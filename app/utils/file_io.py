# File: app/utils/file_io.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization.

import os, json, logging, traceback, time, random, shutil
from filelock import FileLock, Timeout
from app.config import ensure_data_dirs, INSTANCE_ID
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
				if is_fatal and error_queue: error_queue.put(('show_generic_error', ('Lock Timeout', msg)))
				return None if is_fatal else {}
		except json.JSONDecodeError as e:
			backup_path = f"{path}.bak.{int(time.time())}"
			try:
				if os.path.exists(path):
					shutil.copy2(path, backup_path)
					with open(path, 'w', encoding='utf-8') as f: f.write('{}')
					err_msg = (f"Critical data file '{os.path.basename(path)}' is corrupted!\n\n"
							f"Your data has been safely backed up to:\n{backup_path}\n\n"
							"The application will continue with a fresh session.")
				else: err_msg = f"Could not read data file '{os.path.basename(path)}'."
				logger.critical(f"JSONDecodeError for {path}. Backed up to {backup_path}. Error: {e}", exc_info=True)
				if is_fatal: show_error_centered(None, "Critical Data Corruption", err_msg)
			except Exception as backup_e:
				logger.critical(f"Failed to back up corrupted file {path}. Error: {backup_e}", exc_info=True)
				if is_fatal: show_error_centered(None, "Catastrophic Failure", f"Data file '{os.path.basename(path)}' is corrupt AND could not be backed up. Data may be lost.")
			if is_fatal: raise IOError(f"Corrupted data file: {path}") from e
			return {}
		except IOError as e:
			logger.error("Error reading %s: %s\n%s", path, e, traceback.format_exc())
			return {}
	return {}

def atomic_write_with_backup(data, path, lock_path, file_key, error_queue=None):
	from app.config import LAST_OWN_WRITE_TIMES, LAST_OWN_WRITE_TIMES_LOCK
	ensure_data_dirs()
	tmp_path = path + f".tmp.{INSTANCE_ID}"
	bak1_path = path + ".bak1"
	bak2_path = path + ".bak2"

	try:
		with FileLock(lock_path, timeout=10):
			with open(tmp_path, 'w', encoding='utf-8') as f:
				json.dump(data, f, indent=4, ensure_ascii=False)
			
			if os.path.exists(bak1_path):
				try:
					os.replace(bak1_path, bak2_path)
				except OSError:
					if os.path.exists(bak2_path):
						try: os.remove(bak2_path)
						except OSError as e: logger.warning(f"Failed to remove stale backup {bak2_path}: {e}")
					os.rename(bak1_path, bak2_path)

			if os.path.exists(path):
				try:
					os.rename(path, bak1_path)
				except OSError as e:
					logger.warning(f"Failed to create backup for {path}: {e}")

			os.replace(tmp_path, path)
			logger.info("Saved %s successfully.", path)

			if file_key:
				try:
					mtime = os.path.getmtime(path)
					with LAST_OWN_WRITE_TIMES_LOCK:
						LAST_OWN_WRITE_TIMES[file_key] = mtime
				except (OSError, AttributeError):
					pass
		return True
	except Timeout as e:
		msg = f"Could not acquire lock for writing {os.path.basename(path)}. Your changes were not saved."
		logger.error(msg)
		if error_queue: error_queue.put(('show_generic_error', ('Save Failed', msg)))
		return False
	except (IOError, OSError) as e:
		logger.error("Error in atomic_write_with_backup for %s: %s", path, e, exc_info=True)
		return False
	finally:
		if os.path.exists(tmp_path):
			try: os.remove(tmp_path)
			except OSError: pass

def safe_read_file(path):
	try: return Path(path).read_text(encoding='utf-8-sig', errors='replace')
	except PermissionError: logger.warning("Permission denied for file %s", path); return ""
	except (OSError, IOError) as e: logger.error("Failed to read file %s: %s", path, e); return ""
	except Exception as e: logger.error("Unexpected error reading file %s: %s", path, e, exc_info=True); return ""