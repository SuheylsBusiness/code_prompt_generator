# File: code_prompt_generator/main.pyw
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import sys, os, logging, traceback, configparser, tkinter as tk, json, threading, hashlib, queue, platform, subprocess, fnmatch, time, tempfile, random, string, copy, codecs, re
from libs.logging_setup.setup_logging import DailyFileHandler, HierarchicalFormatter, HierarchyFilter
from tkinter import filedialog, ttk, simpledialog, scrolledtext
from filelock import FileLock, Timeout
from datetime import datetime
from contextlib import contextmanager
import tkinter.font as tkfont

# Constants & Configuration
# ------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
OUTPUT_DIR = os.path.join(DATA_DIR, "outputs")
PROJECTS_FILE = os.path.join(CACHE_DIR, 'projects.json')
SETTINGS_FILE = os.path.join(CACHE_DIR, 'settings.json')
PROJECTS_LOCK_FILE = os.path.join(CACHE_DIR, 'projects.json.lock')
SETTINGS_LOCK_FILE = os.path.join(CACHE_DIR, 'settings.json.lock')
HISTORY_SELECTION_KEY = "history_selection"
LAST_OWN_WRITE_TIMES = {"projects": 0, "settings": 0}
config = configparser.ConfigParser()
MAX_FILES = 500
MAX_CONTENT_SIZE = 2000000
MAX_FILE_SIZE = 500000
CACHE_EXPIRY_SECONDS = 3600

# Logging Setup
# ------------------------------
INSTANCE_ID = f"{os.getpid()}-{ ''.join(random.choices(string.ascii_lowercase + string.digits, k=6)) }"
log_path = os.path.join(DATA_DIR, "logs")
class InstanceLogAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs): return f"[{self.extra['instance_id']}] {msg}", kwargs
logger = logging.getLogger(__name__)
logger = InstanceLogAdapter(logger, {'instance_id': INSTANCE_ID})
# keep root console handler; remember it
from libs.logging_setup.setup_logging import setup_logging
_root_logger = setup_logging(log_level=logging.INFO, excluded_files=['server.py'], log_path=os.path.join(log_path, "general"))
_console_handlers = [h for h in _root_logger.handlers if isinstance(h, logging.StreamHandler)]

# App Setup & Initialization
# ------------------------------
def load_config():
    config_path = os.path.join(BASE_DIR, 'config.ini')
    if not os.path.exists(config_path): show_error_centered(None,"Configuration Error","config.ini file not found."); sys.exit()
    config.read(config_path, encoding='utf-8')
    global CACHE_EXPIRY_SECONDS, MAX_FILES, MAX_CONTENT_SIZE, MAX_FILE_SIZE
    try:
        CACHE_EXPIRY_SECONDS = config.getint('Limits','CACHE_EXPIRY_SECONDS', fallback=3600)
        MAX_FILES = config.getint('Limits','MAX_FILES', fallback=500)
        MAX_CONTENT_SIZE = config.getint('Limits','MAX_CONTENT_SIZE', fallback=2000000)
        MAX_FILE_SIZE = config.getint('Limits','MAX_FILE_SIZE', fallback=500000)
    except Exception: pass

def ensure_data_dirs():
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

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

def load_projects(error_queue=None): return load_json_safely(PROJECTS_FILE, PROJECTS_LOCK_FILE, error_queue, is_fatal=True)
def save_projects(projects_data, error_queue=None): atomic_write_json(projects_data, PROJECTS_FILE, PROJECTS_LOCK_FILE, "projects", error_queue)
def load_settings(error_queue=None): return load_json_safely(SETTINGS_FILE, SETTINGS_LOCK_FILE, error_queue, is_fatal=True)
def save_settings(settings_data, error_queue=None): atomic_write_json(settings_data, SETTINGS_FILE, SETTINGS_LOCK_FILE, "settings", error_queue)
def safe_read_file(path):
    try: return open(path,'r',encoding='utf-8-sig',errors='replace').read()
    except Exception: logger.error("%s", traceback.format_exc()); return ""

# Cache & Hashing Utilities
# ------------------------------
def get_file_hash(file_path):
    try:
        h = hashlib.md5()
        with open(file_path, 'rb') as f:
            while chunk := f.read(65536): h.update(chunk)
        h.update(str(os.path.getmtime(file_path)).encode('utf-8'))
        return h.hexdigest()
    except Exception: logger.error("%s", traceback.format_exc()); return None

def get_cache_key(selected_files, file_hashes):
    d = ''.join(sorted([f + file_hashes.get(f, '') for f in selected_files]))
    return hashlib.md5(d.encode('utf-8')).hexdigest()

def get_cached_output(project_name, cache_key):
    ensure_data_dirs()
    cf = os.path.join(CACHE_DIR, f'cache_{project_name}.json')
    if not os.path.exists(cf): return None
    try:
        with FileLock(cf + '.lock', timeout=2):
            with open(cf,'r',encoding='utf-8') as f: c = json.load(f)
        now_t = time.time()
        stale = [k for k, v in c.items() if not isinstance(v, dict) or (now_t - v.get('time', 0) > CACHE_EXPIRY_SECONDS)]
        if stale:
            for sk in stale: del c[sk]
            save_cached_output(project_name, None, None, full_cache_data=c)
        entry = c.get(cache_key)
        return entry.get('data') if isinstance(entry, dict) else None
    except (Timeout, json.JSONDecodeError, IOError, OSError) as e:
        logger.warning("Could not read cache for %s: %s", project_name, e)
    except Exception: logger.error("%s", traceback.format_exc())
    return None

def save_cached_output(project_name, cache_key, output, full_cache_data=None):
    ensure_data_dirs()
    cf = os.path.join(CACHE_DIR, f'cache_{project_name}.json')
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
    except Exception: logger.error("%s", traceback.format_exc())

# Path & Gitignore Utilities
# ------------------------------
def resource_path(relative_path):
    try: return os.path.join(sys._MEIPASS, relative_path)
    except Exception: return os.path.abspath(os.path.join(".", relative_path))

def parse_gitignore(gitignore_path):
    # If the project has no .gitignore, treat it as an empty list (no log noise)
    if not gitignore_path or not os.path.isfile(gitignore_path):
        return []
    try:
        with open(gitignore_path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except Exception:
        # Downgrade to warning – ignore unreadable files quietly
        logger.warning("Could not read .gitignore at %s", gitignore_path, exc_info=True)
        return []

def match_any_gitignore(path_segment, patterns): return any(fnmatch.fnmatch(path_segment, p) or fnmatch.fnmatch(os.path.basename(path_segment), p) for p in patterns)
def match_any_keep(path_segment, patterns): return any(fnmatch.fnmatch(path_segment, p) or fnmatch.fnmatch(os.path.basename(path_segment), p) for p in patterns)

def path_should_be_ignored(rel_path, respect_gitignore, gitignore_patterns, keep_patterns, blacklist_patterns):
    rel_path_norm = rel_path.replace("\\", "/").lower()
    is_blacklisted = any(bp in rel_path_norm for bp in blacklist_patterns)
    is_gitignored = respect_gitignore and match_any_gitignore(rel_path_norm, gitignore_patterns)
    if match_any_keep(rel_path_norm, keep_patterns): return False
    return is_blacklisted or is_gitignored

def is_dir_forced_kept(dir_path, keep_patterns):
    dir_path_norm = dir_path.strip("/").replace("\\", "/").lower()
    return any(kp.strip("/").replace("\\", "/").lower().startswith(dir_path_norm + "/") or kp.strip("/").replace("\\", "/").lower() == dir_path_norm for kp in keep_patterns)

# Formatting & String Utilities
# ------------------------------
def format_german_thousand_sep(num): return f"{num:,}".replace(",", ".")
def unify_line_endings(text): return text.replace('\r\n', '\n').replace('\r', '\n')

def get_relative_time_str(dt_ts):
    diff = int(time.time() - dt_ts)
    if diff < 1: return "Now"
    if diff < 60: return f"{diff} seconds ago"
    if diff < 3600: return f"{diff // 60} minutes ago"
    if diff < 86400: return f"{diff // 3600} hours ago"
    if diff < 2592000: return f"{diff // 86400} days ago"
    return "30+ days ago"

# System & Platform Utilities
# ------------------------------
def open_in_editor(file_path):
    try:
        if platform.system() == 'Windows': os.startfile(file_path)
        elif platform.system() == 'Darwin': subprocess.call(('open', file_path))
        else: subprocess.call(('xdg-open', file_path))
    except Exception: logger.error("%s", traceback.format_exc())

# Trace Suspension Utilities
# ------------------------------
@contextmanager
def suspend_var_traces(vars_):
    saved = []
    for v in vars_:
        info = v.trace_info()
        saved.append((v, info))
        for mode, cb in info:
            v.trace_remove(mode, cb)
    try: yield
    finally:
        for v, info in saved:
            for mode, cb in info:
                v.trace_add(mode, cb)

# GUI Helper Utilities
# ------------------------------
def center_window(win, parent):
    try:
        win.update_idletasks()
        px, py, pw, ph = parent.winfo_rootx(), parent.winfo_rooty(), parent.winfo_width(), parent.winfo_height()
        w, h = win.winfo_width(), win.winfo_height()
        x, y = px + (pw//2) - (w//2), py + (ph//2) - (h//2)
        win.geometry(f"+{x}+{y}")
    except Exception:
        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h = win.winfo_width(), win.winfo_height()
        x, y = (sw // 2) - (w // 2), (sh // 2) - (h // 2)
        win.geometry(f"+{x}+{y}")

def apply_modal_geometry(win, parent, key):
    geom = parent.settings.get('modal_geometry', {}).get(key)
    if geom: win.geometry(geom)
    else: center_window(win, parent)
    def on_close():
        parent.settings.setdefault('modal_geometry', {})[key] = win.geometry()
        parent.save_app_settings()
        win.destroy()
    win.protocol("WM_DELETE_WINDOW", on_close)
    win.resizable(True, True); win.focus_force()

def _show_dialog(parent, title, message, dialog_key, is_error=False):
    if not parent and is_error: root = tk.Tk(); root.withdraw()
    else: root = parent
    win = tk.Toplevel(); win.title(title)
    ttk.Label(win, text=message, justify=tk.CENTER).pack(padx=20, pady=20)
    ttk.Button(win, text="OK", command=win.destroy).pack(pady=5)
    if parent: apply_modal_geometry(win, parent, dialog_key)
    elif is_error: center_window(win, root)

def show_info_centered(parent, title, message): _show_dialog(parent, title, message, "InfoDialog")
def show_warning_centered(parent, title, message): _show_dialog(parent, title, message, "WarningDialog")
def show_error_centered(parent, title, message): _show_dialog(parent, title, message, "ErrorDialog", is_error=True)

def show_yesno_centered(parent, title, message):
    win = tk.Toplevel(); win.title(title)
    result = {"answer": False}
    ttk.Label(win, text=message).pack(padx=20, pady=20)
    def on_yes(): result["answer"] = True; win.destroy()
    btn_frame = ttk.Frame(win); btn_frame.pack(pady=5)
    ttk.Button(btn_frame, text="Yes", command=on_yes).pack(side=tk.LEFT, padx=10)
    ttk.Button(btn_frame, text="No", command=win.destroy).pack(side=tk.LEFT, padx=10)
    apply_modal_geometry(win, parent, "YesNoDialog")
    parent.wait_window(win)
    return result["answer"]

def show_yesnocancel_centered(parent, title, message, yes_text="Yes", no_text="No", cancel_text="Cancel"):
    win = tk.Toplevel(); win.title(title)
    result = {"answer": "cancel"}
    ttk.Label(win, text=message, justify=tk.CENTER).pack(padx=20, pady=20)
    def set_answer(ans): result["answer"] = ans; win.destroy()
    btn_frame = ttk.Frame(win); btn_frame.pack(pady=5)
    ttk.Button(btn_frame, text=yes_text, command=lambda: set_answer("yes")).pack(side=tk.LEFT, padx=10)
    ttk.Button(btn_frame, text=no_text, command=lambda: set_answer("no")).pack(side=tk.LEFT, padx=10)
    ttk.Button(btn_frame, text=cancel_text, command=win.destroy).pack(side=tk.LEFT, padx=10)
    win.protocol("WM_DELETE_WINDOW", win.destroy)
    apply_modal_geometry(win, parent, "YesNoCancelDialog")
    parent.wait_window(win)
    return result["answer"]

# Dialog: RenameTemplateDialog
# ------------------------------
class RenameTemplateDialog(tk.Toplevel):
    # Initialization
    # ------------------------------
    def __init__(self, parent, old_name):
        super().__init__(); self.parent = parent; self.title("Rename Template")
        self.new_name = None; self.old_name = old_name
        self.create_widgets()
        apply_modal_geometry(self, parent, "RenameTemplateDialog")
        self.wait_window()

    # Widget Creation
    # ------------------------------
    def create_widgets(self):
        frame = ttk.Frame(self); frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Enter new template name:").pack(anchor='w')
        self.entry_var = tk.StringVar(value=self.old_name)
        self.entry = ttk.Entry(frame, textvariable=self.entry_var); self.entry.pack(fill=tk.X, pady=5); self.entry.focus_set()
        btn_frame = ttk.Frame(frame); btn_frame.pack(anchor='e', pady=5)
        ttk.Button(btn_frame, text="OK", command=self.on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.on_cancel).pack(side=tk.LEFT)

    # Event Handlers
    # ------------------------------
    def on_ok(self): self.new_name = self.entry_var.get().strip(); self.destroy()
    def on_cancel(self): self.new_name = None; self.destroy()

# Dialog: SettingsDialog
# ------------------------------
class SettingsDialog(tk.Toplevel):
    # Initialization
    # ------------------------------
    def __init__(self, parent):
        super().__init__(); self.parent = parent; self.title("Settings")
        self.create_widgets()
        apply_modal_geometry(self, parent, "SettingsDialog")

    # Widget Creation
    # ------------------------------
    def create_widgets(self):
        proj_conf = self.parent.projects.get(self.parent.current_project, {})
        self.grid_rowconfigure(0, weight=1); self.grid_columnconfigure(0, weight=1)

        # ── canvas + scrollbar ────────────────────────────────────────────────
        self.canvas = tk.Canvas(self, borderwidth=0); self.canvas.grid(row=0, column=0, sticky='nsew')
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview); self.scrollbar.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.content_frame = ttk.Frame(self.canvas); self.content_frame.columnconfigure(0, weight=1)
        self._cwin_id = self.canvas.create_window((0, 0), window=self.content_frame, anchor='nw')

        # stretch the inner frame to dialog width on any resize
        def _stretch(event):
            self.canvas.itemconfig(self._cwin_id, width=event.width)
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.bind('<Configure>', _stretch, add='+')
        self.content_frame.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")), add='+')

        # enable mouse-wheel scrolling
        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind(ev, self.on_mousewheel, add='+')

        # ── project-specific section ──────────────────────────────────────────
        proj_frame = ttk.LabelFrame(self.content_frame, text="Project-Specific Settings")
        proj_frame.grid(row=0, column=0, padx=10, pady=10, sticky='ew')
        proj_frame.columnconfigure(0, weight=1)

        ttk.Label(proj_frame, text="Prefix:").pack(pady=(5,0), anchor='center', padx=10)
        self.prefix_entry = ttk.Entry(proj_frame, takefocus=True)
        self.prefix_entry.insert(0, proj_conf.get("prefix", ""))
        self.prefix_entry.pack(fill=tk.X, padx=10, pady=(0,10))

        ttk.Label(proj_frame, text="Project-specific .gitignore & Keep List:").pack(pady=(5,0), anchor='center', padx=10)
        self.extend_text = scrolledtext.ScrolledText(proj_frame, width=60, height=8, takefocus=True)
        self.extend_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0,10))
        self.extend_text.insert('1.0', "\n".join(proj_conf.get("blacklist", []) + [f"-{k}" for k in proj_conf.get("keep", [])]))

        ttk.Button(proj_frame, text="Open Project Logs Folder", command=self.open_project_logs, takefocus=True).pack(pady=5, padx=10)

        # ── global section ────────────────────────────────────────────────────
        glob_frame = ttk.LabelFrame(self.content_frame, text="Global Settings")
        glob_frame.grid(row=1, column=0, padx=10, pady=10, sticky='ew')
        glob_frame.columnconfigure(0, weight=1)

        self.respect_var = tk.BooleanVar(value=self.parent.settings.get('respect_gitignore', True))
        ttk.Checkbutton(glob_frame, text="Respect .gitignore", variable=self.respect_var, takefocus=True).pack(pady=5, anchor='center', padx=10)

        self.reset_scroll_var = tk.BooleanVar(value=self.parent.settings.get('reset_scroll_on_reset', True))
        ttk.Checkbutton(glob_frame, text="Reset project tree scroll on Reset", variable=self.reset_scroll_var, takefocus=True).pack(pady=5, anchor='center', padx=10)

        ttk.Label(glob_frame, text="Global .gitignore & Keep List:").pack(pady=(5,0), anchor='center', padx=10)
        self.global_extend_text = scrolledtext.ScrolledText(glob_frame, width=60, height=8, takefocus=True)
        self.global_extend_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0,10))
        self.global_extend_text.insert('1.0', "\n".join(
            self.parent.settings.get("global_blacklist", []) +
            [f"-{k}" for k in self.parent.settings.get("global_keep", [])]
        ))

        # ── save button row ───────────────────────────────────────────────────
        btn_container = ttk.Frame(self.content_frame)
        btn_container.grid(row=2, column=0, padx=10, pady=10, sticky='ew')
        btn_container.columnconfigure(0, weight=1)
        ttk.Button(btn_container, text="Save", command=self.save_settings, takefocus=True).pack()

    # Event Handlers & Public API
    # ------------------------------
    def on_mousewheel(self, event):
        if event.num == 4: self.canvas.yview_scroll(-1, "units")
        elif event.num == 5: self.canvas.yview_scroll(1, "units")
        else: self.canvas.yview_scroll(int(-1 * (event.delta / 120)) if platform.system() == 'Windows' else int(-1 * event.delta), "units")
        return "break"
        
    def open_project_logs(self):
        project_name = self.parent.current_project
        if not project_name: return show_warning_centered(self, "No Project", "No project is currently selected.")
        project_log_dir = os.path.join(self.parent.log_path, os.path.basename(project_name))
        os.makedirs(project_log_dir, exist_ok=True)
        open_in_editor(project_log_dir)

    def save_settings(self):
        proj_conf = self.parent.projects[self.parent.current_project]
        proj_conf["prefix"] = self.prefix_entry.get().strip()
        self.parent.settings['respect_gitignore'] = self.respect_var.get()
        self.parent.settings['reset_scroll_on_reset'] = self.reset_scroll_var.get()
        
        proj_lines = [l.strip() for l in self.extend_text.get('1.0', tk.END).split('\n') if l.strip()]
        proj_conf["blacklist"] = [l for l in proj_lines if not l.startswith('-')]
        proj_conf["keep"] = [l[1:].strip() for l in proj_lines if l.startswith('-')]

        glob_lines = [l.strip() for l in self.global_extend_text.get('1.0', tk.END).split('\n') if l.strip()]
        self.parent.settings["global_blacklist"] = [l for l in glob_lines if not l.startswith('-')]
        self.parent.settings["global_keep"] = [l[1:].strip() for l in glob_lines if l.startswith('-')]

        self.parent.save_app_projects(); self.parent.save_app_settings()
        self.destroy()
        self.parent.refresh_files(is_manual=True)

