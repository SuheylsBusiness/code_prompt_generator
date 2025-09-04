# File: app/utils/sanitizer.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization.

import re, os, json, configparser, io, logging
try: import tomllib
except ImportError: tomllib = None
try: import yaml
except ImportError: yaml = None

logger = logging.getLogger(__name__)

# Constants
# ------------------------------
TARGET_EXTENSIONS = {'.env', '.ini', '.toml', '.yaml', '.yml', '.json', '.cfg'}
REDACTION_PLACEHOLDER = '[REDACTED]'

# More aggressive substring matching for all common sensitive terms.
SENSITIVE_KEYWORDS_PATTERN = re.compile(
    r'KEY|TOKEN|blz|pin|product_id|user_id|SECRET|PASSWORD|PASSWORT|DB_MONGO_URL|\b('
    r'PASSWORD|PASSWD|PWORD|AUTH|CERTIFICATE|'
    r'CONN_STR|CONNECTION_STRING|DATABASE_URL|CLIENT_ID|'
    r'CLIENT_SECRET|WEBHOOK_URL|TENANTID|CLIENTID|CLIENTSECRET|REDIRECTURI'
    r')\b',
    re.IGNORECASE
)


# Main Sanitization Logic
# ------------------------------
def sanitize_content(file_path, content, settings_model):
	if not settings_model.get('sanitize_configs_enabled', False) or not content:
		return content, False

	file_type = _identify_file_type(file_path, content)
	if not file_type:
		return content, False

	sanitizers = {
		'json': _sanitize_json,
		'yaml': _sanitize_yaml,
		'toml': _sanitize_toml,
		'ini': _sanitize_ini,
		'env': _sanitize_env
	}
	sanitizer_func = sanitizers.get(file_type)

	if sanitizer_func:
		try:
			sanitized_content, was_changed = sanitizer_func(content)
			return (sanitized_content, was_changed)
		except Exception as e:
			logger.error(f"Sanitizer for type '{file_type}' failed on {file_path}: {e}", exc_info=True)
			# Fallback to a basic regex scan as a last resort on any error
			return _sanitize_line_based(content, r'^\s*([a-zA-Z0-9_.-]+)\s*[:=]\s*(.*)')

	return content, False

# File Type Identification
# ------------------------------
def _identify_file_type(file_path, content):
    filename = os.path.basename(file_path).lower()
    ext = os.path.splitext(filename)[1]

    target_id = None
    if filename in TARGET_EXTENSIONS:
        target_id = filename
    elif ext in TARGET_EXTENSIONS:
        target_id = ext
    else:
        return None

    content_start = content.lstrip()[:4096]
    if not content_start: return None
    
    if target_id == '.json':
        if content_start.startswith('{') or content_start.startswith('['): return 'json'
    elif target_id in ('.yaml', '.yml'):
        if yaml and ':' in content_start.split('\n')[0]: return 'yaml'
    elif target_id == '.toml':
        if tomllib and ('=' in content_start or '[' in content_start): return 'toml'
    elif target_id in ('.ini', '.cfg'):
        for line in content_start.split('\n'):
            line = line.strip()
            if line.startswith('[') and line.endswith(']'):
                return 'ini'
    elif target_id == '.env':
        first_line = next((line for line in content_start.split('\n') if line.strip() and not line.strip().startswith('#')), None)
        if first_line and '=' in first_line: return 'env'
    
    return None

# Format-Specific Sanitizers
# ------------------------------
def _recursive_redact(obj):
	was_changed = False
	if isinstance(obj, dict):
		for key, value in obj.items():
			if SENSITIVE_KEYWORDS_PATTERN.search(str(key)):
				if obj[key] != REDACTION_PLACEHOLDER:
					obj[key] = REDACTION_PLACEHOLDER
					was_changed = True
			else:
				child_changed, new_value = _recursive_redact(value)
				if child_changed:
					obj[key] = new_value
					was_changed = True
	elif isinstance(obj, list):
		for i, item in enumerate(obj):
			child_changed, new_item = _recursive_redact(item)
			if child_changed:
				obj[i] = new_item
				was_changed = True
	elif isinstance(obj, str):
		stripped_val = obj.strip()
		if stripped_val.startswith('{') and stripped_val.endswith('}'):
			try:
				sub_obj = json.loads(obj)
				child_changed, new_sub_obj = _recursive_redact(sub_obj)
				if child_changed:
					return True, json.dumps(new_sub_obj)
			except json.JSONDecodeError:
				pass # Not a valid JSON string, treat as regular string
	return was_changed, obj

