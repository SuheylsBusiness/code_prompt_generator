# File: code_prompt_generator/app/custom_scripts/header_formatter.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import os, json
from pathlib import Path
from app.config import get_logger
from app.utils.ui_helpers import show_error_centered

logger = get_logger(__name__)

# Defaults
# ------------------------------
DEFAULT_HEADER_CONFIG = {
	".py": {
		"token": "#",
		"llm_note": "LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization."
	},
	".js": {
		"token": "//",
		"block_start": "/*",
		"block_end": "*/",
		"llm_note": "LLM NOTE: LLM Editor, follow these code style guidelines: (1) Keep the file path comment, LLM note, and grouping comments; (2) No extra comments or docstrings; (3) Favor concise single-line or inline code; (4) Preserve code structure and organization as given."
	},
	".ejs": {
		"token_start": "<!--",
		"token_end": "-->",
		"llm_note": "LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or explanatory comments; (2) Retain the file path comment, this LLM note, and grouping comments; (3) Use single-line or inline code without altering functionality; (4) No additional comments beyond these markers; (5) Preserve code structure and organization as given; (6) For any JS: organize from least to most important, placing core logic last, grouped under markers (e.g., // Main Logic)."
	}
}

SPECIAL_WS = "\u00A0"

# Helpers
# ------------------------------
def _validate_cfg(cfg):
	if not isinstance(cfg, dict): return False
	for ext, c in cfg.items():
		if not isinstance(ext, str) or not isinstance(c, dict): return False
		if "llm_note" not in c: return False
		if "token" not in c and not ("token_start" in c and "token_end" in c): return False
	return True

def _find_content_start(lines, ext, cfg):
	if ext == ".js":
		token = cfg.get("token", "//"); bs = cfg.get("block_start", "/*"); be = cfg.get("block_end", "*/")
		in_block = False
		for i, ln in enumerate(lines):
			s = ln.strip()
			if not s: continue
			if in_block:
				if be in s: in_block = False
				continue
			if s.startswith(token): continue
			if s.startswith(bs):
				if be not in s: in_block = True
				continue
			return i
		return len(lines)
	if ext == ".ejs":
		in_html = False; in_ejs = False
		for i, ln in enumerate(lines):
			s = ln.strip()
			if not s: continue
			if in_html:
				if "-->" in s: in_html = False
				continue
			if in_ejs:
				if "%>" in s: in_ejs = False
				continue
			if s.startswith("<!--"):
				if "-->" not in s: in_html = True
				continue
			if s.startswith("<%#"):
				if "%>" not in s: in_ejs = True
				continue
			return i
		return len(lines)
	comment_marker = cfg.get("token") or cfg.get("token_start")
	for i, ln in enumerate(lines):
		s = ln.strip()
		if not s or (comment_marker and s.startswith(comment_marker)): continue
		return i
	return len(lines)

def _build_header(relative_path, c):
	h = []
	if "token" in c:
		h.append(f"{c['token']} File: {relative_path}\n")
		h.append(f"{c['token']} {c['llm_note']}\n")
	else:
		start, end = c['token_start'], c['token_end']
		h.append(f"{start} FILE: {relative_path} {end}\n")
		h.append(f"{start} {c['llm_note']} {end}\n")
	return h