# Dialog: RawEditDialog
# ------------------------------
class RawEditDialog(tk.Toplevel):
    # Initialization
    # ------------------------------
    def __init__(self, parent):
        super().__init__(); self.parent = parent; self.title("Raw Edit Templates JSON")
        self.create_widgets()
        apply_modal_geometry(self, parent, "RawEditDialog")

    # Widget Creation
    # ------------------------------
    def create_widgets(self):
        self.text_area = scrolledtext.ScrolledText(self, width=80, height=20, wrap='none')
        self.text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.text_area.insert(tk.END, json.dumps(self.parent.settings.get("global_templates", {}), indent=4))
        btn_frame = ttk.Frame(self); btn_frame.pack(pady=5)
        ttk.Button(btn_frame, text="Save", command=self.save_json, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy, takefocus=True).pack(side=tk.LEFT, padx=5)

    # Public API
    # ------------------------------
    def save_json(self):
        try: new_data = json.loads(self.text_area.get('1.0', tk.END).strip())
        except json.JSONDecodeError as e: show_error_centered(self, "Invalid JSON", f"Please fix JSON format.\n{e}"); return
        self.parent.settings["global_templates"] = new_data
        self.parent.parent.save_app_settings()
        self.parent.parent.load_templates(force_refresh=True)
        self.parent.parent.quick_copy_var.set("")
        self.parent.destroy(); self.destroy()

# Dialog: TemplatesDialog
# ------------------------------
class TemplatesDialog(tk.Toplevel):
    # Initialization
    # ------------------------------
    def __init__(self, parent):
        super().__init__(); self.parent = parent; self.title("Manage Templates")
        self.settings = parent.settings
        self.templates = copy.deepcopy(self.settings.get("global_templates", {}))
        self.template_names = sorted(self.templates.keys())
        self.last_selected_index = None
        self.create_widgets()
        apply_modal_geometry(self, parent, "TemplatesDialog")
        self.select_current_template()

    # Widget Creation
    # ------------------------------
    def create_widgets(self):
        top_btn_frame = ttk.Frame(self); top_btn_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(top_btn_frame, text="Raw Edit All Templates", command=self.raw_edit_all_templates).pack(side=tk.RIGHT)
        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL); main_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        lf = ttk.Frame(main_pane); main_pane.add(lf, weight=1)
        self.template_listbox = tk.Listbox(lf, exportselection=False, takefocus=True); self.template_listbox.pack(fill=tk.BOTH, expand=True)
        for t in self.template_names: self.template_listbox.insert(tk.END, t)
        self.template_listbox.bind('<<ListboxSelect>>', self.on_template_select, add='+'); self.template_listbox.bind("<Double-Button-1>", self.on_name_dbl_click)
        self.adjust_listbox_width()

        cf = ttk.Frame(main_pane); main_pane.add(cf, weight=3)
        ttk.Label(cf, text="Template Content:").pack(anchor='w')
        self.template_text = scrolledtext.ScrolledText(cf, height=15, takefocus=True); self.template_text.pack(fill=tk.BOTH, expand=True, pady=(5,0))
        
        bf = ttk.Frame(self); bf.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(bf, text="Add New", command=self.add_template, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text="Delete", command=self.delete_template, takefocus=True).pack(side=tk.LEFT, padx=5)
        self.is_default_var = tk.BooleanVar()
        self.default_button = ttk.Checkbutton(bf, text="Set as Default", variable=self.is_default_var, command=self.toggle_default_template, state=tk.DISABLED)
        self.default_button.pack(side=tk.LEFT, padx=15)
        ttk.Button(bf, text="Save and Close", command=self.save_and_close, takefocus=True).pack(side=tk.RIGHT, padx=5)

    # Event Handlers & Public API
    # ------------------------------
    def on_template_select(self, _):
        self.save_current_template_content()
        s = self.template_listbox.curselection()
        if not s:
            if self.last_selected_index is not None and self.last_selected_index < self.template_listbox.size(): self.template_listbox.selection_set(self.last_selected_index)
            elif self.template_listbox.size() > 0: self.template_listbox.selection_set(0); self.on_template_select(None)
            else: self.default_button.config(state=tk.DISABLED)
            return
        i = s[0]; t_name = self.template_listbox.get(i)
        self.template_text.delete('1.0', tk.END); self.template_text.insert(tk.END, self.templates.get(t_name, ""))
        self.last_selected_index = i
        self.is_default_var.set(t_name == self.settings.get("default_template_name"))
        self.default_button.config(state=tk.NORMAL)

    def on_name_dbl_click(self, event):
        s = self.template_listbox.curselection()
        if not s: return
        old_name = self.template_listbox.get(s[0])
        new_name = RenameTemplateDialog(self.parent, old_name).new_name
        if new_name is None or new_name == old_name: return
        if not new_name: return show_warning_centered(self, "Warning", "Template name cannot be empty.")
        if new_name in self.templates: return show_error_centered(self, "Error", "Template name already exists.")
        self.templates[new_name] = self.templates.pop(old_name)
        if self.settings.get("default_template_name") == old_name: self.settings["default_template_name"] = new_name
        all_templates = self.templates.keys()
        self.template_names = sorted(all_templates)
        self.refresh_template_list(new_name)

    def add_template(self):
        name = simpledialog.askstring("Template Name", "Enter template name:")
        if name is None: return
        name = name.strip()
        if not name: return show_warning_centered(self, "Warning", "Template name cannot be empty.")
        if name in self.templates: return show_error_centered(self, "Error", "Template name already exists.")
        self.save_current_template_content()
        self.templates[name] = ""; self.template_names.append(name); self.template_names.sort()
        self.refresh_template_list(name)

    def delete_template(self):
        s = self.template_listbox.curselection()
        if not s: return
        t_name = self.template_listbox.get(s[0])
        if show_yesno_centered(self, "Delete Template", f"Are you sure you want to delete '{t_name}'?"):
            del self.templates[t_name]
            self.template_names.remove(t_name)
            if self.settings.get("default_template_name") == t_name: self.settings["default_template_name"] = None
            self.refresh_template_list()
            self.template_text.delete('1.0', tk.END)

    def save_and_close(self):
        self.save_current_template_content()
        self.parent.settings["global_templates"] = self.templates
        self.parent.save_app_settings()
        self.parent.load_templates(force_refresh=True)
        self.destroy()

    def raw_edit_all_templates(self): RawEditDialog(self)
    
    # Internal Helpers
    # ------------------------------
    def adjust_listbox_width(self):
        max_w = max((len(t) for t in self.template_names), default=20)
        self.template_listbox.config(width=min(max_w + 2, 50))

    def select_current_template(self):
        current_template = self.parent.template_var.get()
        if current_template in self.template_names: idx = self.template_names.index(current_template)
        elif self.template_listbox.size() > 0: idx = 0
        else: return
        self.template_listbox.selection_clear(0, tk.END); self.template_listbox.selection_set(idx)
        self.template_listbox.activate(idx); self.template_listbox.see(idx)
        self.on_template_select(None)
    
    def refresh_template_list(self, new_selection=None):
        cur_sel_name = new_selection or (self.template_listbox.get(self.template_listbox.curselection()[0]) if self.template_listbox.curselection() else None)
        self.template_listbox.delete(0, tk.END)
        for t in self.template_names: self.template_listbox.insert(tk.END, t)
        self.adjust_listbox_width()
        if cur_sel_name and cur_sel_name in self.template_names:
            idx = self.template_names.index(cur_sel_name)
            self.template_listbox.selection_set(idx); self.template_listbox.activate(idx)
        elif self.template_listbox.size() > 0: self.template_listbox.selection_set(0)
        self.on_template_select(None)

    def save_current_template_content(self):
        if self.last_selected_index is not None and self.last_selected_index < len(self.template_names):
            t_name = self.template_names[self.last_selected_index]
            content = self.template_text.get('1.0', tk.END).rstrip('\n')
            if self.templates.get(t_name) != content: self.templates[t_name] = content; return True
        return False
        
    def toggle_default_template(self):
        if not self.template_listbox.curselection(): return
        t_name = self.template_listbox.get(self.template_listbox.curselection()[0])
        if self.is_default_var.get(): self.settings["default_template_name"] = t_name
        elif self.settings.get("default_template_name") == t_name: self.settings["default_template_name"] = None

