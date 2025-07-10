# File: code_prompt_generator/app/utils/system_utils.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import platform, os, subprocess, logging, time
from contextlib import contextmanager
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)

# System & Platform Utilities
# ------------------------------
def open_in_editor(file_path):
    try:
        safe_path = str(Path(file_path))
        if platform.system() == 'Windows':
            try:
                subprocess.Popen(["notepad++", safe_path])
            except FileNotFoundError:
                os.startfile(safe_path)
        elif platform.system() == 'Darwin':
            subprocess.Popen(['open', '--', safe_path])
        else:
            subprocess.Popen(['xdg-open', '--', safe_path])
    except Exception: logger.error("%s", traceback.format_exc())

def open_in_vscode(folder_path):
    try:
        subprocess.Popen(['code', '.'], cwd=str(Path(folder_path)))
        return True
    except FileNotFoundError:
        return False
    except Exception:
        logger.error("%s", traceback.format_exc())
        return False

def get_relative_time_str(dt_ts):
    diff = int(time.time() - dt_ts)
    if diff < 1: return "Now"
    if diff < 60: return f"{diff} seconds ago"
    if diff < 3600: return f"{diff // 60} minutes ago"
    if diff < 86400: return f"{diff // 3600} hours ago"
    return f"{diff // 86400} days ago"

def unify_line_endings(text): return text.replace('\r\n', '\n').replace('\r', '\n')