def _process_one(abs_path, rel_path, root_dir, header_cfg):
	try:
		with open(abs_path, 'r', encoding='utf-8-sig') as f:
			lines = f.readlines()
	except UnicodeDecodeError:
		return {"changed": False, "ws": 0, "skipped": True, "reason": "non-utf8"}, None
	except Exception as e:
		return {"changed": False, "ws": 0, "skipped": True, "reason": str(e)}, None

	ws_count = sum(ln.count(SPECIAL_WS) for ln in lines)
	if ws_count: lines = [ln.replace(SPECIAL_WS, " ") for ln in lines]

	ext = Path(abs_path).suffix.lower()
	if ext not in header_cfg:
		if ws_count:
			try:
				with open(abs_path, 'w', encoding='utf-8', newline='') as f: f.writelines(lines)
				return {"changed": True, "ws": ws_count, "skipped": False}, None
			except Exception as e:
				return {"changed": False, "ws": ws_count, "skipped": True, "reason": str(e)}, None
		return {"changed": False, "ws": 0, "skipped": False}, None

	cfg = header_cfg[ext]
	first_idx = _find_content_start(lines, ext, cfg)
	body = lines[first_idx:]
	header = _build_header(rel_path, cfg)
	new_lines = header + ["\n"] + body

	orig_text = "".join(lines)
	new_text = "".join(new_lines)
	if orig_text == new_text and not ws_count:
		return {"changed": False, "ws": 0, "skipped": False}, None

	try:
		with open(abs_path, 'w', encoding='utf-8', newline='') as f: f.writelines(new_lines)
		return {"changed": True, "ws": ws_count, "skipped": False}, None
	except Exception as e:
		return {"changed": False, "ws": ws_count, "skipped": True, "reason": str(e)}, None

# Script
# ------------------------------
class HeaderFormatterScript:
	def __init__(self, controller):
		self.controller = controller

	def _load_header_config(self, project_root):
		settings = self.controller.settings_model
		template_name = "[CSTM]: Header Formatter Config"
		warnings = []
		cfg = None
		tpl = settings.get_template_content(template_name)
		if not tpl:
			show_error_centered(self.controller.view, "Missing Template", f"Template '{template_name}' not found. Falling back to 'header_config.json' in the project root.")
		else:
			try:
				parsed = json.loads(tpl)
				if _validate_cfg(parsed): cfg = parsed
				else:
					show_error_centered(self.controller.view, "Invalid Config Template", f"Template '{template_name}' is invalid JSON or missing required fields. Falling back to 'header_config.json'.")
			except Exception:
				show_error_centered(self.controller.view, "Invalid Config Template", f"Template '{template_name}' is not valid JSON. Falling back to 'header_config.json'.")

		if cfg is not None:
			return cfg, warnings

		cfg_path = os.path.join(project_root, "header_config.json")
		if os.path.isfile(cfg_path):
			try:
				with open(cfg_path, 'r', encoding='utf-8') as f:
					data = json.load(f)
				if _validate_cfg(data): return data, warnings
				warnings.append("header_config.json is invalid; using defaults.")
			except Exception as e:
				warnings.append(f"Failed to read header_config.json: {e}")

		try:
			with open(cfg_path, 'w', encoding='utf-8') as f: json.dump(DEFAULT_HEADER_CONFIG, f, indent=2, ensure_ascii=False)
		except Exception as e:
			warnings.append(f"Could not create header_config.json: {e}")
		return DEFAULT_HEADER_CONFIG, warnings

	def run(self, root_dir, visible_relative_paths):
		if not root_dir or not os.path.isdir(root_dir):
			return {"script_id": "header_formatter", "ok": False, "error": "Project directory is invalid."}
		cfg, warn_list = self._load_header_config(root_dir)
		total = len(visible_relative_paths)
		updated = 0
		updated_files = []
		warnings = list(warn_list)
		ws_total = 0
		skipped = 0

		for rp in visible_relative_paths:
			abs_path = os.path.join(root_dir, rp)
			if not os.path.isfile(abs_path): 
				warnings.append(f"Missing file: {rp}")
				continue
			stats, _ = _process_one(abs_path, rp.replace("\\", "/"), root_dir, cfg)
			if stats.get("skipped"): 
				skipped += 1
				reason = stats.get("reason")
				if reason: warnings.append(f"Skipped {rp}: {reason}")
				continue
			if stats.get("changed"):
				updated += 1
				updated_files.append(rp)
			ws_total += stats.get("ws", 0)

		return {
			"script_id": "header_formatter",
			"ok": True,
			"total": total,
			"updated": updated,
			"updated_files": updated_files,
			"ws": ws_total,
			"warnings": warnings,
			"had_warnings": bool(warnings)
		}