# Dialog: TextEditorDialog
# ------------------------------
class TextEditorDialog(tk.Toplevel):
    # Initialization
    # ------------------------------
    def __init__(self, parent, initial_text="", opened_file=None):
        super().__init__(); self.parent = parent; self.opened_file = opened_file; self.title("Text Editor")
        self.create_widgets()
        if initial_text: self.text_area.insert(tk.END, initial_text)
        apply_modal_geometry(self, parent, "TextEditorDialog")

    # Widget Creation
    # ------------------------------
    def create_widgets(self):
        bf = ttk.Frame(self); bf.pack(fill=tk.X, padx=5, pady=5)
        actions = {"Replace \"**\"": self.replace_stars, "Remove Duplicates": self.remove_duplicates, "Sort Alphabetically": self.sort_alphabetically, "Sort by Length": self.sort_by_length, "Unescape": self.unescape_text, "Escape": self.escape_text}
        for name, cmd in actions.items(): ttk.Button(bf, text=name, command=cmd, takefocus=True).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text='Copy & Close', command=self.copy_and_close, takefocus=True).pack(side=tk.RIGHT, padx=5)
        ttk.Button(bf, text='Open in Notepad++', command=self.open_in_notepad, takefocus=True).pack(side=tk.RIGHT, padx=5)
        self.text_area = scrolledtext.ScrolledText(self, width=80, height=25, wrap='none'); self.text_area.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    # Event Handlers & Public API
    # ------------------------------
    def copy_and_close(self): self.update_clipboard(); self.destroy()
    def open_in_notepad(self): self.parent.save_and_open_notepadpp(unify_line_endings(self.text_area.get('1.0', 'end-1c')).rstrip('\n')); self.destroy()
    def replace_stars(self): self.process_text(lambda t: t.replace("**", ""))
    def remove_duplicates(self): self.process_text(lambda t: '\n'.join(dict.fromkeys(t.rstrip('\n').split('\n'))))
    def sort_alphabetically(self): self.process_text(lambda t: '\n'.join(sorted(t.rstrip('\n').split('\n'))))
    def sort_by_length(self): self.process_text(lambda t: '\n'.join(sorted(t.rstrip('\n').split('\n'), key=len)))
    def escape_text(self): self.process_text(lambda t: t.rstrip('\n').encode('unicode_escape').decode('ascii', 'ignore'))
    def unescape_text(self):
        try: self.process_text(lambda t: codecs.decode(t.rstrip('\n'), 'unicode_escape'))
        except Exception as e: show_error_centered(self, "Unescape Error", f"Failed to unescape text: {e}")

    # Internal Helpers
    # ------------------------------
    def update_clipboard(self, msg="Copied to clipboard"):
        txt = self.text_area.get('1.0', tk.END).strip()
        self.clipboard_clear(); self.clipboard_append(txt)
        self.parent.set_status_temporary(msg)

    def process_text(self, func):
        new_text = func(self.text_area.get('1.0', tk.END))
        self.text_area.delete('1.0', tk.END); self.text_area.insert(tk.END, new_text)
        self.update_clipboard(); self.destroy()

# Dialog: HistorySelectionDialog
# ------------------------------
class HistorySelectionDialog(tk.Toplevel):
    # Initialization
    # ------------------------------
    def __init__(self, parent):
        super().__init__(); self.parent = parent; self.title("History Selection")
        apply_modal_geometry(self, parent, "HistorySelectionDialog")
        self.create_widgets()

    # Widget Creation
    # ------------------------------
    def create_widgets(self):
        pad_frame = ttk.Frame(self); pad_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.canvas = tk.Canvas(pad_frame, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(pad_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set); self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.content_frame = ttk.Frame(self.canvas)
        canvas_window_id = self.canvas.create_window((0, 0), window=self.content_frame, anchor='nw')
        self.content_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"), width=self.canvas.winfo_width()))
        self.bind("<MouseWheel>", self.on_mousewheel, add='+'); self.bind("<Button-4>", self.on_mousewheel, add='+'); self.bind("<Button-5>", self.on_mousewheel, add='+')
        self.load_history()

    # Event Handlers & Public API
    # ------------------------------
    def on_mousewheel(self, event):
        if event.num == 4: self.canvas.yview_scroll(-1, "units")
        elif event.num == 5: self.canvas.yview_scroll(1, "units")
        else: self.canvas.yview_scroll(int(-1 * (event.delta / 120)) if platform.system() == 'Windows' else int(-1 * event.delta), "units")
        return "break"

    def load_history(self):
        hs = sorted(self.parent.settings.get(HISTORY_SELECTION_KEY, []), key=lambda x: x.get("timestamp", 0), reverse=True)[:20]
        for s_obj in hs:
            fr = ttk.Frame(self.content_frame); fr.pack(fill=tk.X, expand=True, pady=5)
            proj = s_obj.get("saved_project_name") or s_obj.get("project_name") or s_obj.get("project", "(Unknown)")
            lbl_txt = f"{proj} | {datetime.fromtimestamp(s_obj['timestamp']).strftime('%d.%m.%Y %H:%M:%S')} ({get_relative_time_str(s_obj['timestamp'])})"
            ttk.Label(fr, text=lbl_txt, style='Info.TLabel').pack(anchor='w')
            lines = s_obj["files"]
            txt = tk.Text(fr, wrap='none', height=len(lines) if lines else 1); txt.pack(fill=tk.X, expand=True, pady=2)
            txt.insert(tk.END, "".join(f"{f}\n" for f in lines)); txt.config(state='disabled')
            txt.bind("<MouseWheel>", lambda e: self.on_mousewheel(e), add='+'); txt.bind("<Key>", lambda e: "break")
            r_btn = ttk.Button(fr, text="Re-select", command=lambda data=s_obj: self.reselect_set(data)); r_btn.pack(fill=tk.X, pady=(1, 0))
            if any(f not in self.parent.file_vars for f in lines): r_btn.config(state=tk.DISABLED)
    
    def reselect_set(self, s_obj): self.parent.start_bulk_update_and_reselect(s_obj["files"]); self.destroy()

# Dialog: OutputFilesDialog
# ------------------------------
class OutputFilesDialog(tk.Toplevel):
    # Initialization
    # ------------------------------
    def __init__(self, parent):
        super().__init__(); self.parent = parent; self.title("View Outputs"); self.files_list = []
        self.active_loading_filepath = None
        self.create_widgets()
        apply_modal_geometry(self, parent, "OutputFilesDialog")
        self.load_files()

    # Widget Creation
    # ------------------------------
    def create_widgets(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL); pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        left_frame = ttk.Frame(pane); pane.add(left_frame, weight=3)
        cols = ("name", "time", "chars"); self.tree = ttk.Treeview(left_frame, columns=cols, show='headings', selectmode='browse')
        for col, text, width in [("name", "File Name", 250), ("time", "Generated", 120), ("chars", "Chars", 80)]:
            self.tree.heading(col, text=text); self.tree.column(col, width=width, stretch=(col == "name"), anchor='e' if col == "chars" else 'w')
        ysb = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.tree.yview); xsb = ttk.Scrollbar(left_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set); self.tree.grid(row=0, column=0, sticky='nsew')
        ysb.grid(row=0, column=1, sticky='ns'); xsb.grid(row=1, column=0, sticky='ew')
        left_frame.grid_rowconfigure(0, weight=1); left_frame.grid_columnconfigure(0, weight=1)
        right_frame = ttk.Frame(pane); pane.add(right_frame, weight=5)
        editor_buttons_frame = ttk.Frame(right_frame); editor_buttons_frame.pack(fill=tk.X, pady=(0, 5))
        self.save_button = ttk.Button(editor_buttons_frame, text='Save', command=self.save_current_file, state=tk.DISABLED); self.save_button.pack(side=tk.LEFT)
        ttk.Button(editor_buttons_frame, text='Copy', command=self.copy_text_to_clipboard).pack(side=tk.LEFT, padx=5)
        ttk.Button(editor_buttons_frame, text='Open in Notepad++', command=self.open_in_notepad).pack(side=tk.RIGHT, padx=5)
        self.editor_text = scrolledtext.ScrolledText(right_frame, wrap=tk.NONE, state='disabled', width=80, height=25); self.editor_text.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_file_select)

    # Event Handlers & Public API
    # ------------------------------
    def load_files(self):
        for i in self.tree.get_children(): self.tree.delete(i)
        if not os.path.isdir(OUTPUT_DIR): return
        files_with_meta = []
        for f in os.listdir(OUTPUT_DIR):
            fp = os.path.join(OUTPUT_DIR, f)
            if os.path.isfile(fp):
                try:
                    with open(fp, 'r', encoding='utf-8', errors='replace') as cf: cc=len(cf.read())
                    files_with_meta.append((f, os.path.getmtime(fp), cc, fp))
                except (OSError,UnicodeDecodeError): continue
        files_with_meta.sort(key=lambda x: x[1], reverse=True)
        self.files_list = [item[3] for item in files_with_meta]
        for f, mtime, char_count, _ in files_with_meta: self.tree.insert("", tk.END, values=(f, get_relative_time_str(mtime), format_german_thousand_sep(char_count)))
        if self.files_list: self.tree.selection_set(self.tree.get_children()[0])

    def on_file_select(self, event):
        if not self.tree.selection(): return
        idx = self.tree.index(self.tree.selection()[0])
        if idx >= len(self.files_list): return
        self.active_loading_filepath = self.files_list[idx]
        self.editor_text.config(state='normal'); self.editor_text.delete('1.0', tk.END)
        self.editor_text.insert('1.0', f"--- Loading {os.path.basename(self.active_loading_filepath)} ---"); self.editor_text.config(state='disabled')
        self.save_button.config(state=tk.DISABLED)
        threading.Thread(target=self._load_content_worker, args=(self.active_loading_filepath,), daemon=True).start()

    def save_current_file(self):
        if not self.active_loading_filepath: return show_warning_centered(self, "Warning", "No file selected.")
        self.save_button.config(state=tk.DISABLED)
        threading.Thread(target=self._save_file_worker, args=(self.active_loading_filepath, self.editor_text.get('1.0', tk.END)), daemon=True).start()
        self.destroy()

    def copy_text_to_clipboard(self):
        txt = self.editor_text.get('1.0', tk.END).strip()
        self.clipboard_clear(); self.clipboard_append(txt)
        self.parent.set_status_temporary("Copied to clipboard"); self.destroy()

    def open_in_notepad(self): self.parent.save_and_open_notepadpp(unify_line_endings(self.editor_text.get('1.0', 'end-1c')).rstrip('\n')); self.destroy()

    # Internal Workers
    # ------------------------------
    def _load_content_worker(self, filepath):
        try: content = safe_read_file(filepath)
        except Exception as e: content = f"Error reading file:\n\n{e}"
        if self.winfo_exists(): self.after(0, self._update_editor_content, content, filepath)

    def _update_editor_content(self, content, filepath):
        if self.winfo_exists() and self.active_loading_filepath == filepath:
            try:
                self.editor_text.config(state='normal'); self.editor_text.delete('1.0', tk.END)
                self.editor_text.insert('1.0', content); self.save_button.config(state=tk.NORMAL)
                self.title(f"View Outputs - [{os.path.basename(filepath)}]")
            except tk.TclError: pass

    def _save_file_worker(self, filepath, content):
        try:
            with open(filepath, 'w', encoding='utf-8', newline='\n') as f: f.write(content)
            self.parent.queue.put(('set_status_temporary', (f"Saved {os.path.basename(filepath)}", 2000)))
        except Exception as e:
            logger.error("Error saving output file %s: %s\n%s", filepath, e, traceback.format_exc())
            self.parent.queue.put(('show_error', ("Save Error", f"Could not save file:\n{e}")))