def _sanitize_json(content):
	try:
		data = json.loads(content)
		was_changed, sanitized_data = _recursive_redact(data)
		if was_changed: return json.dumps(sanitized_data, indent=2), True
	except json.JSONDecodeError as e:
		logger.warning(f"JSON parsing failed, falling back to regex sanitizer. Error: {e}")
		return _sanitize_line_based(content, r'^\s*"?([a-zA-Z0-9_.-]+)"?\s*:\s*(.*)')
	return content, False

def _sanitize_yaml(content):
	if not yaml: return content, False
	try:
		data = yaml.safe_load(content)
		was_changed, sanitized_data = _recursive_redact(data)
		if was_changed: return yaml.dump(sanitized_data, default_flow_style=False, sort_keys=False), True
	except (yaml.YAMLError, AttributeError) as e:
		logger.warning(f"YAML parsing failed, falling back to regex sanitizer. Error: {e}")
		return _sanitize_line_based(content, r'^\s*"?([a-zA-Z0-9_.-]+)"?\s*:\s*(.*)')
	return content, False

def _sanitize_toml(content):
	return _sanitize_ini(content) # TOML is a superset of INI; configparser can handle most simple cases.

def _sanitize_ini(content):
	try:
		parser = configparser.ConfigParser(interpolation=None, allow_no_value=True, strict=False)
		parser.read_string(content)
		was_changed = False
		for section in parser.sections():
			for key, value in parser.items(section):
				is_sensitive = SENSITIVE_KEYWORDS_PATTERN.search(key)
				val_changed, new_val = _recursive_redact(value)
				if is_sensitive:
					if value != REDACTION_PLACEHOLDER:
						parser.set(section, key, REDACTION_PLACEHOLDER)
						was_changed = True
				elif val_changed:
					parser.set(section, key, new_val)
					was_changed = True
		if was_changed:
			string_io = io.StringIO()
			parser.write(string_io)
			return string_io.getvalue(), True
	except configparser.Error as e:
		logger.warning(f"INI/TOML parsing failed, falling back to regex sanitizer. Error: {e}")
		return _sanitize_line_based(content, r'^\s*([a-zA-Z0-9_.-]+)\s*=\s*(.*)')
	return content, False

def _sanitize_env(content):
	return _sanitize_line_based(content, r'^\s*(?:export\s+)?([a-zA-Z0-9_]+)\s*=\s*(.*)')

# Regex-Based Sanitization Helper
# ------------------------------
def _sanitize_line_based(content, pattern_format):
    lines = content.split('\n')
    was_changed = False
    
    line_pattern = re.compile(pattern_format, re.IGNORECASE)

    for i, line in enumerate(lines):
        # Also check for commented out secrets
        temp_line = line.lstrip()
        is_commented = temp_line.startswith(('#', ';'))
        if is_commented:
            temp_line = temp_line[1:].lstrip()
        
        match = line_pattern.match(temp_line)
        
        if match:
            key = match.group(1).strip()
            original_value = match.group(2).strip()
            
            if SENSITIVE_KEYWORDS_PATTERN.search(key):
                if original_value and original_value.strip("'\"") != REDACTION_PLACEHOLDER:
                    assignment_operator_pos = line.find('=') if '=' in line else line.find(':')
                    if assignment_operator_pos == -1: continue
                    
                    line_prefix = line[:assignment_operator_pos+1]
                    lines[i] = f"{line_prefix.rstrip()} {REDACTION_PLACEHOLDER}"
                    was_changed = True

    if was_changed:
        return '\n'.join(lines), True
    return content, False