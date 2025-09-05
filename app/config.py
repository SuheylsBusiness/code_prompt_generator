# File: app/config.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization.

import os, configparser, random, string, logging, sys, threading
from libs.logging_setup.setup_logging import DailyFileHandler, HierarchicalFormatter, HierarchyFilter

# Constants & Configuration
# ------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
PROJECTS_DIR = os.path.join(DATA_DIR, "projects") # New projects directory
OUTPUT_DIR = os.path.join(DATA_DIR, "outputs")
SETTINGS_FILE = os.path.join(CACHE_DIR, 'settings.json')
SETTINGS_LOCK_FILE = os.path.join(CACHE_DIR, 'settings.json.lock')
TEMPLATES_FILE = os.path.join(CACHE_DIR, 'templates.json')
TEMPLATES_LOCK_FILE = os.path.join(CACHE_DIR, 'templates.json.lock')
HISTORY_FILE = os.path.join(CACHE_DIR, 'history.json')
HISTORY_LOCK_FILE = os.path.join(CACHE_DIR, 'history.json.lock')
LAST_OWN_WRITE_TIMES = {"settings": 0, "templates": 0, "history": 0}
LAST_OWN_WRITE_TIMES_LOCK = threading.Lock()
INSTANCE_ID = f"{os.getpid()}-{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}"
LOG_PATH = os.path.join(DATA_DIR, "logs")
_CONSOLE_HANDLERS = []

# Configurable Limits (with defaults)
CACHE_EXPIRY_SECONDS = 3600
MAX_FILES = 500
MAX_CONTENT_SIZE = 2000000
MAX_FILE_SIZE = 500000
FILE_WATCHER_INTERVAL_MS = 10000
PERIODIC_SAVE_INTERVAL_SECONDS = 30
PROCESS_POOL_THRESHOLD_KB = 200

# App Setup & Initialization
# ------------------------------
def load_config():
	config = configparser.ConfigParser()
	config_path = os.path.join(BASE_DIR, 'config.ini')
	if not os.path.exists(config_path): sys.stderr.write("Configuration Error: config.ini file not found.\n"); sys.exit(1)
	config.read(config_path, encoding='utf-8')
	global CACHE_EXPIRY_SECONDS, MAX_FILES, MAX_CONTENT_SIZE, MAX_FILE_SIZE, FILE_WATCHER_INTERVAL_MS, PERIODIC_SAVE_INTERVAL_SECONDS, PROCESS_POOL_THRESHOLD_KB
	try:
		CACHE_EXPIRY_SECONDS = config.getint('Limits','CACHE_EXPIRY_SECONDS', fallback=3600)
		MAX_FILES = config.getint('Limits','MAX_FILES', fallback=500)
		MAX_CONTENT_SIZE = config.getint('Limits','MAX_CONTENT_SIZE', fallback=2000000)
		MAX_FILE_SIZE = config.getint('Limits','MAX_FILE_SIZE', fallback=500000)
		FILE_WATCHER_INTERVAL_MS = config.getint('Limits', 'FILE_WATCHER_INTERVAL_MS', fallback=10000)
		PERIODIC_SAVE_INTERVAL_SECONDS = config.getint('Limits', 'PERIODIC_SAVE_INTERVAL_SECONDS', fallback=30)
		PROCESS_POOL_THRESHOLD_KB = config.getint('Limits', 'PROCESS_POOL_THRESHOLD_KB', fallback=200)
	except (configparser.Error, ValueError) as e: logging.warning("Could not parse config.ini, using defaults. Error: %s", e)

def ensure_data_dirs():
	os.makedirs(CACHE_DIR, exist_ok=True)
	os.makedirs(OUTPUT_DIR, exist_ok=True)
	os.makedirs(LOG_PATH, exist_ok=True)
	os.makedirs(PROJECTS_DIR, exist_ok=True)

class InstanceLogAdapter(logging.LoggerAdapter):
	def process(self, msg, kwargs): return f"[{self.extra['instance_id']}] {msg}", kwargs

def get_logger(name):
	logger = logging.getLogger(name)
	return InstanceLogAdapter(logger, {'instance_id': INSTANCE_ID})

def initialize_logging():
	from libs.logging_setup.setup_logging import setup_logging
	_root_logger = setup_logging(log_level=logging.INFO, excluded_files=['server.py'], log_path=os.path.join(LOG_PATH, "general"))
	global _CONSOLE_HANDLERS
	_CONSOLE_HANDLERS[:] = [h for h in _root_logger.handlers if isinstance(h, logging.StreamHandler)]

def set_project_file_handler(project_name: str):
	root = logging.getLogger()
	old_handler = next((h for h in list(root.handlers) if isinstance(h, DailyFileHandler)), None)

	sanitized = "".join(c for c in project_name if c.isalnum() or c in (' ', '_', '-')).rstrip() if project_name else "general"
	safe_project_name = os.path.basename(sanitized) if sanitized else "general"
	log_dir = os.path.join(LOG_PATH, safe_project_name)
	os.makedirs(log_dir, exist_ok=True)

	fh = DailyFileHandler(log_dir=log_dir, log_prefix="app", encoding="utf-8", delay=True)
	fh.setLevel(logging.INFO)
	fh.addFilter(HierarchyFilter())
	fh.setFormatter(HierarchicalFormatter("%(asctime)s - %(func_hierarchy)s - %(levelname)s - %(message)s"))
	root.addHandler(fh)

	if old_handler:
		root.removeHandler(old_handler)
		try: old_handler.close()
		except Exception: pass

	for ch in _CONSOLE_HANDLERS:
		if ch not in root.handlers: root.addHandler(ch)
	get_logger(__name__).info("Switched file logging to %s", project_name or "general")

load_config()
ensure_data_dirs()