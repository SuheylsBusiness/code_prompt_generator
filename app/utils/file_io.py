# File: code_prompt_generator/app/utils/file_io.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import os, json, logging, traceback, time, random, shutil
from filelock import FileLock, Timeout
from app.config import ensure_data_dirs, INSTANCE_ID, LAST_OWN_WRITE_TIMES, LAST_OWN_WRITE_TIMES_LOCK
from pathlib import Path
from app.utils.ui_helpers import show_error_centered

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
		except json.JSONDecodeError as e:
			backup_path = f"{path}.bak.{int(time.time())}"
			try:
				if os.path.exists(path):
					# Use copy instead of rename to avoid file lock issues from external editors/watchers.
					shutil.copy2(path, backup_path)
					# Overwrite the corrupt file with a valid empty one.
					with open(path, 'w', encoding='utf-8') as f: f.write('{}')
					err_msg = (f"Critical data file '{os.path.basename(path)}' is corrupted!\n\n"
							   f"Your data has been safely backed up to:\n{backup_path}\n\n"
							   "The application will continue with a fresh session.")
				else: err_msg = f"Could not read data file '{os.path.basename(path)}'."
				logger.critical(f"JSONDecodeError for {path}. Backed up to {backup_path}. Error: {e}", exc_info=True)
				show_error_centered(None, "Critical Data Corruption", err_msg)
			except Exception as backup_e:
				logger.critical(f"Failed to back up corrupted file {path}. Error: {backup_e}")
				show_error_centered(None, "Catastrophic Failure", f"Data file '{os.path.basename(path)}' is corrupt AND could not be backed up. Data may be lost.")
			if is_fatal: raise IOError(f"Corrupted data file: {path}") from e
			return {}
		except IOError as e:
			logger.error("Error reading %s: %s\n%s", path, e, traceback.format_exc())
			return {}
	return {}

def atomic_write_with_backup(data, path, lock_path, file_key, error_queue=None):
    """
    Atomically writes a JSON file and maintains a rotating backup system
    (file.json, file.json.bak1, file.json.bak2).
    """
    ensure_data_dirs()
    tmp_path = path + f".tmp.{INSTANCE_ID}"
    bak1_path = path + ".bak1"
    bak2_path = path + ".bak2"

    try:
        with FileLock(lock_path, timeout=10):
            # Check for changes before performing expensive I/O
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        if json.load(f) == data:
                            logger.debug("Skipped saving %s, no changes detected.", os.path.basename(path))
                            return True
                except (json.JSONDecodeError, IOError):
                    pass # Will proceed to overwrite the corrupt file

            # 1. Rotate backups
            if os.path.exists(bak1_path):
                try: os.replace(bak1_path, bak2_path)
                except OSError: # On windows, os.replace fails if dest exists
                    if os.path.exists(bak2_path): os.remove(bak2_path)
                    os.rename(bak1_path, bak2_path)
            
            if os.path.exists(path):
                os.rename(path, bak1_path)

            # 2. Write new file
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, path)
            logger.info("Saved %s successfully.", path)

            # 3. Update write time for file watcher
            if file_key:
                with LAST_OWN_WRITE_TIMES_LOCK:
                    LAST_OWN_WRITE_TIMES[file_key] = os.path.getmtime(path)
        return True
    except Timeout as e:
        msg = f"Could not acquire lock for writing {os.path.basename(path)}. Your changes were not saved."
        logger.error(msg)
        if error_queue: error_queue.put(('show_generic_error', ('Save Failed', msg)))
        raise e
    except (IOError, OSError) as e:
        logger.error("Error in atomic_write_with_backup for %s: %s\n%s", path, e, traceback.format_exc())
        return False
    finally:
        if os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except OSError: pass

def safe_read_file(path):
	try: return Path(path).read_text(encoding='utf-8-sig', errors='replace')
	except PermissionError: return ""
	except (OSError, IOError) as e: logger.error("Failed to read file %s: %s", path, e); return ""