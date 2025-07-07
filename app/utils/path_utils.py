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
    except Exception:
        logger.warning("Could not read .gitignore at %s", gitignore_path, exc_info=True)
        return []

def match_any_gitignore(path_segment, patterns):
    ignored = False
    path_parts = path_segment.split('/')
    for pattern in patterns:
        is_negation = pattern.startswith('!')
        if is_negation:
            pattern = pattern[1:]

        # Directory-only patterns
        if pattern.endswith('/'):
            # This requires checking if the path is a directory, which we don't know here.
            # We match against the path as if it were a directory.
            if fnmatch.fnmatch(path_segment + '/', pattern):
                ignored = not is_negation
            continue

        if '/' in pattern: # Patterns with slashes match against the full path
            if fnmatch.fnmatch(path_segment, pattern):
                ignored = not is_negation
        else: # Patterns without slashes match against any path component
            if any(fnmatch.fnmatch(part, pattern) for part in path_parts):
                ignored = not is_negation
    return ignored

def match_any_keep(path_segment, patterns): return any(fnmatch.fnmatch(path_segment, p) or fnmatch.fnmatch(os.path.basename(path_segment), p) for p in patterns)

def path_should_be_ignored(rel_path, respect_gitignore, gitignore_patterns, keep_patterns, blacklist_patterns):
    rel_path_norm = rel_path.replace("\\", "/").lower()
    path_components = rel_path_norm.split('/')
    
    # Keep patterns override everything
    if match_any_keep(rel_path_norm, keep_patterns):
        return False

    # Blacklist patterns
    is_blacklisted = any(fnmatch.fnmatchcase(comp, p) for comp in path_components for p in blacklist_patterns if '/' not in p) or \
                     any(fnmatch.fnmatch(rel_path_norm, p) or fnmatch.fnmatch(rel_path_norm, f"*/{p}") or fnmatch.fnmatch(rel_path_norm, f"{p}/*") or fnmatch.fnmatch(rel_path_norm, f"*/{p}/*") for p in blacklist_patterns if '/' in p)
    if is_blacklisted:
        return True

    # Gitignore patterns (with negation)
    if respect_gitignore:
        return match_any_gitignore(rel_path_norm, gitignore_patterns)

    return False

def is_dir_forced_kept(dir_path, keep_patterns):
    dir_path_norm = dir_path.strip("/").replace("\\", "/").lower()
    return any(kp.strip("/").replace("\\", "/").lower().startswith(dir_path_norm + "/") or kp.strip("/").replace("\\", "/").lower() == dir_path_norm for kp in keep_patterns)