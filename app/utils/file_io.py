# File: code_prompt_generator/app/utils/file_io.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import os, json, logging, traceback, time, random
from filelock import FileLock, Timeout
from app.config import ensure_data_dirs, INSTANCE_ID, LAST_OWN_WRITE_TIMES

logger = logging.getLogger(__name__)

# File I/O & Locking Utilities
# ------------------------------
def load_json_safely(path, lock_path, error_queue=None, is_fatal=False):
    ensure_data_dirs()
    for attempt in range(5):
        try:
            with FileLock(lock_path, timeout=1):
                if not os.path.exists(path): return {}
                with open(path, 'r', encoding='utf-8') as f: return json.load(f)
        except Timeout:
            logger.warning(f"Lock timeout for {path} on attempt {attempt + 1}")
            if attempt < 4: time.sleep(0.5 + random.uniform(0, 0.5))
            else:
                msg = f"Could not acquire lock for reading {os.path.basename(path)}. Another instance may be busy."
                logger.error(msg)
                if error_queue: error_queue.put(('show_warning', ('Lock Timeout', msg)))
                return None if is_fatal else {}
        except (json.JSONDecodeError, IOError) as e:
            logger.error("Error reading %s: %s\n%s", path, e, traceback.format_exc())
            return {}
    return {}

def atomic_write_json(data, path, lock_path, file_key, error_queue=None):
    ensure_data_dirs()
    try:
        with FileLock(lock_path, timeout=5):
            old_data = {}
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f: old_data = json.load(f)
                except (json.JSONDecodeError, IOError): logger.warning("Could not read old data from %s, will overwrite.", path)
            if old_data == data: return
            tmp_path = path + f".tmp.{INSTANCE_ID}"
            with open(tmp_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, path)
            LAST_OWN_WRITE_TIMES[file_key] = os.path.getmtime(path)
            logger.info("Saved %s successfully.", path)
    except Timeout:
        msg = f"Could not acquire lock for writing {os.path.basename(path)}. Your changes were not saved."
        logger.error(msg)
        if error_queue: error_queue.put(('show_warning', ('Save Skipped', msg)))
    except Exception as e:
        logger.error("Error in atomic_write_json for %s: %s\n%s", path, e, traceback.format_exc())

def safe_read_file(path):
    try: return open(path,'r',encoding='utf-8-sig',errors='replace').read()
    except Exception: logger.error("%s", traceback.format_exc()); return ""