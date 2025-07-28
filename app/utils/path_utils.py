# File: code_prompt_generator/app/utils/path_utils.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import os, sys, logging, fnmatch
from app.config import BASE_DIR

logger = logging.getLogger(__name__)

# Path & Gitignore Utilities
# ------------------------------
def resource_path(relative_path):
	try: return os.path.join(sys._MEIPASS, relative_path)
	except Exception: return os.path.abspath(os.path.join(BASE_DIR, relative_path))

def parse_gitignore(gitignore_path):
	if not gitignore_path or not os.path.isfile(gitignore_path): return []
	try:
		with open(gitignore_path, 'r', encoding='utf-8') as f:
			return [line.strip() for line in f if line.strip() and not line.startswith('#')]
	except Exception as e:
		logger.warning("Could not read .gitignore at %s: %s", gitignore_path, e, exc_info=True)
		return []

def match_any_gitignore(path_segment, patterns):
	ignored = False
	path_parts = path_segment.split('/')
	for pattern in patterns:
		is_negation = pattern.startswith('!')
		match_pattern = pattern[1:] if is_negation else pattern
		if not match_pattern: continue

		is_match = False
		# Pattern with '/' must match from the start of the relative path
		if '/' in match_pattern.rstrip('/'):
			if fnmatch.fnmatch(path_segment, match_pattern): is_match = True
		# Pattern ending in '/' matches directories anywhere
		elif match_pattern.endswith('/'):
			match_dir = match_pattern.rstrip('/')
			if any(part == match_dir for part in path_parts) and path_segment.endswith('/'):
				is_match = True
		# Other patterns match any path component (file or directory name)
		else:
			if any(fnmatch.fnmatch(part, match_pattern) for part in path_parts): is_match = True
		
		if is_match:
			ignored = not is_negation
	return ignored

def path_should_be_ignored(rel_path, respect_gitignore, gitignore_patterns, keep_patterns, blacklist_patterns):
	path_norm = rel_path.lower().replace("\\", "/")
	path_parts = path_norm.rstrip('/').split('/')
	base_name = path_parts[-1] if path_parts else ''

	# 1. Keep patterns have the highest precedence.
	for kp in keep_patterns:
		kp_norm = kp.strip('/')
		# Keep if path is within a kept dir, or is a parent of a kept path.
		if path_norm.startswith(kp_norm) or kp.startswith(path_norm.rstrip('/')):
			return False
		# Keep if basename matches a wildcard pattern.
		if '/' not in kp and fnmatch.fnmatch(base_name, kp):
			return False
			
	# 2. Blacklist patterns are checked next.
	for bp in blacklist_patterns:
		bp_norm = bp.strip('/')
		# Ignore if path is within a blacklisted dir.
		if path_norm.startswith(bp_norm) and bp_norm:
			return True
		# Ignore if any path component matches a wildcard pattern.
		if '/' not in bp and any(fnmatch.fnmatch(part, bp) for part in path_parts):
			return True

	# 3. Gitignore patterns are checked last.
	if respect_gitignore:
		return match_any_gitignore(path_norm, gitignore_patterns)

	return False