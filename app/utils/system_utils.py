# File: code_prompt_generator/app/utils/system_utils.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import platform, os, subprocess, logging, time
from contextlib import contextmanager
import traceback

logger = logging.getLogger(__name__)

# System & Platform Utilities
# ------------------------------
def open_in_editor(file_path):
    try:
        if platform.system() == 'Windows':
            try:
                subprocess.Popen(["notepad++", file_path])
            except FileNotFoundError:
                os.startfile(file_path)
        elif platform.system() == 'Darwin': subprocess.call(('open', file_path))
        else: subprocess.call(('xdg-open', file_path))
    except Exception: logger.error("%s", traceback.format_exc())

def get_relative_time_str(dt_ts):
    diff = int(time.time() - dt_ts)
    if diff < 1: return "Now"
    if diff < 60: return f"{diff} seconds ago"
    if diff < 3600: return f"{diff // 60} minutes ago"
    if diff < 86400: return f"{diff // 3600} hours ago"
    return f"{diff // 86400} days ago"

def unify_line_endings(text): return text.replace('\r\n', '\n').replace('\r', '\n')

# Trace Suspension Utilities
# ------------------------------
@contextmanager
def suspend_var_traces(vars_):
    saved = []
    for v in vars_:
        try:
            info = v.trace_info()
            saved.append((v, info))
            for mode, cb in info: v.trace_remove(mode, cb)
        except Exception: pass
    try: yield
    finally:
        for v, info in saved:
            for mode, cb in info:
                try: v.trace_add(mode, cb)
                except Exception: pass