# File: app/utils/path_utils.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization.

import os, sys, logging, fnmatch
from app.config import BASE_DIR

logger = logging.getLogger(__name__)

# Path & Gitignore Utilities
# ------------------------------
def resource_path(relative_path):
	try: return os.path.join(sys._MEIPASS, relative_path)
	except Exception: return os.path.abspath(os.path.join(BASE_DIR, relative_path))

def normalize_path(path_str): return path_str.replace("\\", "/")

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
		if '/' in match_pattern.rstrip('/'):
			if fnmatch.fnmatch(path_segment, match_pattern): is_match = True
		elif match_pattern.endswith('/'):
			match_dir = match_pattern.rstrip('/')
			if any(part == match_dir for part in path_parts) and path_segment.endswith('/'):
				is_match = True
		else:
			if any(fnmatch.fnmatch(part, match_pattern) for part in path_parts): is_match = True
		
		if is_match:
			ignored = not is_negation
	return ignored

def path_should_be_ignored(rel_path, respect_gitignore, gitignore_patterns, keep_patterns, blacklist_patterns):
	path_norm = normalize_path(rel_path.lower())
	is_dir_path = path_norm.endswith('/')
	path_parts = path_norm.rstrip('/').split('/')
	base_name = path_parts[-1] if path_parts else ''
	def _norm(p): return normalize_path(p.strip().lower())

	for kp in keep_patterns:
		kp = _norm(kp)
		if not kp: continue
		if '/' not in kp:
			if fnmatch.fnmatch(base_name, kp): return False
		elif kp.endswith('/'):
			dir_pat = kp.rstrip('/')
			if is_dir_path and (path_norm == kp or path_norm.startswith(kp)): return False
			if not is_dir_path and path_norm.startswith(dir_pat + '/'): return False
		else:
			if not is_dir_path and path_norm == kp: return False
			
	for bp in blacklist_patterns:
		bp = _norm(bp)
		if not bp: continue
		is_match = False
		if '/' not in bp:
			if any(fnmatch.fnmatch(part, bp) for part in path_parts): is_match = True
		elif bp.endswith('/'):
			dir_pat = bp.rstrip('/')
			if path_norm == bp or path_norm.startswith(bp): is_match = True
			if f"/{dir_pat}/" in f"/{path_norm}": is_match = True
		else:
			if path_norm == bp or fnmatch.fnmatch(path_norm, bp): is_match = True
			if path_norm.startswith(bp + '/'): is_match = True
		
		if is_match:
			if is_dir_path and any(_norm(kp).startswith(path_norm) for kp in keep_patterns):
				continue
			return True

	if respect_gitignore:
		return match_any_gitignore(path_norm, gitignore_patterns)

	return False