# File: code_prompt_generator/app/utils/cache_utils.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import os, json, hashlib, time, logging, traceback
from filelock import FileLock, Timeout
from app.config import PROJECTS_DIR, INSTANCE_ID, CACHE_EXPIRY_SECONDS
from app.utils.migration_utils import get_safe_project_foldername

logger = logging.getLogger(__name__)

# Cache & Hashing Utilities
# ------------------------------
def get_file_hash(file_path):
    try:
        h = hashlib.md5()
        with open(file_path, 'rb') as f:
            while chunk := f.read(65536): h.update(chunk)
        h.update(str(os.path.getmtime(file_path)).encode('utf-8'))
        return h.hexdigest()
    except Exception as e: logger.error("Failed to get file hash for %s: %s", file_path, e); return None

def get_cache_key(selected_files, file_hashes):
    d = ''.join(sorted([f + file_hashes.get(f, '') for f in selected_files]))
    return hashlib.md5(d.encode('utf-8')).hexdigest()

def get_cached_output(project_name, cache_key):
    if not project_name: return None
    folder_name = get_safe_project_foldername(project_name)
    cf = os.path.join(PROJECTS_DIR, folder_name, 'cache.json')
    if not os.path.exists(cf): return None
    try:
        with FileLock(cf + '.lock', timeout=2):
            c = {}
            try:
                with open(cf,'r',encoding='utf-8') as f: c = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            now_t = time.time()
            stale = [k for k, v in c.items() if not isinstance(v, dict) or (now_t - v.get('time', 0) > CACHE_EXPIRY_SECONDS)]
            if stale:
                for sk in stale:
                    del c[sk]
                with open(cf, 'w', encoding='utf-8') as f:
                    json.dump(c, f, indent=4, ensure_ascii=False)
            entry = c.get(cache_key)
            return entry.get('data') if isinstance(entry, dict) else None
    except (Timeout, IOError, OSError) as e:
        logger.warning("Could not read cache for %s: %s", project_name, e)
    except Exception as e: logger.error("Exception reading cache: %s", e, exc_info=True)
    return None

def save_cached_output(project_name, cache_key, output, full_cache_data=None):
    if not project_name: return
    folder_name = get_safe_project_foldername(project_name)
    project_folder = os.path.join(PROJECTS_DIR, folder_name)
    os.makedirs(project_folder, exist_ok=True)
    cf = os.path.join(project_folder, 'cache.json')
    lock_path = cf + '.lock'
    try:
        with FileLock(lock_path, timeout=5):
            c = {}
            if full_cache_data is not None: c = full_cache_data
            elif os.path.exists(cf):
                try:
                    with open(cf, 'r', encoding='utf-8') as f: c = json.load(f)
                except (json.JSONDecodeError, IOError): pass
            if cache_key is not None: c[cache_key] = {"time": time.time(), "data": output}
            tmp_path = cf + f".tmp.{INSTANCE_ID}"
            with open(tmp_path, 'w', encoding='utf-8') as f: json.dump(c, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, cf)
    except Timeout: logger.error("Timeout saving cache for %s", project_name)
    except Exception as e: logger.error("Exception saving cache: %s", e, exc_info=True)