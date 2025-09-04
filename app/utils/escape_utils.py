# File: app/utils/escape_utils.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization.

import codecs

# --- Safe Escape/Unescape ---
def safe_escape(txt: str) -> str:
	return txt.encode('unicode_escape').decode('ascii')

def safe_unescape(txt: str) -> str:
	return codecs.decode(txt, 'unicode_escape')