# Main Application
# ------------------------------
class CodePromptGeneratorApp(tk.Tk):
    # Initialization & State
    # ------------------------------
    def __init__(self):
        super().__init__()
        self.title(f"Code Prompt Generator - PID: {os.getpid()}")
        self.queue = queue.Queue()
        self.projects = load_projects(self.queue)
        self.settings = load_settings(self.queue)
        self.log_path = log_path
        if self.projects is None or self.settings is None:
            show_error_centered(None, "Fatal Error", "Could not load data files due to a file lock. Please close other instances.")
            sys.exit(1)
        self.initialize_styles()
        self.initialize_state()
        self.create_layout()
        self.after(50, self.process_queue)
        lp = self.settings.get('last_selected_project')
        if lp and lp in self.projects: self.project_var.set(lp); self.load_project(lp)
        else: self._set_project_file_handler(None) # Initialize logging to general
        self.restore_window_geometry()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.watch_file_changes()
        self.start_precompute_worker()

    # ------------------------------
    # Logging: keep one console handler, swap per-project file handler only
    # ------------------------------
    def _set_project_file_handler(self, project_name: str):
        root = logging.getLogger()
        # remove any previous DailyFileHandler to prevent duplicate logging
        for h in list(root.handlers):
            if isinstance(h, DailyFileHandler):
                root.removeHandler(h)
                try: h.close()
                except Exception: pass
        
        safe_project_name = "".join(c for c in project_name if c.isalnum() or c in (' ', '_', '-')).rstrip() if project_name else "general"
        log_dir = os.path.join(self.log_path, safe_project_name)
        os.makedirs(log_dir, exist_ok=True)
        
        fh = DailyFileHandler(log_dir=log_dir, log_prefix="app", encoding="utf-8", delay=True)
        fh.setLevel(logging.INFO)
        fh.addFilter(HierarchyFilter())
        fh.setFormatter(HierarchicalFormatter("%(asctime)s - %(func_hierarchy)s - %(levelname)s - %(message)s"))
        root.addHandler(fh)
        # guarantee console handler is still attached exactly once
        for ch in _console_handlers:
            if ch not in root.handlers: root.addHandler(ch)
        self._proj_file_handler = fh
        logger.info("Switched file logging to %s", project_name or "general")

    def initialize_styles(self):
        self.style = ttk.Style(self)
        try: self.style.theme_use('vista')
        except tk.TclError:
            try: self.style.theme_use(self.style.theme_names()[0])
            except Exception as e: logger.warning("Failed to set a theme: %s", e)
        self.style.configure('.', font=('Segoe UI', 10), background='#F3F3F3')
        for s in ['TFrame', 'TLabel', 'TCheckbutton', 'Modern.TCheckbutton']: self.style.configure(s, background='#F3F3F3')
        for s in ['ProjectOps.TLabelframe', 'TemplateOps.TLabelframe', 'FilesFrame.TLabelframe']: self.style.configure(s, background='#F3F3F3', padding=10, foreground='#444444')
        self.style.configure('TButton', foreground='black', background='#F0F0F0', padding=6, font=('Segoe UI',10,'normal'))
        self.style.map('TButton', foreground=[('disabled','#7A7A7A'),('active','black')], background=[('active','#E0E0E0'),('disabled','#F0F0F0')])
        self.style.configure('RemoveFile.TButton', anchor='center', padding=(2,1))
        self.icon_path = resource_path('app_icon.ico')
        if os.path.exists(self.icon_path):
            try: self.iconbitmap(self.icon_path)
            except tk.TclError: logger.warning("Could not set .ico file.")

    def initialize_state(self):
        self.settings.setdefault('respect_gitignore', True)
        self.settings.setdefault("global_templates", {"Default": "Your task is to\n\n{{dirs}}{{files_provided}}{{file_contents}}"})
        self.settings.setdefault('reset_scroll_on_reset', True)
        self.settings.setdefault("global_blacklist", [])
        self.settings.setdefault("global_keep", [])
        self.settings.setdefault("default_template_name", None)
        self.baseline_projects, self.baseline_settings = copy.deepcopy(self.projects), copy.deepcopy(self.settings)
        self.last_projects_mtime = os.path.getmtime(PROJECTS_FILE) if os.path.exists(PROJECTS_FILE) else 0
        self.last_settings_mtime = os.path.getmtime(SETTINGS_FILE) if os.path.exists(SETTINGS_FILE) else 0
        self.current_project = None
        self.templates, self.file_vars, self.file_hashes, self.file_mtimes, self.file_contents = {}, {}, {}, {}, {}
        self.file_char_counts, self.file_labels, self.row_frames = {}, {}, {}
        self.all_items, self.filtered_items = [], []
        self.click_counts, self.previous_check_states = {}, {}
        self.all_files_count, self.project_tree_scroll_pos = 0, 0.0
        self.data_lock, self.precompute_lock = threading.Lock(), threading.Lock()
        self.precompute_request = threading.Event()
        self.precomputed_prompt_cache = {}
        self.bulk_update_active, self.reset_button_clicked, self.is_silent_refresh = False, False, False
        self.settings_dialog, self.templates_dialog = None, None
        self.search_debounce_timer, self.scroll_restore_job, self.checkbox_toggle_timer = None, None, None
        self.loading_thread, self.autoblacklist_thread, self.precompute_thread = None, None, None
        self.skip_search_scroll = False
        self.project_search_buffer = ""
        self.project_search_last_key_time = 0
        self.bulk_chunk = 100
        self._char_count_token = 0
        self._project_listbox = None

    # Application Lifecycle & Context
    # ------------------------------
    def on_closing(self):
        projects_changed = self.projects != self.baseline_projects
        settings_for_comparison = copy.deepcopy(self.settings)
        baseline_for_comparison = copy.deepcopy(self.baseline_settings)
        settings_for_comparison.pop('window_geometry', None)
        baseline_for_comparison.pop('window_geometry', None)
        settings_changed = settings_for_comparison != baseline_for_comparison
        change_descs = []
        if projects_changed: change_descs.append("Project data (e.g., last file selections, usage stats)")
        if settings_changed: change_descs.append("Application settings (e.g., templates, last project)")
        if change_descs:
            message = "There are unsaved changes:\n\n- " + "\n- ".join(change_descs) + "\n\nSave changes before closing?"
            res = show_yesnocancel_centered(self, "Unsaved Changes", message, yes_text="Save", no_text="Don't Save")
            if res == "cancel": return
            if res == "yes":
                self.settings['window_geometry'] = self.geometry()
                self.save_app_settings()
                self.save_app_projects()
        else:
            if self.settings.get('window_geometry') != self.geometry():
                self.settings['window_geometry'] = self.geometry()
                self.save_app_settings()
        self.destroy()

    def restore_window_geometry(self):
        geom = self.settings.get('window_geometry'); self.geometry(geom if geom else "1000x700")

    def watch_file_changes(self):
        changed_projects = os.path.exists(PROJECTS_FILE) and os.path.getmtime(PROJECTS_FILE) > self.last_projects_mtime and abs(os.path.getmtime(PROJECTS_FILE) - LAST_OWN_WRITE_TIMES["projects"]) > 1.0
        changed_settings = os.path.exists(SETTINGS_FILE) and os.path.getmtime(SETTINGS_FILE) > self.last_settings_mtime and abs(os.path.getmtime(SETTINGS_FILE) - LAST_OWN_WRITE_TIMES["settings"]) > 1.0
        if changed_projects:
            logger.info("External change in projects.json, reloading.")
            self.projects = load_projects(self.queue); self.baseline_projects = copy.deepcopy(self.projects)
            self.sort_and_set_projects(self.project_dropdown)
            if self.current_project and self.current_project not in self.projects: self.current_project = None; self.clear_project_view()
            elif self.current_project: self.refresh_files()
        if changed_settings:
            logger.info("External change in settings.json, reloading.")
            self.settings = load_settings(self.queue); self.baseline_settings = copy.deepcopy(self.settings)
            self.load_templates(force_refresh=True)
            if getattr(self, 'templates_dialog', None) and self.templates_dialog.winfo_exists():
                self.templates_dialog.settings = self.settings; self.templates_dialog.templates = copy.deepcopy(self.settings.get("global_templates", {}))
                self.templates_dialog.template_names = sorted(self.templates_dialog.templates.keys()); self.templates_dialog.refresh_template_list()
        if os.path.exists(PROJECTS_FILE): self.last_projects_mtime = os.path.getmtime(PROJECTS_FILE)
        if os.path.exists(SETTINGS_FILE): self.last_settings_mtime = os.path.getmtime(SETTINGS_FILE)
        self.after(2000, self.watch_file_changes)
    
    @contextmanager
    def bulk_update_mode(self):
        self.bulk_update_active = True
        try: yield
        finally: self.bulk_update_active = False; self.on_file_selection_changed()

    # GUI Layout Creation
    # ------------------------------
    def create_layout(self):
        self.top_frame = ttk.Frame(self); self.top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)
        self.create_top_widgets(self.top_frame)
        self.file_frame = ttk.LabelFrame(self, text="Project Files", style='FilesFrame.TLabelframe')
        self.file_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(5,0))
        self.create_file_widgets(self.file_frame)
        self.control_frame = ttk.Frame(self); self.control_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=5)
        self.create_bottom_widgets(self.control_frame)

    def create_top_widgets(self, container):
        pa = ttk.LabelFrame(container, text="Project Operations", style='ProjectOps.TLabelframe')
        pa.pack(side=tk.LEFT, fill=tk.Y, padx=(0,5))

        ttk.Label(pa, text="Select Project:").pack(anchor='w', pady=(0,2))

        self.project_var = tk.StringVar()
        self.project_dropdown = ttk.Combobox(
            pa, textvariable=self.project_var, state='readonly',
            width=20, takefocus=True
        )
        self.project_dropdown.pack(anchor='w', pady=(0,5))

        # incremental search – works when list is closed …
        self.project_dropdown.bind("<KeyPress>", self.on_project_dropdown_search)

        # … and now also when the drop-down list is OPEN
        self.project_dropdown.configure(postcommand=self.bind_project_listbox)

        self.project_dropdown.bind("<<ComboboxSelected>>", self.on_project_selected)
        self.sort_and_set_projects(self.project_dropdown)

        of = ttk.Frame(pa); of.pack(anchor='w', pady=(5,0))
        ttk.Button(of, text="Add Project", command=self.add_project, takefocus=True).pack(side=tk.LEFT)
        ttk.Button(of, text="Open Folder", command=self.open_project_folder, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(of, text="Remove Project", command=self.remove_project, takefocus=True).pack(side=tk.LEFT, padx=5)

        tf = ttk.LabelFrame(container, text="Template", style='TemplateOps.TLabelframe'); tf.pack(side=tk.RIGHT, fill=tk.Y, padx=(5,0))
        template_frame_inner = ttk.Frame(tf); template_frame_inner.pack(anchor='w')
        ttk.Label(template_frame_inner, text="Select Template:").pack(anchor='w', pady=(0,2))
        self.template_var = tk.StringVar(); self.template_var.trace_add('write', lambda *a: self.request_precomputation())
        self.template_dropdown = ttk.Combobox(template_frame_inner, textvariable=self.template_var, state='readonly', width=20, takefocus=True); self.template_dropdown.pack(anchor='w', pady=(0,5)); self.template_dropdown.bind("<<ComboboxSelected>>", self.on_template_selected)
        template_buttons_frame = ttk.Frame(tf); template_buttons_frame.pack(anchor='w', pady=5)
        self.manage_templates_btn = ttk.Button(template_buttons_frame, text="Manage Templates", command=self.manage_templates, takefocus=True); self.manage_templates_btn.pack(side=tk.LEFT)
        self.reset_template_btn = ttk.Button(template_buttons_frame, text="Reset to Default", command=self.reset_template_to_default, takefocus=True, state=tk.DISABLED); self.reset_template_btn.pack(side=tk.LEFT, padx=5)

        qf = ttk.LabelFrame(container, text="Quick Copy w/Clipboard", style='TemplateOps.TLabelframe'); qf.pack(side=tk.RIGHT, fill=tk.Y, padx=5)
        self.quick_copy_var = tk.StringVar()
        self.quick_copy_dropdown = ttk.Combobox(qf, textvariable=self.quick_copy_var, state='readonly', width=20, takefocus=True); self.quick_copy_dropdown.pack(anchor='w', pady=(0,5)); self.quick_copy_dropdown.bind("<<ComboboxSelected>>", self.on_quick_copy_selected)

    def create_file_widgets(self, container):
        sf = ttk.Frame(container); sf.pack(anchor='w', padx=5, pady=(5,2))
        ttk.Label(sf, text="Search:").pack(side=tk.LEFT, padx=(0,5))
        self.file_search_var = tk.StringVar(); self.file_search_var.trace_add("write", self.on_search_changed)
        ttk.Entry(sf, textvariable=self.file_search_var, width=25, takefocus=True).pack(side=tk.LEFT)
        ttk.Button(sf, text="✕", command=lambda: self.file_search_var.set(""), style='Toolbutton').pack(side=tk.LEFT, padx=(5,0))

        tf = ttk.Frame(container); tf.pack(fill=tk.X, padx=5, pady=(5,2))
        self.select_all_button = ttk.Button(tf, text="Select All", command=self.toggle_select_all, takefocus=True); self.select_all_button.pack(side=tk.LEFT)
        self.reset_button = ttk.Button(tf, text="Reset", command=self.reset_selection, takefocus=True); self.reset_button.pack(side=tk.LEFT, padx=5)
        self.file_selected_label = ttk.Label(tf, text="Files selected: 0 / 0 (Chars: 0)", width=45); self.file_selected_label.pack(side=tk.LEFT, padx=10)
        self.view_outputs_button = ttk.Button(tf, text="View Outputs", command=self.open_output_files, takefocus=True); self.view_outputs_button.pack(side=tk.RIGHT)
        self.history_button = ttk.Button(tf, text="History Selection", command=self.open_history_selection, takefocus=True); self.history_button.pack(side=tk.RIGHT, padx=5)

        mf = ttk.Frame(container); mf.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.files_canvas, self.inner_frame = self.create_scrolled_frame(mf, side=tk.LEFT)
        self.selected_files_canvas, self.selected_files_inner = self.create_scrolled_frame(mf, side=tk.RIGHT, width=300)

    def create_bottom_widgets(self, container):
        gen_frame = ttk.Frame(container); gen_frame.pack(side=tk.LEFT, padx=5)
        self.generate_button = ttk.Button(gen_frame, text="Generate", width=12, command=self.generate_output, takefocus=True); self.generate_button.pack(side=tk.LEFT)
        ttk.Label(gen_frame, text="MD:").pack(side=tk.LEFT, padx=(10, 0)); self.generate_menu_button_md = ttk.Button(gen_frame, text="▼", width=2, command=self.show_quick_generate_menu); self.generate_menu_button_md.pack(side=tk.LEFT)
        ttk.Label(gen_frame, text="CB:").pack(side=tk.LEFT, padx=(10, 0)); self.generate_menu_button_cb = ttk.Button(gen_frame, text="▼", width=2, command=self.show_quick_generate_menu_cb); self.generate_menu_button_cb.pack(side=tk.LEFT)
        self.refresh_button = ttk.Button(container, text="Refresh Files", width=12, command=lambda: self.refresh_files(is_manual=True), takefocus=True); self.refresh_button.pack(side=tk.LEFT, padx=5)
        self.status_label = ttk.Label(container, text="Ready"); self.status_label.pack(side=tk.RIGHT, padx=10)
        self.text_editor_button = ttk.Button(container, text="Open Text Editor", command=self.open_text_editor, takefocus=True); self.text_editor_button.pack(side=tk.RIGHT)
        self.settings_button = ttk.Button(container, text="Settings", command=self.open_settings, takefocus=True); self.settings_button.pack(side=tk.RIGHT, padx=5)
        
    # GUI Helpers
    # ------------------------------
    def create_scrolled_frame(self, parent, side, width=None):
        container = ttk.Frame(parent); container.pack(side=side, fill=tk.BOTH if side==tk.LEFT else tk.Y, expand=(side==tk.LEFT), padx=(0,5) if side==tk.LEFT else (5,0))
        if width: container.config(width=width); container.pack_propagate(False)
        canvas = tk.Canvas(container, highlightthickness=0, background='#F3F3F3')
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set); canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); scrollbar.pack(side=tk.LEFT, fill=tk.Y)
        inner_frame = ttk.Frame(canvas)
        inner_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner_frame, anchor='nw')
        self.bind_mousewheel_events(canvas)
        return canvas, inner_frame
        
    def set_status_temporary(self, msg, duration=2000):
        self.status_label.config(text=msg); self.after(duration, lambda: self.status_label.config(text="Ready"))

    def schedule_scroll_restore(self, pos):
        if self.scroll_restore_job: self.after_cancel(self.scroll_restore_job)
        self.scroll_restore_job = self.after(50, lambda p=pos: (self.files_canvas.yview_moveto(p), setattr(self, "scroll_restore_job", None)))

    # Project & Template Management
    # ------------------------------
    def save_app_settings(self): save_settings(self.settings, self.queue)
    def save_app_projects(self): save_projects(self.projects, self.queue)

    def add_project(self):
        dp = filedialog.askdirectory(title="Select Project Directory")
        if not dp: return
        name = os.path.basename(dp)
        if not name.strip(): return show_warning_centered(self, "Invalid Name", "Project name cannot be empty.")
        if name in self.projects: return show_error_centered(self, "Error", f"Project '{name}' already exists.")
        self.projects[name] = {"path": dp, "last_files": [], "blacklist": [], "keep": [], "prefix": "", "click_counts": {}, "last_usage": time.time(), "usage_count": 1}
        self.save_app_projects(); self.sort_and_set_projects(self.project_dropdown); self.project_var.set(name)
        self.load_project(name, is_new_project=True)

    def remove_project(self):
        disp = self.project_var.get(); name = disp.split(' (')[0] if ' (' in disp else disp
        if not name: return show_warning_centered(self, "No Project Selected", "Please select a project to remove.")
        if name not in self.projects: return show_warning_centered(self, "Invalid Selection", "Project not found.")
        if show_yesno_centered(self, "Remove Project", f"Are you sure you want to remove '{name}'?"):
            del self.projects[name]; self.save_app_projects()
            if self.settings.get('last_selected_project') == name: del self.settings['last_selected_project']; self.save_app_settings()
            if self.current_project == name: self.current_project = None
            self.sort_and_set_projects(self.project_dropdown)
            all_projs = self.project_dropdown['values']
            if all_projs: self.project_var.set(all_projs[0]); self.load_project(all_projs[0].split(' (')[0])
            else: self.project_var.set(""); self.clear_project_view()

    def open_project_folder(self):
        if not self.current_project: return show_warning_centered(self, "No Project Selected", "Please select a project first.")
        proj_path = self.projects[self.current_project].get("path")
        if proj_path and os.path.isdir(proj_path): open_in_editor(proj_path)
        else: show_error_centered(self, "Error", "Project path is invalid or does not exist.")

    def load_project(self, name, is_new_project=False):
        if self.current_project and self.current_project in self.projects:
            try:
                if self.files_canvas.winfo_height() > 1: self.projects[self.current_project]['scroll_pos'] = self.files_canvas.yview()[0]
            except (AttributeError, tk.TclError): pass
        self.current_project = name
        self.settings['last_selected_project'] = name
        self._set_project_file_handler(name)
        proj = self.projects[name]
        self.project_tree_scroll_pos = proj.get("scroll_pos", 0.0)
        self.click_counts = proj.get("click_counts", {})
        self.run_autoblacklist_in_background(name)
        self.load_templates(force_refresh=True)
        self.load_items_in_background(is_new_project=is_new_project)

    def load_templates(self, *, force_refresh=False):
        self.templates = self.settings.get("global_templates", {})
        if self.settings.get("default_template_name") not in self.templates:
            self.settings["default_template_name"] = None
        
        display_templates = sorted([n for n, c in self.templates.items() if not ("{{CLIPBOARD}}" in c and "{{file_contents}}" not in c)])
        if not force_refresh and list(self.template_dropdown['values']) == display_templates: return
        self.template_dropdown['values'] = display_templates
        if display_templates: self.template_dropdown.config(height=min(len(display_templates), 15), width=max(max((len(x) for x in display_templates), default=0)+2, 20))
        
        quick_copy_templates = [n for n in sorted(self.templates.keys()) if "{{CLIPBOARD}}" in self.templates.get(n, "") and "{{file_contents}}" not in self.templates.get(n, "")]
        editor_tools = ["Replace \"**\"", "Remove Duplicates", "Sort Alphabetically", "Sort by Length", "Escape Text", "Unescape Text"]
        qc_menu = []
        if quick_copy_templates: qc_menu.extend(["-- Template Content --"] + quick_copy_templates)
        all_tools = ["Truncate Between '---'"] + editor_tools
        try:
            replace_idx = editor_tools.index("Replace \"**\"")
            all_tools = editor_tools[:replace_idx+1] + ["Truncate Between '---'"] + editor_tools[replace_idx+1:]
        except ValueError: all_tools = ["Truncate Between '---'"] + editor_tools
        qc_menu.extend(["-- Text Editor Tools --"] + all_tools)
        self.quick_copy_dropdown.config(values=qc_menu, height=min(len(qc_menu), 15))
        if qc_menu: self.quick_copy_dropdown.config(width=max(max((len(x) for x in qc_menu), default=0)+2, 20))
        self.quick_copy_var.set("")

        default_to_set = self.settings.get("default_template_name")
        if default_to_set and default_to_set in display_templates:
            self.template_var.set(default_to_set)
        elif display_templates:
            self.template_var.set(display_templates[0])
        else:
            self.template_var.set("")
        self.update_default_template_button(); self.on_template_selected(None)

    # File & Item Management
    # ------------------------------
    def refresh_files(self, is_manual=False):
        if not self.current_project: return
        self.project_tree_scroll_pos = self.files_canvas.yview()[0] if self.files_canvas.winfo_height() > 1 else 0.0
        selection = [p for p, v in self.file_vars.items() if v.get()]
        self.load_items_in_background(is_silent=not is_manual)
        self.after(200, lambda: self.restore_selection_after_refresh(selection))
        
    def restore_selection_after_refresh(self, selection_to_restore): self.start_bulk_update_and_reselect(selection_to_restore)

    def filter_and_display_items(self, scroll_to_top=False):
        if self.reset_button_clicked and not self.settings.get('reset_scroll_on_reset', True): scroll_to_top = False
        for w in self.inner_frame.winfo_children(): w.destroy()
        query = self.file_search_var.get().strip().lower()
        self.filtered_items = [it for it in self.all_items if query in it["path"].lower()] if query else self.all_items
        with self.data_lock:
            for item in self.filtered_items:
                rf = tk.Frame(self.inner_frame); rf.pack(fill=tk.X, anchor='w'); self.bind_mousewheel_events(rf)
                indent = (4 + item["level"] * 10, 2)
                if item["type"] == "dir":
                    rf.config(bg='#F3F3F3'); lbl = tk.Label(rf, text=f"{os.path.basename(item['path'].rstrip('/'))}/", bg='#F3F3F3', fg='#0066AA')
                    lbl.pack(side=tk.LEFT, padx=indent); self.bind_mousewheel_events(lbl)
                else:
                    path = item["path"]; self.row_frames[path] = rf; self.update_row_color(path)
                    chk = ttk.Checkbutton(rf, variable=self.file_vars.get(path), style='Modern.TCheckbutton'); chk.pack(side=tk.LEFT, padx=indent); self.bind_mousewheel_events(chk)
                    char_count = format_german_thousand_sep(self.file_char_counts.get(path, 0))
                    lbl = tk.Label(rf, text=f"{os.path.basename(path)} [{char_count}]", bg=rf["bg"]); lbl.pack(side=tk.LEFT, padx=2)
                    lbl.bind("<Button-1>", lambda e, p=path: self.file_vars[p].set(not self.file_vars[p].get()))
                    self.bind_mousewheel_events(lbl); self.file_labels[path] = lbl
        self.on_file_selection_changed()
        if scroll_to_top or (self.reset_button_clicked and self.settings.get('reset_scroll_on_reset', True)): self.schedule_scroll_restore(0.0)
        else: self.schedule_scroll_restore(self.project_tree_scroll_pos)
        self.reset_button_clicked = False; self.is_silent_refresh = False

    def clear_project_view(self):
        self.all_items.clear(); self.filtered_items.clear()
        with self.data_lock:
            for d in [self.file_vars, self.file_hashes, self.file_mtimes, self.file_contents, self.file_char_counts]: d.clear()
        for w in self.inner_frame.winfo_children(): w.destroy()
        self.on_file_selection_changed()

    def update_file_contents(self, selected_files):
        proj_path = self.projects[self.current_project]["path"]
        with self.data_lock:
            for rp in selected_files:
                ap = os.path.join(proj_path, rp)
                if not os.path.isfile(ap): continue
                try:
                    st = os.stat(ap)
                    current_mtime = st.st_mtime_ns
                    if self.file_mtimes.get(rp) != current_mtime:
                        fsz = st.st_size
                        content = safe_read_file(ap) if fsz <= MAX_FILE_SIZE else None
                        if content is not None: content = unify_line_endings(content)
                        self.file_contents[rp] = content
                        self.file_char_counts[rp] = len(content) if content is not None else fsz
                        self.file_mtimes[rp] = current_mtime
                except OSError:
                    logger.warning("Could not access %s", rp)
                    self.file_contents[rp] = None
                    self.file_char_counts[rp] = 0
                    self.file_mtimes.pop(rp, None)

    # Selection & State Tracking
    # ------------------------------
    def toggle_select_all(self):
        filtered_files = [i for i in self.filtered_items if i["type"] == "file"]
        if not filtered_files: return
        new_state = not all(self.file_vars[i["path"]].get() for i in filtered_files)
        files_to_change = [item["path"] for item in filtered_files]
        self.start_bulk_update_and_reselect(files_to_change if new_state else [])

    def reset_selection(self):
        to_uncheck = [p for p, v in self.file_vars.items() if v.get()]
        search_was_active = self.file_search_var.get() != ""

        if not to_uncheck and not search_was_active:
            return

        self.reset_button_clicked = True

        if to_uncheck:
            with self.bulk_update_mode():
                for path in to_uncheck:
                    self.file_vars[path].set(False)

        if search_was_active:
            self.file_search_var.set("")
        else:
            if self.settings.get('reset_scroll_on_reset', True):
                self.files_canvas.yview_moveto(0.0)
            self.reset_button_clicked = False

    def start_bulk_update_and_reselect(self, files_to_select):
        self.bulk_update_active = True; self._bulk_update_list = list(self.file_vars.keys())
        self._bulk_update_selection = set(files_to_select); self._bulk_update_index = 0
        self._bulk_update_chunk_size = self.bulk_chunk; self.after(1, self._bulk_update_next_chunk)

    def _bulk_update_next_chunk(self):
        if self._bulk_update_index >= len(self._bulk_update_list):
            self.bulk_update_active = False
            # Re-show the list once every BooleanVar has been set
            if getattr(self, "_pending_repack", False):
                if getattr(self, '_geom_manager', None) and getattr(self, '_geom_info', None):
                    opts = self._geom_info.copy()
                    if 'in' in opts:
                        opts['in_'] = opts.pop('in')

                    if self._geom_manager == 'pack':
                        self.file_frame.pack(**opts)
                    elif self._geom_manager == 'grid':
                        self.file_frame.grid(**opts)
                    elif self._geom_manager == 'place':
                        self.file_frame.place(**opts)
                self._pending_repack = False
            self.on_file_selection_changed()
            if self.reset_button_clicked:
                self.filter_and_display_items()
            return
        end = min(self._bulk_update_index + self._bulk_update_chunk_size, len(self._bulk_update_list))
        for f in self._bulk_update_list[self._bulk_update_index:end]:
            self.file_vars[f].set(f in self._bulk_update_selection)
        self._bulk_update_index = end
        self.after(1, self._bulk_update_next_chunk)

    def add_history_selection(self, selection):
        history = self.settings.get(HISTORY_SELECTION_KEY, [])
        selection_set = set(selection)
        found = next((h for h in history if set(h["files"]) == selection_set and h.get("project") == self.current_project), None)
        if found: found["gens"] = found.get("gens", 0) + 1; found["timestamp"] = time.time()
        else:
            history.append({"id": hashlib.md5(",".join(sorted(selection)).encode('utf-8')).hexdigest(), "files": selection, "timestamp": time.time(), "gens": 1, "project": self.current_project or "(Unknown)", "saved_project_name": self.current_project})
        self.settings[HISTORY_SELECTION_KEY] = sorted(history, key=lambda x: x["timestamp"], reverse=True)[:20]

    # Generation & Output Logic
    # ------------------------------
    def generate_output(self, template_override=None): self._initiate_generation(template_override, to_clipboard=False)
    def generate_output_to_clipboard(self, template_override=None): self._initiate_generation(template_override, to_clipboard=True)
    
    def _initiate_generation(self, template_override, to_clipboard):
        if self.settings_dialog and self.settings_dialog.winfo_exists(): self.settings_dialog.save_settings()
        if not self.current_project: return show_warning_centered(self, "No Project Selected", "Please select a project first.")
        sel = [p for p, v in self.file_vars.items() if v.get()]
        active_template = template_override if template_override is not None else self.template_var.get()
        tpl_content = self.templates.get(active_template, "")
        if not sel and "{{CLIPBOARD}}" not in tpl_content: return show_warning_centered(self, "Warning", "No files selected.")
        if len(sel) > MAX_FILES: return show_warning_centered(self, "Warning", f"Selected {len(sel)} files. Max is {MAX_FILES}.")
        proj = self.projects[self.current_project]
        if not os.path.isdir(proj["path"]): return show_error_centered(self, "Invalid Path", "Project directory does not exist.")
        self.update_file_contents(sel)
        precompute_key = self.get_precompute_key(sel, active_template)
        if precompute_key in self.precomputed_prompt_cache and not to_clipboard:
            prompt, _ = self.precomputed_prompt_cache[precompute_key]
            return self.finalize_generation(prompt, sel)
        self.generate_button.config(state=tk.DISABLED)
        self.generate_menu_button_md.config(state=tk.DISABLED)
        self.generate_menu_button_cb.config(state=tk.DISABLED)
        self.status_label.config(text=f"Generating{' for clipboard' if to_clipboard else ''}...")
        proj["last_files"] = sel
        if template_override is None: proj["last_template"] = self.template_var.get()
        target = self.generate_output_to_clipboard_worker if to_clipboard else self.generate_output_worker
        threading.Thread(target=target, args=(sel, active_template), daemon=True).start()

    def simulate_final_prompt(self, selection, template_override=None):
        prompt, _, total_selection_chars = self.simulate_generation(selection, template_override)
        return prompt.rstrip('\n') + '\n', total_selection_chars

    def simulate_generation(self, selection, template_override=None):
        proj = self.projects[self.current_project]; proj_path = proj["path"]; prefix = proj.get("prefix", "").strip()
        s1 = f"### {prefix} File Structure" if prefix else "### File Structure"
        s2 = f"### {prefix} Code Files provided" if prefix else "### Code Files provided"
        s3 = f"### {prefix} Code Files" if prefix else "### Code Files"
        gitignore_patterns = parse_gitignore(os.path.join(proj_path, '.gitignore')) if self.settings.get('respect_gitignore', True) and os.path.isfile(os.path.join(proj_path, '.gitignore')) else []
        keep_patterns = proj.get("keep", []) + self.settings.get("global_keep", [])
        dir_tree = self.generate_directory_tree_custom(proj_path, proj.get('blacklist', []) + self.settings.get("global_blacklist", []), self.settings.get('respect_gitignore', True), gitignore_patterns, keep_patterns)
        
        template_name = template_override if template_override is not None else self.template_var.get()
        template_content = self.templates.get(template_name, "")
        if "{{CLIPBOARD}}" in template_content:
            try: template_content = template_content.replace("{{CLIPBOARD}}", self.clipboard_get())
            except tk.TclError: template_content = template_content.replace("{{CLIPBOARD}}", "")

        content_blocks, total_size, total_selection_chars = [], 0, 0
        with self.data_lock:
            for rp in selection:
                content = self.file_contents.get(rp)
                if content is None: continue
                total_selection_chars += len(content)
                if total_size + len(content) > MAX_CONTENT_SIZE: break
                content_blocks.append(f"--- {rp} ---\n{content}\n--- {rp} ---\n")
                total_size += len(content)
        
        prompt = template_content.replace("{{dirs}}", f"{s1}\n\n{dir_tree.strip()}")
        if "{{files_provided}}" in prompt:
            lines = "".join(f"- {x}\n" for x in selection if x in self.file_contents and self.file_contents.get(x) is not None)
            prompt = prompt.replace("{{files_provided}}", f"\n\n{s2}\n{lines}".rstrip('\n'))
        else: prompt = prompt.replace("{{files_provided}}", "")
        
        file_content_section = f"\n\n{s3}\n\n{''.join(content_blocks)}" if content_blocks else ""
        return prompt.replace("{{file_contents}}", file_content_section), content_blocks, total_selection_chars

    def generate_directory_tree_custom(self, start_path, blacklist, respect_git, git_patterns, keep_patterns, max_depth=10, max_lines=1000):
        lines, stack = [], [(start_path, 0)]
        blacklist_lower = [b.strip().lower() for b in blacklist]
        while stack and len(lines) < max_lines:
            current_path, depth = stack.pop()
            rel_path = os.path.relpath(current_path, start_path).replace("\\", "/")
            if rel_path == ".": rel_path = ""
            lines.append(f"{'    ' * depth}{os.path.basename(current_path) if depth > 0 else os.path.basename(start_path)}/")
            if len(lines) >= max_lines or depth >= max_depth: continue
            try: entries = sorted(os.listdir(current_path))
            except OSError: continue
            dirs_to_visit, files_to_list = [], []
            for entry in entries:
                full_path = os.path.join(current_path, entry); rel_entry = f"{rel_path}/{entry}".lstrip("/").lower()
                if path_should_be_ignored(rel_entry, respect_git, git_patterns, keep_patterns, blacklist_lower):
                    if os.path.isdir(full_path) and is_dir_forced_kept(rel_entry, keep_patterns): dirs_to_visit.append(entry)
                    continue
                if os.path.isdir(full_path): dirs_to_visit.append(entry)
                else: files_to_list.append(entry)
            if len(dirs_to_visit) + len(files_to_list) > 50 and rel_path: lines.append(f"{'    ' * (depth + 1)}... (directory too large)"); continue
            for d in reversed(dirs_to_visit): stack.append((os.path.join(current_path, d), depth + 1))
            for f in files_to_list:
                if len(lines) >= max_lines: break
                lines.append(f"{'    ' * (depth + 1)}{f}")
        if len(lines) >= max_lines: lines.append("... (output truncated due to size limits)")
        return "\n".join(lines)
        
    def save_and_open(self, output):
        ts = datetime.now().strftime("%d.%m.%Y_%H.%M.%S"); safe_proj_name = ''.join(c for c in self.current_project if c.isalnum() or c in ' _').rstrip()
        filename = f"{safe_proj_name}_{ts}.md"; filepath = os.path.join(OUTPUT_DIR, filename)
        try:
            with open(filepath, 'w', encoding='utf-8', newline='\n') as f: f.write(output)
            open_in_editor(filepath)
        except Exception: logger.error("%s", traceback.format_exc()); show_error_centered(self, "Error", "Failed to save output.")

    def save_silently(self, output, project_name):
        ts = datetime.now().strftime("%d.%m.%Y_%H.%M.%S"); safe_proj_name = ''.join(c for c in project_name if c.isalnum() or c in ' _').rstrip() or "output"
        filename = f"{safe_proj_name}_{ts}.md"; filepath = os.path.join(OUTPUT_DIR, filename)
        try:
            with open(filepath, 'w', encoding='utf-8', newline='\n') as f: f.write(output)
        except Exception as e:
            logger.error("Failed to save output silently: %s", e, exc_info=True)
            self.queue.put(('show_warning', ('Save Error', 'Failed to save output silently.')))

    def save_and_open_notepadpp(self, content):
        ts = datetime.now().strftime("%d.%m.%Y_%H.%M.%S")
        safe_proj_name = ''.join(c for c in (self.current_project or "temp") if c.isalnum() or c in ' _').rstrip() or "temp"
        filename = f"{safe_proj_name}_text_{ts}.txt"; filepath = os.path.join(OUTPUT_DIR, filename)
        try:
            with open(filepath, 'w', encoding='utf-8') as f: f.write(unify_line_endings(content).rstrip('\n'))
            if platform.system() == 'Windows':
                try: subprocess.Popen(["notepad++", filepath])
                except FileNotFoundError: os.startfile(filepath)
            else: subprocess.call(('xdg-open', filepath))
            self.set_status_temporary("Opened in editor")
        except Exception: logger.error("%s", traceback.format_exc()); show_error_centered(self, "Error", "Failed to open in editor.")

    # Background Processing & Threading
    # ------------------------------
    def load_items_in_background(self, is_new_project=False, is_silent=False):
        if hasattr(self, 'loading_thread') and self.loading_thread and self.loading_thread.is_alive(): return
        self.status_label.config(text="Loading..."); self.is_silent_refresh = is_silent
        if is_new_project: self.project_tree_scroll_pos = 0.0
        self.loading_thread = threading.Thread(target=self._load_items_worker, args=(is_new_project,), daemon=True); self.loading_thread.start()

    def _load_items_worker(self, is_new_project):
        if not self.current_project: return
        proj = self.projects[self.current_project]; proj_path = proj["path"]
        if not os.path.isdir(proj_path): return self.queue.put(('load_items_done', ("error", None, is_new_project)))
        
        proj_bl = proj.get("blacklist", []); glob_bl = self.settings.get("global_blacklist", [])
        comb_bl = list(set(proj_bl + glob_bl)); comb_bl_lower = [b.strip().lower().replace("\\", "/") for b in comb_bl]
        proj_kp = proj.get("keep", []); glob_kp = self.settings.get("global_keep", [])
        comb_kp = list(set(proj_kp + glob_kp))
        git_patterns = parse_gitignore(os.path.join(proj_path, '.gitignore')) if self.settings.get('respect_gitignore', True) and os.path.isfile(os.path.join(proj_path, '.gitignore')) else []
        
        found_items, file_count, limit_exceeded = [], 0, False
        for root, dirs, files in os.walk(proj_path, topdown=True):
            if file_count >= MAX_FILES: limit_exceeded = True; break
            rel_root = os.path.relpath(root, proj_path).replace("\\", "/"); rel_root = "" if rel_root == "." else rel_root
            dirs[:] = sorted([d for d in dirs if not path_should_be_ignored(f"{rel_root}/{d}".lstrip("/").lower(), self.settings.get('respect_gitignore',True), git_patterns, comb_kp, comb_bl_lower) or is_dir_forced_kept(f"{rel_root}/{d}".lstrip("/").lower(), comb_kp)])
            if rel_root: found_items.append({"type": "dir", "path": rel_root + "/", "level": rel_root.count('/')})
            for f in sorted(files):
                if file_count >= MAX_FILES: limit_exceeded = True; break
                rel_path = f"{rel_root}/{f}".lstrip("/")
                if not path_should_be_ignored(rel_path.lower(), self.settings.get('respect_gitignore', True), git_patterns, comb_kp, comb_bl_lower):
                    if os.path.isfile(os.path.join(root, f)):
                        found_items.append({"type": "file", "path": rel_path, "level": rel_path.count('/')}); file_count += 1
        self.queue.put(('load_items_done', ("ok", (found_items, limit_exceeded, []), is_new_project)))

    def run_autoblacklist_in_background(self, proj_name):
        if hasattr(self, 'autoblacklist_thread') and self.autoblacklist_thread and self.autoblacklist_thread.is_alive(): return
        self.autoblacklist_thread = threading.Thread(target=self._auto_blacklist_worker, args=(proj_name,), daemon=True); self.autoblacklist_thread.start()

    def _auto_blacklist_worker(self, proj_name):
        new_additions = self.check_and_auto_blacklist(proj_name)
        if new_additions: self.queue.put(('auto_bl', (proj_name, new_additions)))
    
    def start_precompute_worker(self):
        self.precompute_thread = threading.Thread(target=self._precompute_worker, daemon=True); self.precompute_thread.start()

    def _precompute_worker(self):
        while True:
            self.precompute_request.wait()
            with self.precompute_lock:
                self.precompute_request.clear()
                if not self.current_project: continue
                sel = [p for p, v in self.file_vars.items() if v.get()]
                template_name = self.template_var.get()
                self.update_file_contents(sel)
                prompt, total_chars = self.simulate_final_prompt(sel, template_name)
                key = self.get_precompute_key(sel, template_name)
                self.precomputed_prompt_cache = {key: (prompt, total_chars)}
    
    # ------------------------------
    # Background Processing & Threading
    # ------------------------------
    def _char_count_worker(self):
        request_token = self._char_count_token
        try:
            sel = [p for p, v in self.file_vars.items() if v.get()]
            self.update_file_contents(sel)
            prompt, _ = self.simulate_final_prompt(sel, self.template_var.get())
            total_chars = len(prompt)
            if self._char_count_token == request_token:
                self.queue.put(('char_count_done', (len(sel), total_chars)))
        except Exception as e:
            logger.error("Character count worker failed: %s", e, exc_info=True)
            if self._char_count_token == request_token:
                self.queue.put(('char_count_done', (len(sel), -1)))
        
    def generate_output_worker(self, sel, template_override):
        try:
            self.update_file_contents(sel)
            prompt, _ = self.simulate_final_prompt(sel, template_override)
            self.queue.put(('save_and_open', (prompt, sel)))
        except Exception as e: logger.error("Error generating output: %s", e, exc_info=True); self.queue.put(('error', "Error generating output."))

    def generate_output_to_clipboard_worker(self, sel, template_override):
        try:
            self.update_file_contents(sel)
            prompt, _ = self.simulate_final_prompt(sel, template_override)
            self.queue.put(('copy_and_save_silently', (prompt, sel)))
        except Exception as e: logger.error("Error generating for clipboard: %s", e, exc_info=True); self.queue.put(('error', "Error generating for clipboard."))

    # Event Handlers
    # ------------------------------
    def on_project_selected(self, _):
        disp = self.project_var.get(); name = disp.split(' (')[0] if ' (' in disp else disp; self.load_project(name)

    def on_template_selected(self, _):
        if self.current_project: self.projects[self.current_project]["last_template"] = self.template_var.get()

    def on_search_changed(self, *args):
        # always repaint from the very top after a search-bar keystroke
        if self.search_debounce_timer: self.after_cancel(self.search_debounce_timer)
        stt = not self.skip_search_scroll
        self.skip_search_scroll = False
        self.search_debounce_timer = self.after(200, lambda top=stt: self.filter_and_display_items(scroll_to_top=top))

    def on_checkbox_toggled(self, f_path):
        if self.bulk_update_active: self.previous_check_states[f_path] = self.file_vars[f_path].get(); return
        if not self.previous_check_states.get(f_path, False) and self.file_vars[f_path].get():
            self.click_counts[f_path] = min(self.click_counts.get(f_path, 0) + 1, 100)
            if self.current_project: self.projects[self.current_project]['click_counts'] = self.click_counts
        self.previous_check_states[f_path] = self.file_vars[f_path].get(); self.update_row_color(f_path)
        if self.checkbox_toggle_timer: self.after_cancel(self.checkbox_toggle_timer)
        self.checkbox_toggle_timer = self.after(10, self.on_file_selection_changed)

    def on_file_selection_changed(self, *a):
        if self.bulk_update_active: return
        selected = [p for p, v in self.file_vars.items() if v.get()]
        if self.current_project: self.projects[self.current_project]["last_files"] = selected
        self.file_selected_label.config(text=f"Files selected: {len(selected)} / {self.all_files_count} (Chars: Calculating...)")
        self._char_count_token += 1
        threading.Thread(target=self._char_count_worker, daemon=True).start()
        self.refresh_selected_files_list(selected); self.update_select_all_button(); self.request_precomputation()

    def on_selected_file_clicked(self, f_path): self.clipboard_clear(); self.clipboard_append(f_path); self.set_status_temporary("Copied to clipboard")
    
    def on_files_mousewheel(self, event):
        w = event.widget
        target_canvas = None
        while w is not None:
            if w == self.files_canvas:
                target_canvas = self.files_canvas
                break
            if w == self.selected_files_canvas:
                target_canvas = self.selected_files_canvas
                break
            w = w.master
        if target_canvas:
            if event.num == 4: target_canvas.yview_scroll(-1, "units")
            elif event.num == 5: target_canvas.yview_scroll(1, "units")
            else: target_canvas.yview_scroll(int(-1 * (event.delta / 120)) if platform.system() == 'Windows' else int(-1 * event.delta), "units")
        return "break"

    def on_quick_copy_selected(self, _):
        val = self.quick_copy_var.get(); self.quick_copy_dropdown.set("")
        if not val or val.startswith("-- "): return
        try: clip_in = self.clipboard_get()
        except tk.TclError: clip_in = ""
        project_name = self.current_project or "ClipboardAction"
        if val == "Truncate Between '---'":
            processed_text, notification = self.process_quick_copy_format(clip_in)
            self.clipboard_clear(); self.clipboard_append(processed_text)
            self.set_status_temporary(notification, 4000)
            return
        if val in self.templates and "{{CLIPBOARD}}" in self.templates[val]:
            content = self.templates[val].replace("{{CLIPBOARD}}", clip_in).strip()
            self.clipboard_clear(); self.clipboard_append(content); self.save_silently(content, project_name); self.set_status_temporary("Copied to clipboard")
            return
        op_map = {"Replace \"**\"": lambda t: t.replace("**", ""), "Remove Duplicates": lambda t: '\n'.join(dict.fromkeys(t.rstrip('\n').split('\n'))),
                  "Sort Alphabetically": lambda t: '\n'.join(sorted(t.rstrip('\n').split('\n'))), "Sort by Length": lambda t: '\n'.join(sorted(t.rstrip('\n').split('\n'), key=len)),
                  "Escape Text": lambda t: t.rstrip('\n').encode('unicode_escape').decode('ascii', 'ignore'), "Unescape Text": lambda t: codecs.decode(t.rstrip('\n'), 'unicode_escape')}
        if val in op_map:
            try: new_clip = op_map[val](clip_in).strip()
            except Exception: return self.set_status_temporary("Operation failed!", 3000)
            self.clipboard_clear(); self.clipboard_append(new_clip); self.save_silently(new_clip, project_name); self.set_status_temporary("Clipboard updated")

    def on_project_dropdown_search(self, event):
        now = time.time()
        if now - self.project_search_last_key_time > 1.0:
            self.project_search_buffer = ""
        self.project_search_last_key_time = now

        # update the search buffer
        if event.keysym == "BackSpace":
            if self.project_search_buffer:
                self.project_search_buffer = self.project_search_buffer[:-1]
        # when the listbox owns the focus, `event.char` is '', so use `keysym`
        elif (len(event.char) == 1 and event.char.isprintable()) or (
              len(event.keysym) == 1 and event.keysym.isprintable()):
            ch = event.char if event.char else event.keysym
            self.project_search_buffer += ch.lower()
        elif event.keysym == "Escape":
            self.project_search_buffer = ""
            return
        else:
            return

        if not self.project_search_buffer:
            return

        values = list(self.project_dropdown["values"])
        match_val = next(
            (v for v in values if v.split(" (")[0].lower().startswith(self.project_search_buffer)),
            None,
        )
        if not match_val:
            return

        # ── CASE 1: key event came from the drop-down Listbox (open state) ──
        lb = getattr(self, "_project_listbox", None)
        if lb and lb.winfo_exists():
            try:
                idx = values.index(match_val)
                # sync both the pop-down listbox *and* the combobox state
                lb.selection_clear(0, tk.END)
                lb.selection_set(idx)
                lb.activate(idx)
                lb.see(idx)
                self.project_dropdown.current(idx)   # ★ keep combobox in sync ★
                self.project_var.set(match_val)
            except ValueError: pass
            self.project_var.set(match_val)
            if event.widget is lb: return "break"
        idx = values.index(match_val)
        self.project_dropdown.current(idx)           # ★ ensure internal index ★
        self.project_var.set(match_val)
        self.project_dropdown.event_generate("<<ComboboxSelected>>")

    def bind_mousewheel_events(self, widget):
        widget.bind("<MouseWheel>", self.on_files_mousewheel, add='+')
        widget.bind("<Button-4>", self.on_files_mousewheel, add='+')
        widget.bind("<Button-5>", self.on_files_mousewheel, add='+')
        
    def open_settings(self):
        if self.current_project:
            if self.settings_dialog and self.settings_dialog.winfo_exists(): self.settings_dialog.destroy()
            self.settings_dialog = SettingsDialog(self)
        else: show_warning_centered(self,"No Project Selected","Please select a project first.")

    def manage_templates(self):
        if self.current_project:
            if self.templates_dialog and self.templates_dialog.winfo_exists(): self.templates_dialog.destroy()
            self.templates_dialog = TemplatesDialog(self); self.wait_window(self.templates_dialog); self.load_templates(force_refresh=True)
        else: show_warning_centered(self,"No Project Selected","Please select a project first.")

    def open_history_selection(self):
        if not self.current_project: show_warning_centered(self,"No Project Selected","Please select a project first."); return
        HistorySelectionDialog(self)

    def bind_project_listbox(self):
        """
        Attach our incremental-search KeyPress handler to the Listbox that appears
        inside the Combobox pop-down.  The widget names differ across Tcl/Tk
        versions, so we search the pop-down’s descendants instead of relying on a
        hard-coded path.
        """
        try:
            # Pop-down toplevel created by ttk::combobox
            popdown_path = self.tk.call("ttk::combobox::PopdownWindow", self.project_dropdown)
            popdown_widget = self.nametowidget(popdown_path)

            # recursive search for the first Listbox
            def _find_listbox(widget):
                if isinstance(widget, tk.Listbox):
                    return widget
                for child in widget.winfo_children():
                    result = _find_listbox(child)
                    if result is not None:
                        return result
                return None

            listbox = _find_listbox(popdown_widget)
            if listbox is not None:
                self._project_listbox = listbox
                listbox.bind("<KeyPress>", self.on_project_dropdown_search, add="+")

        except Exception as e:
            # Non-fatal: just skip binding if the pop-down isn’t ready
            logger.debug("bind_project_listbox: %s", e, exc_info=False)

    def open_output_files(self): OutputFilesDialog(self)
    def open_text_editor(self): TextEditorDialog(self, initial_text="")
    
    # Queue Processing & UI Updates
    # ------------------------------
    def process_queue(self):
        try:
            while True:
                task, data = self.queue.get_nowait()
                handler = getattr(self, f"_handle_queue_{task}", None)
                if handler: handler(data)
        except queue.Empty: pass
        self.after(50, self.process_queue)

    def _handle_queue_save_and_open(self, data): self.finalize_generation(data[0], data[1])
    def _handle_queue_copy_and_save_silently(self, data): self.finalize_clipboard_generation(data[0], data[1])
    def _handle_queue_set_status_temporary(self, data): self.set_status_temporary(data[0], data[1])
    def _handle_queue_show_warning(self, data): show_warning_centered(self, data[0], data[1])
    def _handle_queue_error(self, data):
        show_error_centered(self, "Error", data); self.generate_button.config(state=tk.NORMAL)
        self.generate_menu_button_md.config(state=tk.NORMAL); self.generate_menu_button_cb.config(state=tk.NORMAL); self.status_label.config(text="Ready")
    def _handle_queue_load_items_done(self, data):
        status, result, is_new_project = data
        if status == "error": show_error_centered(self, "Invalid Path", "Project directory does not exist.")
        else: self.load_items_result(result, is_new_project)
        self.status_label.config(text="Ready")
    def _handle_queue_auto_bl(self, data): self.on_auto_blacklist_done(data[0], data[1])
    def _handle_queue_char_count_done(self, data):
        f_count, c_count = data
        self.update_selection_char_count(f_count, c_count)
    def _handle_queue_file_contents_loaded(self, proj):
        if proj == self.current_project:
            with self.data_lock:
                for p, lbl in self.file_labels.items(): lbl.config(text=f"{os.path.basename(p)} [{format_german_thousand_sep(self.file_char_counts.get(p,0))}]")
            self.refresh_selected_files_list([p for p,v in self.file_vars.items() if v.get()]); self.request_precomputation()

    def load_items_result(self, data, is_new_project):
        with self.data_lock:
            for d in [self.file_contents, self.file_char_counts, self.file_hashes, self.file_mtimes, self.file_vars]: d.clear()
        self.all_items = data[0]
        if data[1]: show_warning_centered(self, "File Limit Exceeded", f"Only the first {MAX_FILES} files are loaded.")
        last_files = self.projects[self.current_project].get("last_files", []) if not is_new_project else []
        if is_new_project: self.projects[self.current_project]["last_files"] = []
        self.file_labels.clear(); self.row_frames.clear()
        self.all_files_count = sum(1 for it in self.all_items if it["type"] == "file")
        with self.data_lock:
            for it in self.all_items:
                if it["type"] == "file":
                    self.file_vars[it["path"]] = tk.BooleanVar(value=(it["path"] in last_files))
                    self.previous_check_states[it["path"]] = self.file_vars[it["path"]].get()
        for path_var in self.file_vars: self.file_vars[path_var].trace_add('write', lambda *a, pv=path_var: self.on_checkbox_toggled(pv))
        self.filter_and_display_items()
        threading.Thread(target=self._load_file_contents_worker, daemon=True).start()

    def _load_file_contents_worker(self):
        if not self.current_project: return
        proj_path = self.projects[self.current_project]["path"]
        files_to_load = [item["path"] for item in self.all_items if item["type"] == "file"]
        with self.data_lock:
            for rp in files_to_load:
                ap = os.path.join(proj_path, rp)
                try:
                    fsize = os.path.getsize(ap) if os.path.isfile(ap) else 0
                    self.file_char_counts[rp] = fsize
                    self.file_contents[rp] = None if fsize > MAX_FILE_SIZE else ""
                except OSError: self.file_contents[rp], self.file_char_counts[rp] = None, 0
        self.queue.put(('file_contents_loaded', self.current_project))
    
    def check_and_auto_blacklist(self, proj_name, threshold=50):
        proj, proj_path = self.projects[proj_name], self.projects[proj_name]["path"]
        if not os.path.isdir(proj_path): return []
        current_bl = proj.get("blacklist", []) + self.settings.get("global_blacklist", [])
        keep_patterns = proj.get("keep", []) + self.settings.get("global_keep", [])
        git_patterns = parse_gitignore(os.path.join(proj_path, '.gitignore')) if self.settings.get('respect_gitignore', True) else []
        new_blacklisted = []
        for root, dirs, files in os.walk(proj_path):
            rel_root = os.path.relpath(root, proj_path).replace("\\", "/").strip("/")
            if any(bl.lower() in rel_root.lower() for bl in current_bl if rel_root): continue
            unignored_files = [f for f in files if not path_should_be_ignored(f"{rel_root}/{f}".strip("/").lower(), self.settings.get('respect_gitignore',True), git_patterns, keep_patterns, current_bl)]
            if len(unignored_files) > threshold and rel_root and rel_root.lower() not in [b.lower() for b in current_bl]:
                new_blacklisted.append(rel_root)
        return new_blacklisted

    def on_auto_blacklist_done(self, proj_name, dirs):
        proj = self.projects[proj_name]; proj["blacklist"] = list(dict.fromkeys(proj.get("blacklist", []) + dirs)); self.save_app_projects()
        if self.current_project == proj_name: show_info_centered(self, "Auto-Blacklisted", f"Directories with >50 files were blacklisted:\n\n{', '.join(dirs)}")
    
    def finalize_generation(self, output, selection):
        proj = self.projects[self.current_project]; proj["last_usage"] = time.time(); proj["usage_count"] = proj.get("usage_count", 0) + 1
        self.sort_and_set_projects(self.project_dropdown); self.save_and_open(output)
        self.generate_button.config(state=tk.NORMAL); self.generate_menu_button_md.config(state=tk.NORMAL); self.generate_menu_button_cb.config(state=tk.NORMAL)
        self.status_label.config(text="Ready"); self.add_history_selection(selection)
        
    def finalize_clipboard_generation(self, output, selection):
        self.clipboard_clear(); self.clipboard_append(output); self.set_status_temporary("Copied to clipboard.")
        self.save_silently(output, self.current_project)
        self.generate_button.config(state=tk.NORMAL); self.generate_menu_button_md.config(state=tk.NORMAL); self.generate_menu_button_cb.config(state=tk.NORMAL)
        self.status_label.config(text="Ready"); self.add_history_selection(selection)

    def refresh_selected_files_list(self, selected):
        for w in self.selected_files_inner.winfo_children(): w.destroy()
        max_len = 0; longest_txt = ""; display_data = []
        with self.data_lock:
            for f in selected:
                lbl_txt = f"{f} [{format_german_thousand_sep(self.file_char_counts.get(f, 0))}]"
                display_data.append((f, lbl_txt))
                if len(lbl_txt) > max_len: max_len, longest_txt = len(lbl_txt), lbl_txt
        for f, lbl_text in display_data:
            rf = ttk.Frame(self.selected_files_inner); rf.pack(fill=tk.X, anchor='w')
            xb = ttk.Button(rf, text="x", width=1, style='RemoveFile.TButton', command=lambda ff=f: self.file_vars[ff].set(False))
            xb.pack(side=tk.LEFT, padx=(0,5)); self.bind_mousewheel_events(xb)
            lbl = ttk.Label(rf, text=lbl_text, cursor="hand2"); lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
            lbl.bind("<Button-1>", lambda e, ff=f: self.on_selected_file_clicked(ff)); self.bind_mousewheel_events(lbl)
        try:
            w = tkfont.nametofont('TkDefaultFont').measure(longest_txt) + 60
            scr_w = self.winfo_screenwidth() // 2
            self.selected_files_canvas.master.config(width=min(max(w, 150), scr_w))
        except Exception: pass
        self.selected_files_canvas.yview_moveto(0)

    def update_select_all_button(self):
        filtered_files = [x for x in self.filtered_items if x["type"] == "file"]
        if filtered_files: self.select_all_button.config(text="Unselect All" if all(self.file_vars[x["path"]].get() for x in filtered_files) else "Select All")
        else: self.select_all_button.config(text="Select All")
        
    def update_row_color(self, p):
        if p not in self.row_frames: return
        ratio = min(self.click_counts.get(p, 0) / 100, 1.0)
        nr = int(243 + (206 - 243) * ratio); ng = int(243 + (230 - 243) * ratio); nb = int(243 + (255 - 243) * ratio)
        hexcolor = f"#{nr:02x}{ng:02x}{nb:02x}"
        self.row_frames[p].config(bg=hexcolor)
        for w in self.row_frames[p].winfo_children():
            if isinstance(w, tk.Label): w.config(bg=hexcolor)

    def sort_and_set_projects(self, combobox):
        usage_list = sorted(
            [(k, p.get("last_usage", 0), p.get("usage_count", 0))
             for k, p in self.projects.items()],
            key=lambda x: (-x[1], -x[2], x[0].lower())
        )
        sorted_display_values = [
            f"{n} ({get_relative_time_str(lu)})" if lu > 0 else n
            for n, lu, uc in usage_list
        ]
        max_w = max((len(d) for d in sorted_display_values), default=20)
        combobox["values"] = sorted_display_values

        # --- keep current selection even if its “(x seconds ago)” text changed ---
        cur_disp = self.project_var.get()
        cur_name = cur_disp.split(" (")[0] if " (" in cur_disp else cur_disp
        match = next(
            (d for d in sorted_display_values
             if d == cur_name or d.startswith(f"{cur_name} (")),
            None
        )
        if match:
            combobox.set(match)
        elif sorted_display_values:
            combobox.set(sorted_display_values[0])

        combobox.configure(width=max(max_w, 20))

    def get_precompute_key(self, sel, template_name):
        h = hashlib.md5()
        for fp in sorted(sel):
            h.update(fp.encode())
            h.update(str(self.file_mtimes.get(fp, 0)).encode())
        if "{{CLIPBOARD}}" in self.templates.get(template_name, ""):
            try: h.update(self.clipboard_get().encode())
            except tk.TclError: pass
        h.update(template_name.encode())
        return h.hexdigest()

    def request_precomputation(self): self.precompute_request.set()
    def update_selection_char_count(self, f_count, c_count):
        char_str = "Error" if c_count < 0 else f"Total Chars: {format_german_thousand_sep(c_count)}"
        self.file_selected_label.config(text=f"Files selected: {f_count} / {self.all_files_count} ({char_str})")
    
    def _strip_bold_markers_safely(self, text):
        lines = text.split('\n')
        output_lines = []
        in_fenced_code = False
        for line in lines:
            if line.startswith('```'):
                in_fenced_code = not in_fenced_code
                output_lines.append(line)
                continue
            if in_fenced_code or line.startswith('    '):
                output_lines.append(line)
                continue
            parts = re.split(r'(`[^`]*`)', line)
            processed_line = "".join([part if i % 2 == 1 else part.replace('**', '') for i, part in enumerate(parts)])
            output_lines.append(processed_line)
        return '\n'.join(output_lines)

    def process_quick_copy_format(self, text):
        text = unify_line_endings(text)
        text = self._strip_bold_markers_safely(text)
        lines = text.split('\n')
        delimiter_indices = [i for i, line in enumerate(lines) if re.match(r'^\s*---\s*$', line)]
        between = len(delimiter_indices) >= 2
        final_lines = (
            lines[delimiter_indices[0] + 1:delimiter_indices[1]]
            if between else lines
        )
        start_content = 0
        while start_content < len(final_lines) and not final_lines[start_content].strip(): start_content += 1
        end_content = len(final_lines) - 1
        while end_content >= start_content and not final_lines[end_content].strip(): end_content -= 1
        final_text = '\n'.join(final_lines[start_content:end_content + 1]) if start_content <= end_content else ""
        char_cnt = len(final_text)
        notification = (
            f"✅ Copied {char_cnt} chars (between delimiters)"
            if between else
            f"ℹ️ {'Only one' if len(delimiter_indices)==1 else 'No'} ‘---’ found – copied whole document ({char_cnt} chars)."
        )
        return final_text, notification

    def show_quick_generate_menu(self): self._show_quick_menu(self.generate_menu_button_md, self.generate_output)
    def show_quick_generate_menu_cb(self): self._show_quick_menu(self.generate_menu_button_cb, self.generate_output_to_clipboard)
    
    def _show_quick_menu(self, button, command_func):
        quick_templates = [n for n, c in self.templates.items() if not ("{{CLIPBOARD}}" in c and "{{file_contents}}" not in c)]
        if not quick_templates: return
        menu = tk.Menu(self, tearoff=0)
        for tpl in quick_templates: menu.add_command(label=tpl, command=lambda t=tpl: command_func(template_override=t))
        menu.post(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())
        
    def update_default_template_button(self): self.reset_template_btn.config(state=tk.NORMAL if self.settings.get("default_template_name") else tk.DISABLED)
    def reset_template_to_default(self):
        default_name = self.settings.get("default_template_name")
        if default_name and default_name in self.template_dropdown['values']: self.template_var.set(default_name); self.on_template_selected(None)

# Main Execution
# ------------------------------
if __name__ == "__main__":
    try:
        load_config()
        ensure_data_dirs()
        app = CodePromptGeneratorApp()
        app.mainloop()
    except Exception as e:
        logger.error("Fatal Error: %s\n%s", e, traceback.format_exc())
        print(f"A fatal error occurred: {e}", file=sys.stderr)