# File: code_prompt_generator/main.pyw
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

import sys, os, logging, traceback, configparser, tkinter as tk, json, threading, hashlib, queue, platform, subprocess, fnmatch, time, tempfile, random, string, copy, codecs
from tkinter import filedialog, ttk, simpledialog, scrolledtext
from filelock import FileLock, Timeout
from datetime import datetime

# NEW ▶ absolute anchor: directory containing this .pyw
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR    = os.path.join(BASE_DIR, "data")
CACHE_DIR  = os.path.join(DATA_DIR, "cache")
OUTPUT_DIR = os.path.join(DATA_DIR, "outputs")     # <─ now absolute

config = configparser.ConfigParser()
MAX_FILES = 500
MAX_CONTENT_SIZE = 2000000
MAX_FILE_SIZE = 500000
CACHE_EXPIRY_SECONDS = 3600

INSTANCE_ID = f"{os.getpid()}-{ ''.join(random.choices(string.ascii_lowercase + string.digits, k=6)) }"
log_path = os.path.join(DATA_DIR, "logs")

class InstanceLogAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"[{self.extra['instance_id']}] {msg}", kwargs

logger = logging.getLogger(__name__)
logger = InstanceLogAdapter(logger, {'instance_id': INSTANCE_ID})

from libs.logging_setup.setup_logging import setup_logging
setup_logging(log_level=logging.DEBUG, excluded_files=['server.py'], log_path=log_path)

LAST_OWN_WRITE_TIMES = {"projects": 0, "settings": 0}

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
    except: pass

def ensure_data_dirs():
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

PROJECTS_FILE = os.path.join(CACHE_DIR, 'projects.json')
SETTINGS_FILE = os.path.join(CACHE_DIR, 'settings.json')
PROJECTS_LOCK_FILE = os.path.join(CACHE_DIR, 'projects.json.lock')
SETTINGS_LOCK_FILE = os.path.join(CACHE_DIR, 'settings.json.lock')
HISTORY_SELECTION_KEY = "history_selection"

def load_json_safely(path, lock_path, error_queue=None, is_fatal=False):
    ensure_data_dirs()
    retries = 5
    for attempt in range(retries):
        try:
            with FileLock(lock_path, timeout=1):
                if not os.path.exists(path): return {}
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Timeout:
            logger.warning(f"Lock timeout for {path} on attempt {attempt + 1}")
            if attempt < retries - 1:
                time.sleep(0.5 + random.uniform(0, 0.5))
            else:
                msg = f"Could not acquire lock for reading {os.path.basename(path)}. Another instance may be busy."
                logger.error(msg)
                if error_queue: error_queue.put(('show_warning', ('Lock Timeout', msg)))
                return None if is_fatal else {}
        except (json.JSONDecodeError, IOError) as e:
            logger.error("Error reading %s: %s\n%s", path, e, traceback.format_exc())
            return {}
    return {}

def load_projects(error_queue=None): return load_json_safely(PROJECTS_FILE, PROJECTS_LOCK_FILE, error_queue, is_fatal=True)
def save_projects(projects_data, error_queue=None): atomic_write_json(projects_data, PROJECTS_FILE, PROJECTS_LOCK_FILE, "projects", error_queue)

def load_settings(error_queue=None): return load_json_safely(SETTINGS_FILE, SETTINGS_LOCK_FILE, error_queue, is_fatal=True)
def save_settings(settings_data, error_queue=None): atomic_write_json(settings_data, SETTINGS_FILE, SETTINGS_LOCK_FILE, "settings", error_queue)

def atomic_write_json(data, path, lock_path, file_key, error_queue=None):
    ensure_data_dirs()
    try:
        with FileLock(lock_path, timeout=5):
            old_data = {}
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        old_data = json.load(f)
                except (json.JSONDecodeError, IOError):
                    logger.warning("Could not read old data from %s, will overwrite.", path)

            if old_data == data:
                return

            tmp_path = path + f".tmp.{INSTANCE_ID}"
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, path)
            
            mw = os.path.getmtime(path)
            LAST_OWN_WRITE_TIMES[file_key] = mw
            logger.info("Saved %s successfully.", path)
    except Timeout:
        msg = f"Could not acquire lock for writing {os.path.basename(path)}. Your changes were not saved."
        logger.error(msg)
        if error_queue: error_queue.put(('show_warning', ('Save Skipped', msg)))
    except Exception as e:
        logger.error("Error in atomic_write_json for %s: %s\n%s", path, e, traceback.format_exc())

def center_window(win, parent):
    try:
        win.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = win.winfo_width(), win.winfo_height()
        x = px + (pw//2) - (w//2)
        y = py + (ph//2) - (h//2)
        win.geometry(f"+{x}+{y}")
    except:
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h = win.winfo_width(), win.winfo_height()
        x = (sw // 2) - (w // 2)
        y = (sh // 2) - (h // 2)
        win.geometry(f"+{x}+{y}")

def apply_modal_geometry(win, parent, key):
    s = parent.settings.get('modal_geometry',{})
    g = s.get(key)
    if g: win.geometry(g)
    else: center_window(win, parent)
    def on_close():
        parent.settings.setdefault('modal_geometry',{})[key]=win.geometry()
        parent.save_app_settings()
        win.destroy()
    win.protocol("WM_DELETE_WINDOW", on_close)
    win.focus_force()
    win.resizable(True, True)

def show_info_centered(parent, title, message):
    w = tk.Toplevel()
    w.title(title)
    ttk.Label(w, text=message).pack(padx=20, pady=20)
    b = ttk.Button(w, text="OK", command=w.destroy)
    b.pack(pady=5)
    if parent: apply_modal_geometry(w, parent, "InfoDialog")

def show_warning_centered(parent, title, message):
    w = tk.Toplevel()
    w.title(title)
    ttk.Label(w, text=message).pack(padx=20, pady=20)
    b = ttk.Button(w, text="OK", command=w.destroy)
    b.pack(pady=5)
    if parent: apply_modal_geometry(w, parent, "WarningDialog")

def show_error_centered(parent, title, message):
    if not parent:
        root = tk.Tk()
        root.withdraw()
    w = tk.Toplevel()
    w.title(title)
    ttk.Label(w, text=message).pack(padx=20, pady=20)
    b = ttk.Button(w, text="OK", command=w.destroy)
    b.pack(pady=5)
    if parent: apply_modal_geometry(w, parent, "ErrorDialog")
    else: center_window(w, root)

def show_yesno_centered(parent, title, message):
    w = tk.Toplevel()
    w.title(title)
    r = {"answer": False}
    ttk.Label(w, text=message).pack(padx=20, pady=20)
    def yes(): r["answer"] = True; w.destroy()
    def no(): w.destroy()
    bf = ttk.Frame(w)
    bf.pack()
    ttk.Button(bf, text="Yes", command=yes).pack(side=tk.LEFT, padx=10, pady=5)
    ttk.Button(bf, text="No", command=no).pack(side=tk.LEFT, padx=10, pady=5)
    apply_modal_geometry(w, parent, "YesNoDialog")
    w.wait_window()
    return r["answer"]

def show_yesnocancel_centered(parent, title, message, yes_text="Yes", no_text="No", cancel_text="Cancel"):
    w = tk.Toplevel()
    w.title(title)
    r = {"answer": "cancel"}
    ttk.Label(w, text=message).pack(padx=20, pady=20)
    def yes(): r["answer"] = "yes"; w.destroy()
    def no(): r["answer"] = "no"; w.destroy()
    def cancel(): w.destroy()
    bf = ttk.Frame(w)
    bf.pack(pady=5)
    ttk.Button(bf, text=yes_text, command=yes).pack(side=tk.LEFT, padx=10)
    ttk.Button(bf, text=no_text, command=no).pack(side=tk.LEFT, padx=10)
    ttk.Button(bf, text=cancel_text, command=cancel).pack(side=tk.LEFT, padx=10)
    w.protocol("WM_DELETE_WINDOW", cancel)
    apply_modal_geometry(w, parent, "YesNoCancelDialog")
    w.wait_window()
    return r["answer"]

def get_file_hash(file_path):
    try:
        h = hashlib.md5()
        with open(file_path, 'rb') as f:
            b = f.read(65536)
            while b:
                h.update(b)
                b = f.read(65536)
        h.update(str(os.path.getmtime(file_path)).encode('utf-8'))
        return h.hexdigest()
    except: logger.error("%s", traceback.format_exc()); return None

def get_cache_key(selected_files, file_hashes):
    d = ''.join(sorted([f + file_hashes.get(f, '') for f in selected_files]))
    return hashlib.md5(d.encode('utf-8')).hexdigest()

def get_cached_output(project_name, cache_key):
    ensure_data_dirs()
    try:
        cf = os.path.join(CACHE_DIR, f'cache_{project_name}.json')
        if not os.path.exists(cf): return None
        lock_path = cf + '.lock'
        with FileLock(lock_path, timeout=2):
            with open(cf,'r',encoding='utf-8') as f:
                c = json.load(f)

        now_t = time.time()
        stale = [k for k, v in c.items() if not isinstance(v, dict) or (now_t - v.get('time', 0) > CACHE_EXPIRY_SECONDS)]

        if stale:
            for sk in stale: del c[sk]
            save_cached_output(project_name, None, None, full_cache_data=c)

        entry = c.get(cache_key)
        if not isinstance(entry, dict): return None
        return entry.get('data')
    except (Timeout, json.JSONDecodeError, IOError, OSError) as e:
        logger.warning("Could not read cache for %s: %s", project_name, e)
        return None
    except Exception:
        logger.error("%s", traceback.format_exc()); return None

def save_cached_output(project_name, cache_key, output, full_cache_data=None):
    ensure_data_dirs()
    cf = os.path.join(CACHE_DIR, f'cache_{project_name}.json')
    lock_path = cf + '.lock'
    try:
        with FileLock(lock_path, timeout=5):
            c = {}
            if full_cache_data is not None:
                c = full_cache_data
            elif os.path.exists(cf):
                try:
                    with open(cf, 'r', encoding='utf-8') as f:
                        c = json.load(f)
                except (json.JSONDecodeError, IOError): pass
            if cache_key is not None:
                c[cache_key] = {"time": time.time(), "data": output}
            
            tmp_path = cf + f".tmp.{INSTANCE_ID}"
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(c, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, cf)
    except Timeout:
        logger.error("Timeout saving cache for %s", project_name)
    except Exception:
        logger.error("%s", traceback.format_exc())

def open_in_editor(file_path):
    try:
        if platform.system()=='Windows': os.startfile(file_path)
        elif platform.system()=='Darwin': subprocess.call(('open', file_path))
        else: subprocess.call(('xdg-open', file_path))
    except: logger.error("%s", traceback.format_exc())

def resource_path(relative_path):
    try: return os.path.join(sys._MEIPASS, relative_path)
    except: return os.path.abspath(os.path.join(".", relative_path))

def parse_gitignore(gitignore_path):
    p = []
    try:
        for l in open(gitignore_path,'r', encoding='utf-8'):
            l = l.strip()
            if l and not l.startswith('#'): p.append(l)
    except: logger.error("%s", traceback.format_exc())
    return p

def match_any_gitignore(path_segment, patterns):
    return any(fnmatch.fnmatch(path_segment, x) or fnmatch.fnmatch(os.path.basename(path_segment), x) for x in patterns)

def match_any_keep(path_segment, patterns):
    return any(fnmatch.fnmatch(path_segment, x) or fnmatch.fnmatch(os.path.basename(path_segment), x) for x in patterns)

def path_should_be_ignored(r, rg, gp, gk, bl):
    r2 = r.replace("\\","/").lower()
    if any(b in r2 for b in bl):
        if match_any_keep(r2, gk): return False
        return True
    if rg and match_any_gitignore(r2, gp):
        if match_any_keep(r2, gk): return False
        return True
    return False

def safe_read_file(path):
    try: return open(path,'r',encoding='utf-8-sig',errors='replace').read()
    except: logger.error("%s", traceback.format_exc()); return ""

def format_german_thousand_sep(num):
    return f"{num:,}".replace(",", ".")

def unify_line_endings(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')

def get_relative_time_str(dt_ts):
    diff = time.time() - dt_ts
    if diff<1.0: return "Now"
    diff=int(diff)
    if diff<60: return f"{diff} seconds ago"
    m=diff//60
    if m<60: return f"{m} minutes ago"
    h=diff//3600
    if h<24: return f"{h} hours ago"
    d=h//24
    if d<30: return f"{d} days ago"
    return "30+ days ago"

def is_dir_forced_kept(dr, keep_patterns):
    ds = dr.strip("/").replace("\\","/").lower()
    for k in keep_patterns:
        k2 = k.strip("/").replace("\\","/").lower()
        if k2.startswith(ds+"/") or k2==ds: return True
    return False

class RenameTemplateDialog(tk.Toplevel):
    def __init__(self, parent, old_name):
        super().__init__()
        self.parent = parent
        self.title("Rename Template")
        self.new_name = None
        self.old_name = old_name
        self.create_widgets()
        apply_modal_geometry(self, parent, "RenameTemplateDialog")
        self.wait_window()
    def create_widgets(self):
        lf = ttk.Frame(self)
        lf.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        ttk.Label(lf, text="Enter new template name:").pack(anchor='w')
        self.entry_var = tk.StringVar(value=self.old_name)
        self.entry = ttk.Entry(lf, textvariable=self.entry_var)
        self.entry.pack(fill=tk.X, pady=(5,5))
        bf = ttk.Frame(lf)
        bf.pack(anchor='e', pady=5)
        def ok():
            self.new_name = self.entry_var.get().strip()
            self.destroy()
        def cancel():
            self.new_name = None
            self.destroy()
        ttk.Button(bf, text="OK", command=ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text="Cancel", command=cancel).pack(side=tk.LEFT)
        self.entry.focus_set()

class SettingsDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__()
        self.title("Settings")
        self.parent = parent
        self.create_widgets()
        apply_modal_geometry(self, parent, "SettingsDialog")
    def create_widgets(self):
        gf = ttk.LabelFrame(self, text="General Settings")
        gf.pack(fill=tk.X, padx=10, pady=10)
        ttk.Label(gf, text="Prefix:").pack(pady=5)
        self.prefix_entry = ttk.Entry(gf, takefocus=True)
        cp = self.parent.projects.get(self.parent.current_project,{})
        self.prefix_entry.insert(0,cp.get("prefix",""))
        self.prefix_entry.pack(fill=tk.X,padx=10)
        bf = ttk.LabelFrame(self, text="Behavior")
        bf.pack(fill=tk.X, padx=10, pady=10)
        self.respect_var = tk.BooleanVar(value=self.parent.settings.get('respect_gitignore',True))
        ttk.Checkbutton(bf,text="Respect .gitignore",variable=self.respect_var,takefocus=True).pack(pady=5, anchor='w')
        self.reset_scroll_var = tk.BooleanVar(value=self.parent.settings.get('reset_scroll_on_reset',True))
        ttk.Checkbutton(bf, text="Reset project tree scroll on Reset", variable=self.reset_scroll_var, takefocus=True).pack(pady=5, anchor='w')
        ef = ttk.LabelFrame(self, text=".gitignore Ext/Keep Lists")
        ef.pack(fill=tk.X, padx=10, pady=10)
        ttk.Label(ef, text="Extend/Set Further Items Into .gitignore:").pack(pady=5)
        self.extend_text = scrolledtext.ScrolledText(ef, width=60, height=8, takefocus=True)
        self.extend_text.pack(fill=tk.BOTH,padx=10)
        pr = self.parent.projects.get(self.parent.current_project,{})
        lines = []
        for x in pr.get("blacklist",[]): lines.append(x)
        for y in pr.get("keep",[]): lines.append(f"-{y}")
        self.extend_text.insert('1.0',"\n".join(lines))

        gf2 = ttk.LabelFrame(self, text="Global .gitignore Ext/Keep Lists")
        gf2.pack(fill=tk.X, padx=10, pady=10)
        ttk.Label(gf2, text="Globally ignore or keep:").pack(pady=5)
        self.global_extend_text = scrolledtext.ScrolledText(gf2, width=60, height=8, takefocus=True)
        self.global_extend_text.pack(fill=tk.BOTH, padx=10)
        gbl = self.parent.settings.get("global_blacklist", [])
        gkp = self.parent.settings.get("global_keep", [])
        g_lines = []
        for x in gbl: g_lines.append(x)
        for y in gkp: g_lines.append(f"-{y}")
        self.global_extend_text.insert('1.0', "\n".join(g_lines))

        ttk.Separator(self,orient='horizontal').pack(fill=tk.X,padx=10,pady=5)
        ttk.Button(self, text="Save", command=self.save_settings, takefocus=True).pack(pady=5)
    def save_settings(self):
        pr = self.parent.projects[self.parent.current_project]
        pr["prefix"] = self.prefix_entry.get().strip()
        self.parent.settings['respect_gitignore'] = self.respect_var.get()
        self.parent.settings['reset_scroll_on_reset'] = self.reset_scroll_var.get()
        lines = [l.strip() for l in self.extend_text.get('1.0',tk.END).split('\n') if l.strip()]
        exclude, keep = [], []
        for l in lines:
            if l.startswith('-'): keep.append(l[1:].strip())
            else: exclude.append(l.strip())
        pr["blacklist"] = exclude
        pr["keep"] = keep
        glines = [l.strip() for l in self.global_extend_text.get('1.0', tk.END).split('\n') if l.strip()]
        g_exclude, g_keep = [], []
        for l in glines:
            if l.startswith('-'): g_keep.append(l[1:].strip())
            else: g_exclude.append(l.strip())
        self.parent.settings["global_blacklist"] = g_exclude
        self.parent.settings["global_keep"] = g_keep

        self.parent.save_app_projects()
        self.parent.save_app_settings()
        self.destroy()
        self.parent.refresh_files(is_manual=True)

class RawEditDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.title("Raw Edit Templates JSON")
        self.create_widgets()
        apply_modal_geometry(self, parent, "RawEditDialog")
    def create_widgets(self):
        self.text_area = scrolledtext.ScrolledText(self, width=80, height=20, wrap='none')
        self.text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        raw = self.parent.settings.get("global_templates", {})
        j = json.dumps(raw, indent=4)
        self.text_area.insert(tk.END, j)
        bf = ttk.Frame(self)
        bf.pack(pady=5)
        ttk.Button(bf, text="Save", command=self.save_json, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text="Cancel", command=self.destroy, takefocus=True).pack(side=tk.LEFT, padx=5)
    def save_json(self):
        s = self.text_area.get('1.0', tk.END).strip()
        try:
            new_data = json.loads(s)
        except json.JSONDecodeError as e:
            show_error_centered(self, "Invalid JSON", f"Please fix JSON format.\n{e}")
            return

        self.parent.settings["global_templates"] = new_data
        self.parent.parent.save_app_settings()
        self.parent.parent.load_templates(force_refresh=True)
        self.parent.parent.quick_copy_var.set("")
        
        self.parent.destroy()
        self.destroy()

class TemplatesDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__()
        self.title("Manage Templates")
        self.parent = parent
        self.settings = parent.settings
        self.templates = copy.deepcopy(self.settings.get("global_templates", {}))
        self.template_names = sorted(self.templates.keys())
        self.create_widgets()
        apply_modal_geometry(self, parent, "TemplatesDialog")
        self.select_current_template()
    def create_widgets(self):
        top_btn_frame = ttk.Frame(self)
        top_btn_frame.pack(fill=tk.X, padx=5, pady=5)
        raw_all_btn = ttk.Button(top_btn_frame, text="Raw Edit All Templates", command=self.raw_edit_all_templates)
        raw_all_btn.pack(side=tk.RIGHT)
        self.last_selected_index = None
        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        lf = ttk.Frame(main_pane)
        main_pane.add(lf, weight=1)
        self.template_listbox = tk.Listbox(lf, exportselection=False, takefocus=True)
        self.template_listbox.pack(fill=tk.BOTH, expand=True)
        for t in self.template_names: self.template_listbox.insert(tk.END, t)
        self.template_listbox.bind('<<ListboxSelect>>', self.on_template_select, add='+')
        self.template_listbox.bind("<Double-Button-1>", self.on_name_dbl_click)
        self.adjust_listbox_width()
        cf = ttk.Frame(main_pane)
        main_pane.add(cf, weight=3)
        ttk.Label(cf, text="Template Content:").pack(anchor='w')
        self.template_text = scrolledtext.ScrolledText(cf, height=15, takefocus=True)
        self.template_text.pack(fill=tk.BOTH, expand=True, pady=(5,0))
        bf = ttk.Frame(self)
        bf.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(bf, text="Add New", command=self.add_template, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text="Delete", command=self.delete_template, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text="Quick Copy w/Clipboard", command=self.quick_copy_template, takefocus=True).pack(side=tk.LEFT, padx=5)
        
        self.is_default_var = tk.BooleanVar()
        self.default_button = ttk.Checkbutton(bf, text="Set as Default", variable=self.is_default_var, command=self.toggle_default_template, state=tk.DISABLED)
        self.default_button.pack(side=tk.LEFT, padx=15)

        ttk.Button(bf, text="Save and Close", command=self.save_and_close, takefocus=True).pack(side=tk.RIGHT, padx=5)
    def raw_edit_all_templates(self):
        RawEditDialog(self)
    def adjust_listbox_width(self):
        w = 0
        for t in self.template_names: w = max(w,len(t))
        self.template_listbox.config(width=w+2 if w<50 else 50)
    def select_current_template(self):
        ct = self.parent.template_var.get()
        if ct and ct in self.template_names:
            idx = self.template_names.index(ct)
            self.template_listbox.selection_clear(0, tk.END)
            self.template_listbox.selection_set(idx)
            self.template_listbox.activate(idx)
            self.template_listbox.see(idx)
            self.last_selected_index = idx
            self.on_template_select(None)
        elif self.template_listbox.size()>0:
            self.template_listbox.selection_set(0)
            self.on_template_select(None)
    def on_template_select(self, _):
        self.save_current_template_content()
        s = self.template_listbox.curselection()
        if s:
            i = s[0]
            t = self.template_listbox.get(i)
            self.template_text.delete('1.0',tk.END)
            self.template_text.insert(tk.END,self.templates.get(t, ""))
            self.last_selected_index = i
            
            default_tpl = self.settings.get("default_template_name")
            self.is_default_var.set(t == default_tpl)
            self.default_button.config(state=tk.NORMAL)
        else:
            if self.last_selected_index is not None and self.last_selected_index < self.template_listbox.size(): self.template_listbox.selection_set(self.last_selected_index)
            elif self.template_listbox.size()>0:
                self.template_listbox.selection_set(0)
                self.last_selected_index=0
                self.on_template_select(None)
            else:
                self.default_button.config(state=tk.DISABLED)
    def on_name_dbl_click(self, event):
        s = self.template_listbox.curselection()
        if not s: return
        old = self.template_listbox.get(s[0])
        dlg = RenameTemplateDialog(self.parent, old)
        new_name = dlg.new_name
        if new_name is None: return
        if not new_name:
            show_warning_centered(self,"Warning","Template name cannot be empty.")
            return
        if new_name==old: return
        if new_name in self.templates:
            show_error_centered(self,"Error","Template name already exists.")
            return
        self.templates[new_name] = self.templates.pop(old)
        if self.settings.get("default_template_name") == old:
            self.settings["default_template_name"] = new_name
        self.template_names = sorted(self.templates.keys())
        self.refresh_template_list(new_name)
    def refresh_template_list(self, new_selection=None):
        cur_sel_name = new_selection
        if not cur_sel_name:
            cur_sel_idx = self.template_listbox.curselection()
            if cur_sel_idx: cur_sel_name = self.template_listbox.get(cur_sel_idx[0])

        self.template_listbox.delete(0, tk.END)
        for t in self.template_names: self.template_listbox.insert(tk.END, t)
        self.adjust_listbox_width()
        if cur_sel_name and cur_sel_name in self.template_names:
            idx = self.template_names.index(cur_sel_name)
            self.template_listbox.selection_set(idx)
            self.template_listbox.activate(idx)
            self.last_selected_index = idx
        elif self.template_listbox.size()>0:
            self.template_listbox.selection_set(0)
            self.last_selected_index = 0
        self.on_template_select(None)
    def add_template(self):
        n = simpledialog.askstring("Template Name","Enter template name:")
        if n is None: return
        n = n.strip()
        if not n:
            show_warning_centered(self,"Warning","Template name cannot be empty.")
            return
        if n in self.templates:
            show_error_centered(self,"Error","Template name already exists.")
            return
        self.save_current_template_content()
        self.templates[n] = ""
        self.template_names = sorted(self.templates.keys())
        self.refresh_template_list(n)
    def delete_template(self):
        s = self.template_listbox.curselection()
        if s:
            i = s[0]
            t = self.template_listbox.get(i)
            if show_yesno_centered(self,"Delete Template",f"Are you sure you want to delete '{t}'?"):
                del self.templates[t]
                if self.settings.get("default_template_name") == t:
                    self.settings["default_template_name"] = None
                self.template_names = sorted(self.templates.keys())
                self.refresh_template_list()
                self.template_text.delete('1.0',tk.END)
    def quick_copy_template(self):
        s = self.template_listbox.curselection()
        if not s: return
        content = self.template_text.get('1.0', tk.END)
        try: clip_in = self.clipboard_get()
        except: clip_in = ""
        if "{{CLIPBOARD}}" in content: content = content.replace("{{CLIPBOARD}}", clip_in)
        content = content.strip()
        self.clipboard_clear()
        self.clipboard_append(content)
        self.parent.set_status_temporary("Copied to clipboard")
        self.destroy()
    def save_current_template_content(self):
        if self.last_selected_index is not None and self.last_selected_index < len(self.template_names):
            t_name = self.template_names[self.last_selected_index]
            content = self.template_text.get('1.0', tk.END).rstrip('\n')
            if self.templates.get(t_name) != content:
                self.templates[t_name] = content
                return True
        return False
    def toggle_default_template(self):
        s = self.template_listbox.curselection()
        if not s: return
        t_name = self.template_listbox.get(s[0])
        if self.is_default_var.get():
            self.settings["default_template_name"] = t_name
        else:
            if self.settings.get("default_template_name") == t_name:
                self.settings["default_template_name"] = None
    def save_and_close(self):
        self.save_current_template_content()
        self.parent.settings["global_templates"] = self.templates
        self.parent.save_app_settings()
        self.parent.load_templates(force_refresh=True)
        self.destroy()

class TextEditorDialog(tk.Toplevel):
    def __init__(self, parent, initial_text="", opened_file=None):
        super().__init__()
        self.parent = parent
        self.title("Text Editor")
        self.opened_file = opened_file
        self.create_widgets()
        if initial_text: self.text_area.insert(tk.END, initial_text)
        apply_modal_geometry(self, parent, "TextEditorDialog")
    def create_widgets(self):
        bf = ttk.Frame(self)
        bf.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(bf, text='Replace "**', command=self.replace_stars, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text='Remove Duplicates', command=self.remove_duplicates, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text='Sort Alphabetically', command=self.sort_alphabetically, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text='Sort by Length', command=self.sort_by_length, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text='Unescape', command=self.unescape_text, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text='Escape', command=self.escape_text, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text='Copy & Close', command=self.copy_and_close, takefocus=True).pack(side=tk.RIGHT, padx=5)
        nb = ttk.Button(bf, text='Open in Notepad++', command=self.open_in_notepad, takefocus=True)
        nb.pack(side=tk.RIGHT, padx=5)
        self.text_area = scrolledtext.ScrolledText(self, width=80, height=25, wrap='none')
        self.text_area.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def copy_and_close(self):
        self.update_clipboard()
        self.destroy()
    def update_clipboard(self, msg="Copied to clipboard"):
        txt = self.text_area.get('1.0', tk.END).strip()
        self.clipboard_clear()
        self.clipboard_append(txt)
        self.parent.set_status_temporary(msg)
    def replace_stars(self):
        txt = self.text_area.get('1.0', tk.END).replace("**","")
        self.text_area.delete('1.0', tk.END)
        self.text_area.insert(tk.END, txt)
        self.update_clipboard()
        self.destroy()
    def remove_duplicates(self):
        txt = self.text_area.get('1.o', tk.END).rstrip('\n')
        lines = txt.split('\n')
        seen = set()
        out = []
        for line in lines:
            if line not in seen: seen.add(line); out.append(line)
        self.text_area.delete('1.0', tk.END)
        self.text_area.insert(tk.END, '\n'.join(out))
        self.update_clipboard()
        self.destroy()
    def sort_alphabetically(self):
        txt = self.text_area.get('1.0', tk.END).rstrip('\n')
        lines = txt.split('\n')
        lines.sort()
        self.text_area.delete('1.0', tk.END)
        self.text_area.insert(tk.END, '\n'.join(lines))
        self.update_clipboard()
        self.destroy()
    def sort_by_length(self):
        txt = self.text_area.get('1.0', tk.END).rstrip('\n')
        lines = txt.split('\n')
        lines.sort(key=len)
        self.text_area.delete('1.0', tk.END)
        self.text_area.insert(tk.END, '\n'.join(lines))
        self.update_clipboard()
        self.destroy()
    def escape_text(self):
        txt = self.text_area.get('1.0', tk.END).rstrip('\n')
        esc = txt.encode('unicode_escape').decode('ascii', 'ignore')
        self.text_area.delete('1.0', tk.END)
        self.text_area.insert(tk.END, esc)
        self.update_clipboard()
        self.destroy()
    def unescape_text(self):
        txt = self.text_area.get('1.0', tk.END).rstrip('\n')
        try:
            unesc = codecs.decode(txt, 'unicode_escape')
            self.text_area.delete('1.0', tk.END)
            self.text_area.insert(tk.END, unesc)
            self.update_clipboard()
            self.destroy()
        except Exception as e:
            show_error_centered(self, "Unescape Error", f"Failed to unescape text: {e}")
    def open_in_notepad(self):
        content = self.text_area.get('1.0','end-1c')
        content = unify_line_endings(content).rstrip('\n')
        self.parent.save_and_open_notepadpp(content)
        self.destroy()

class HistorySelectionDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__()
        self.title("History Selection")
        apply_modal_geometry(self, parent, "HistorySelectionDialog")
        self.parent = parent
        self.create_widgets()
        self.resizable(True, True)
    def bind_mousewheel_events(self, w):
        w.bind("<MouseWheel>", self.on_mousewheel, add='+')
        w.bind("<Button-4>", self.on_mousewheel, add='+')
        w.bind("<Button-5>", self.on_mousewheel, add='+')
    def pass_event_to_canvas(self, event):
        self.on_mousewheel(event)
        return "break"
    def on_mousewheel(self, event):
        if event.num==4: self.canvas.yview_scroll(-1,"units")
        elif event.num==5: self.canvas.yview_scroll(1,"units")
        else:
            d = int(-1*(event.delta/120)) if platform.system()=='Windows' else int(-1*event.delta)
            self.canvas.yview_scroll(d,"units")
        return "break"
    def create_widgets(self):
        pad_frame = ttk.Frame(self)
        pad_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.canvas = tk.Canvas(pad_frame, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(pad_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.content_frame = ttk.Frame(self.canvas)
        self.canvas_window_id = self.canvas.create_window((0,0), window=self.content_frame, anchor='nw')
        def on_configure_content(event):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            self.canvas.itemconfig(self.canvas_window_id, width=self.canvas.winfo_width())
        self.content_frame.bind("<Configure>", on_configure_content)
        self.bind_mousewheel_events(self.canvas)
        self.bind("<MouseWheel>", self.on_mousewheel, add='+')
        self.bind("<Button-4>", self.on_mousewheel, add='+')
        self.bind("<Button-5>", self.on_mousewheel, add='+')
        self.load_history()
    def load_history(self):
        hs = self.parent.settings.get(HISTORY_SELECTION_KEY, [])
        all_sorted = sorted(hs, key=lambda x: x.get("timestamp",0), reverse=True)[:20]
        for s_obj in all_sorted:
            fr = ttk.Frame(self.content_frame)
            fr.pack(fill=tk.X, expand=True, pady=5)
            proj = s_obj.get("saved_project_name") or s_obj.get("project_name") or s_obj.get("project","(Unknown)")
            dt_str = datetime.fromtimestamp(s_obj["timestamp"]).strftime("%d.%m.%Y %H:%M:%S")
            rel_str = get_relative_time_str(s_obj["timestamp"])
            lbl_txt = f"{proj} | {dt_str} ({rel_str})"
            ttk.Label(fr, text=lbl_txt, style='Info.TLabel').pack(anchor='w')
            lines = s_obj["files"]
            st_height = min(len(lines),10) if lines else 1
            txt = tk.Text(fr, wrap='none', height=st_height)
            txt.pack(fill=tk.X, expand=True, pady=2)
            txt.insert(tk.END, "".join(f"{ff}\n" for ff in lines))
            txt.config(state='disabled')
            txt.bind("<MouseWheel>", self.pass_event_to_canvas, add='+')
            txt.bind("<Button-4>", self.pass_event_to_canvas, add='+')
            txt.bind("<Button-5>", self.pass_event_to_canvas, add='+')
            txt.bind("<Key>", lambda e: "break")
            r_btn = ttk.Button(fr, text="Re-select", command=lambda setdata=s_obj: self.reselect_set(setdata))
            r_btn.pack(fill=tk.X, pady=(1,0))
            missing = any(ff not in self.parent.file_vars for ff in s_obj["files"])
            if missing: r_btn.config(state=tk.DISABLED)
    def reselect_set(self, s_obj):
        self.parent.start_bulk_update_and_reselect(s_obj["files"])
        self.destroy()

class OutputFilesDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__()
        self.title("View Outputs")
        self.parent = parent
        self.files_list = []
        self.create_widgets()
        apply_modal_geometry(self, parent, "OutputFilesDialog")
        self.load_files()
    def create_widgets(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        left_frame = ttk.Frame(pane)
        pane.add(left_frame, weight=1)
        
        cols = ("name", "time", "chars")
        self.tree = ttk.Treeview(left_frame, columns=cols, show='headings', selectmode='browse')
        self.tree.heading("name", text="File Name")
        self.tree.heading("time", text="Generated")
        self.tree.heading("chars", text="Chars", anchor='e')
        self.tree.column("name", width=250, stretch=True)
        self.tree.column("time", width=120, stretch=False)
        self.tree.column("chars", width=80, stretch=False, anchor='e')
        
        ysb = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.tree.yview)
        xsb = ttk.Scrollbar(left_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        
        self.tree.grid(row=0, column=0, sticky='nsew')
        ysb.grid(row=0, column=1, sticky='ns')
        xsb.grid(row=1, column=0, sticky='ew')
        left_frame.grid_rowconfigure(0, weight=1)
        left_frame.grid_columnconfigure(0, weight=1)

        right_frame = ttk.Frame(pane)
        pane.add(right_frame, weight=2)
        
        self.preview_text = scrolledtext.ScrolledText(right_frame, wrap=tk.WORD, state='disabled')
        self.preview_text.pack(fill=tk.BOTH, expand=True)
        
        self.tree.bind("<<TreeviewSelect>>", self.on_file_select)
        self.tree.bind("<Double-1>", self.on_file_double_click)
    def load_files(self):
        op_dir = OUTPUT_DIR
        if not os.path.isdir(op_dir): return
        
        files_with_meta = []
        for f in os.listdir(op_dir):
            fp = os.path.join(op_dir, f)
            if os.path.isfile(fp):
                try:
                    mtime = os.path.getmtime(fp)
                    content = safe_read_file(fp)
                    char_count = len(content)
                    files_with_meta.append((f, mtime, char_count, fp))
                except OSError:
                    continue
        
        files_with_meta.sort(key=lambda x: x[1], reverse=True)
        
        self.files_list = [item[3] for item in files_with_meta]
        for f, mtime, char_count, _ in files_with_meta:
            rt = get_relative_time_str(mtime)
            self.tree.insert("", tk.END, values=(f, rt, format_german_thousand_sep(char_count)))
    def on_file_select(self, event):
        sel = self.tree.selection()
        if not sel: return
        
        idx = self.tree.index(sel[0])
        if idx >= len(self.files_list): return
        
        fp = self.files_list[idx]
        try:
            txt = safe_read_file(fp)
            self.preview_text.config(state='normal')
            self.preview_text.delete('1.0', tk.END)
            self.preview_text.insert('1.0', txt)
            self.preview_text.config(state='disabled')
        except Exception as e:
            self.preview_text.config(state='normal')
            self.preview_text.delete('1.0', tk.END)
            self.preview_text.insert('1.0', f"Error reading file:\n\n{e}")
            self.preview_text.config(state='disabled')
    def on_file_double_click(self, event):
        sel = self.tree.selection()
        if not sel: return
        
        idx = self.tree.index(sel[0])
        if idx >= len(self.files_list): return
        
        fp = self.files_list[idx]
        txt = safe_read_file(fp)
        self.destroy()
        TextEditorDialog(self.parent, initial_text=txt, opened_file=fp)

class CodePromptGeneratorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Code Prompt Generator - PID: {os.getpid()}")
        self.style = ttk.Style(self)
        try:
            self.style.theme_use('vista')
        except tk.TclError:
            try:
                available_themes = self.style.theme_names()
                if available_themes: self.style.theme_use(available_themes[0])
                else: logger.warning("No ttk themes available for fallback.")
            except Exception as e:
                logger.warning("Failed to set a fallback theme: %s", e)
        self.style.configure('.', font=('Segoe UI', 10), background='#F3F3F3')
        self.style.configure('TFrame', background='#F3F3F3')
        self.style.configure('TLabel', background='#F3F3F3', foreground='#1E1E1E')
        self.style.configure('TCheckbutton', background='#F3F3F3', foreground='#1E1E1E')
        self.style.configure('Modern.TCheckbutton', background='#F3F3F3')
        self.style.configure('ProjectOps.TLabelframe', background='#F3F3F3', padding=10, foreground='#444444')
        self.style.configure('TemplateOps.TLabelframe', background='#F3F3F3', padding=10, foreground='#444444')
        self.style.configure('FilesFrame.TLabelframe', background='#F3F3F3', padding=10, foreground='#444444')
        self.style.configure('TButton', foreground='black', background='#F0F0F0', padding=6, font=('Segoe UI',10,'normal'))
        self.style.map('TButton', foreground=[('disabled','#7A7A7A'),('active','black')], background=[('active','#E0E0E0'),('disabled','#F0F0F0')])
        self.style.configure('Warning.TLabel', foreground='#AA6000')
        self.style.configure('Error.TLabel', foreground='#AA0000')
        self.style.configure('Info.TLabel', foreground='#0066AA')
        self.style.configure('RemoveFile.TButton', anchor='center', padding=(2,1))
        self.icon_path = resource_path('app_icon.ico')
        if os.path.exists(self.icon_path):
            try:
                self.iconbitmap(self.icon_path)
            except tk.TclError:
                logger.warning("Could not set .ico file, format may not be supported on this platform.")
        
        self.queue = queue.Queue()
        self.projects = load_projects(self.queue)
        if self.projects is None:
            show_error_centered(None, "Fatal Error", "Could not load projects.json due to a file lock.\nPlease close other running instances and try again.")
            sys.exit(1)
        self.settings = load_settings(self.queue)
        if self.settings is None:
            show_error_centered(None, "Fatal Error", "Could not load settings.json due to a file lock.\nPlease close other running instances and try again.")
            sys.exit(1)

        self.settings.setdefault('respect_gitignore',True)
        self.settings.setdefault("global_templates", {})
        self.settings.setdefault('reset_scroll_on_reset', True)
        self.settings.setdefault("global_blacklist", [])
        self.settings.setdefault("global_keep", [])
        self.settings.setdefault("default_template_name", None)
        if not self.settings["global_templates"]:
            self.settings["global_templates"]["Default"] = "Your task is to\n\n{{dirs}}{{files_provided}}{{file_contents}}"
            self.save_app_settings()

        self.gitignore_skipped = []
        self.current_project = None
        self.blacklist = []
        self.templates = {}
        self.file_vars = {}
        self.file_hashes = {}
        self.file_contents = {}
        self.all_items = []
        self.filtered_items = []
        self.click_counts = {}
        self.previous_check_states = {}
        self.file_char_counts = {}
        self.file_labels = {}
        self.all_files_count = 0
        self.settings_dialog = None
        self.precompute_thread = None
        self.precompute_lock = threading.Lock()
        self.data_lock = threading.Lock()
        self.precompute_request = threading.Event()
        self.precomputed_prompt_cache = {}
        self.row_frames = {}
        self.bulk_update_active = False
        self.checkbox_toggle_timer = None
        self.loading_thread = None
        self.autoblacklist_thread = None
        self.reset_button_clicked = False
        self.is_silent_refresh = False
        self.project_tree_scroll_pos = 0.0
        self.search_debounce_timer = None
        self.scroll_restore_job = None
        
        self.create_layout()
        self.after(50, self.process_queue)
        lp = self.settings.get('last_selected_project')
        if lp and lp in self.projects: self.project_var.set(lp); self.load_project(lp)
        self.restore_window_geometry()
        
        self.baseline_projects = copy.deepcopy(self.projects)
        self.baseline_settings = copy.deepcopy(self.settings)
        
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.last_projects_mtime = os.path.getmtime(PROJECTS_FILE) if os.path.exists(PROJECTS_FILE) else 0
        self.last_settings_mtime = os.path.getmtime(SETTINGS_FILE) if os.path.exists(SETTINGS_FILE) else 0
        self.watch_file_changes()
        self.start_precompute_worker()
    def schedule_scroll_restore(self, pos):
        if self.scroll_restore_job:
            self.after_cancel(self.scroll_restore_job)
        self.scroll_restore_job = self.after(
            50,
            lambda p=pos: (self.files_canvas.yview_moveto(p),
                           setattr(self, "scroll_restore_job", None))
        )
    def save_app_settings(self):
        save_settings(self.settings, self.queue)
    def save_app_projects(self):
        save_projects(self.projects, self.queue)
    from contextlib import contextmanager
    @contextmanager
    def bulk_update_mode(self):
        self.bulk_update_active = True
        try: yield
        finally:
            self.bulk_update_active = False
            self.on_file_selection_changed()
    def create_layout(self):
        self.top_frame = ttk.Frame(self)
        self.top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)
        self.create_top_widgets(self.top_frame)
        self.file_frame = ttk.LabelFrame(self, text="Project Files", style='FilesFrame.TLabelframe')
        self.file_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(5,0))
        self.create_file_widgets(self.file_frame)
        self.control_frame = ttk.Frame(self)
        self.control_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=5)
        self.create_bottom_widgets(self.control_frame)
    def create_top_widgets(self, c):
        pa = ttk.LabelFrame(c, text="Project Operations", style='ProjectOps.TLabelframe')
        pa.pack(side=tk.LEFT, fill=tk.Y, padx=(0,5))
        ttk.Label(pa, text="Select Project:").pack(anchor='w', pady=(0,2))
        self.project_var = tk.StringVar()
        cb = ttk.Combobox(pa, textvariable=self.project_var, state='readonly', width=20, takefocus=True)
        cb.pack(anchor='w', pady=(0,5))
        cb.bind("<<ComboboxSelected>>", self.on_project_selected)
        self.sort_and_set_projects(cb)
        of = ttk.Frame(pa)
        of.pack(anchor='w', pady=(5,0))
        ttk.Button(of, text="Add Project", command=self.add_project, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(of, text="Remove Project", command=self.remove_project, takefocus=True).pack(side=tk.LEFT, padx=5)
        spacer = ttk.Frame(c)
        spacer.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tf = ttk.LabelFrame(c, text="Template", style='TemplateOps.TLabelframe')
        tf.pack(side=tk.RIGHT, fill=tk.Y)
        
        template_frame_inner = ttk.Frame(tf)
        template_frame_inner.pack(anchor='w')
        ttk.Label(template_frame_inner, text="Select Template:").pack(anchor='w', pady=(0,2))
        self.template_var = tk.StringVar()
        self.template_var.trace_add('write', lambda *a: self.request_precomputation())
        td = ttk.Combobox(template_frame_inner, textvariable=self.template_var, state='readonly', width=20, takefocus=True)
        td.pack(anchor='w', pady=(0,5))
        td.bind("<<ComboboxSelected>>", self.on_template_selected)
        
        template_buttons_frame = ttk.Frame(tf)
        template_buttons_frame.pack(anchor='w', pady=5)
        self.manage_templates_btn = ttk.Button(template_buttons_frame, text="Manage Templates", command=self.manage_templates, takefocus=True)
        self.manage_templates_btn.pack(side=tk.LEFT, padx=(0,5))
        self.reset_template_btn = ttk.Button(template_buttons_frame, text="Reset to Default", command=self.reset_template_to_default, takefocus=True)
        self.reset_template_btn.pack(side=tk.LEFT)
        self.reset_template_btn.config(state=tk.DISABLED)

        qf = ttk.LabelFrame(c, text="Quick Copy w/Clipboard", style='TemplateOps.TLabelframe')
        qf.pack(side=tk.RIGHT, fill=tk.Y, padx=(5,5))
        self.quick_copy_var = tk.StringVar()
        self.quick_copy_dropdown = ttk.Combobox(qf, textvariable=self.quick_copy_var, state='readonly', width=20, takefocus=True)
        self.quick_copy_dropdown.pack(anchor='w', pady=(0,5))
        self.quick_copy_dropdown.bind("<<ComboboxSelected>>", self.on_quick_copy_selected)
        self.project_dropdown = cb
        self.template_dropdown = td
    def set_status_temporary(self, msg, duration=2000):
        self.status_label.config(text=msg)
        self.after(duration, lambda: self.status_label.config(text="Ready"))
    def on_quick_copy_selected(self, _):
        val = self.quick_copy_var.get()
        if not val or val.startswith("-- "):
            self.quick_copy_dropdown.set("")
            return
        try: clip_in = self.clipboard_get()
        except: clip_in = ""
        if val in self.templates and "{{CLIPBOARD}}" in self.templates[val]:
            content = self.templates[val].replace("{{CLIPBOARD}}", clip_in).strip()
            self.clipboard_clear()
            self.clipboard_append(content)
            self.set_status_temporary("Copied to clipboard")
            self.quick_copy_dropdown.set("")
            return
        new_clip = clip_in
        if val=="Replace \"**\"": new_clip = new_clip.replace("**","")
        elif val=="Remove Duplicates":
            lines = new_clip.rstrip('\n').split('\n')
            seen, out = set(), []
            for line in lines:
                if line not in seen: seen.add(line); out.append(line)
            new_clip = "\n".join(out)
        elif val=="Sort Alphabetically":
            lines = new_clip.rstrip('\n').split('\n')
            lines.sort()
            new_clip = "\n".join(lines)
        elif val=="Sort by Length":
            lines = new_clip.rstrip('\n').split('\n')
            lines.sort(key=len)
            new_clip = "\n".join(lines)
        elif val=="Escape Text":
            new_clip = new_clip.rstrip('\n').encode('unicode_escape').decode('ascii','ignore')
        elif val=="Unescape Text":
            try: new_clip = codecs.decode(new_clip.rstrip('\n'), 'unicode_escape')
            except: self.set_status_temporary("Unescape failed!", 3000); return
        new_clip = new_clip.strip()
        self.clipboard_clear()
        self.clipboard_append(new_clip)
        self.set_status_temporary("Clipboard updated")
        self.quick_copy_dropdown.set("")
    def create_file_widgets(self, c):
        sf = ttk.Frame(c)
        sf.pack(anchor='w', padx=5, pady=(5,2))
        ttk.Label(sf, text="Search:").pack(side=tk.LEFT, padx=(0,5))
        self.file_search_var = tk.StringVar()
        self.file_search_var.trace_add("write", self.on_search_changed)
        se = ttk.Entry(sf, textvariable=self.file_search_var, width=25, takefocus=True)
        se.pack(side=tk.LEFT)
        csb = ttk.Button(sf, text="✕", command=lambda: self.file_search_var.set(""))
        csb.pack(side=tk.LEFT, padx=(5,0))
        csb.configure(style='Toolbutton')
        tf = ttk.Frame(c)
        tf.pack(anchor='w', padx=5, pady=(5,2))
        self.select_all_button = ttk.Button(tf, text="Select All", command=self.toggle_select_all, takefocus=True)
        self.select_all_button.pack(side=tk.LEFT, padx=5)
        self.reset_button = ttk.Button(tf, text="Reset", command=self.reset_selection, takefocus=True)
        self.reset_button.pack(side=tk.LEFT, padx=5)
        self.history_button = ttk.Button(tf, text="History Selection", command=self.open_history_selection, takefocus=True)
        self.history_button.pack(side=tk.RIGHT, padx=5)
        self.file_selected_label = ttk.Label(tf, text="Files selected: 0 / 0 (Chars: 0)", width=45)
        self.file_selected_label.pack(side=tk.LEFT, padx=(10,0))
        self.view_outputs_button = ttk.Button(tf, text="View Outputs", command=self.open_output_files, takefocus=True)
        self.view_outputs_button.pack(side=tk.RIGHT, padx=5)
        mf = ttk.Frame(c)
        mf.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.files_text_container = ttk.Frame(mf)
        self.files_text_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.files_canvas = tk.Canvas(self.files_text_container, highlightthickness=0, background='#F3F3F3')
        self.files_scrollbar = ttk.Scrollbar(self.files_text_container, orient="vertical", command=self.files_canvas.yview)
        self.files_canvas.configure(yscrollcommand=self.files_scrollbar.set)
        self.inner_frame = ttk.Frame(self.files_canvas)
        self.inner_frame.bind("<Configure>", lambda e: self.files_canvas.configure(scrollregion=self.files_canvas.bbox("all")))
        self.files_canvas.create_window((0,0), window=self.inner_frame, anchor='nw')
        self.files_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.files_scrollbar.pack(side=tk.LEFT, fill=tk.Y)
        self.bind_mousewheel_events(self.files_canvas)
        self.selected_files_container = ttk.Frame(mf)
        self.selected_files_container.pack(side=tk.RIGHT, fill=tk.Y, padx=(5,0))
        self.selected_files_container.config(width=300)
        self.selected_files_container.pack_propagate(False)
        ttk.Label(self.selected_files_container, text="Selected Files:").pack(anchor='nw')
        self.selected_files_canvas = tk.Canvas(self.selected_files_container, highlightthickness=0, background='#F3F3F3')
        self.selected_files_scrollbar = ttk.Scrollbar(self.selected_files_container, orient="vertical", command=self.selected_files_canvas.yview)
        self.selected_files_canvas.configure(yscrollcommand=self.selected_files_scrollbar.set)
        self.selected_files_inner = ttk.Frame(self.selected_files_canvas)
        self.selected_files_inner.bind("<Configure>", lambda e: self.selected_files_canvas.configure(scrollregion=self.selected_files_canvas.bbox("all")))
        self.selected_files_canvas.create_window((0,0), window=self.selected_files_inner, anchor='nw')
        self.selected_files_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.selected_files_scrollbar.pack(side=tk.LEFT, fill=tk.Y)
        self.bind_mousewheel_events(self.selected_files_canvas)
    def bind_mousewheel_events(self, w):
        w.bind("<MouseWheel>", self.on_files_mousewheel, add='+')
        w.bind("<Button-4>", self.on_files_mousewheel, add='+')
        w.bind("<Button-5>", self.on_files_mousewheel, add='+')
    def create_bottom_widgets(self, c):
        gen_frame = ttk.Frame(c)
        gen_frame.pack(side=tk.LEFT, padx=5)
        self.generate_button = ttk.Button(gen_frame, text="Generate", width=12, command=self.generate_output, takefocus=True)
        self.generate_button.pack(side=tk.LEFT)
        self.generate_menu_button = ttk.Button(gen_frame, text="▼", width=2, command=self.show_quick_generate_menu)
        self.generate_menu_button.pack(side=tk.LEFT)

        self.refresh_button = ttk.Button(c, text="Refresh Files", width=12, command=lambda: self.refresh_files(is_manual=True), takefocus=True)
        self.refresh_button.pack(side=tk.LEFT, padx=5)
        self.settings_button = ttk.Button(c, text="Settings", command=self.open_settings, takefocus=True)
        self.settings_button.pack(side=tk.RIGHT, padx=5)
        self.text_editor_button = ttk.Button(c, text="Open Text Editor", command=self.open_text_editor, takefocus=True)
        self.text_editor_button.pack(side=tk.RIGHT, padx=5)
        self.status_label = ttk.Label(c, text="Ready")
        self.status_label.pack(side=tk.RIGHT, padx=5)
    def on_files_mousewheel(self, event):
        target_canvas = None
        w = event.widget
        while w is not None:
            if w == self.files_canvas:
                target_canvas = self.files_canvas
                break
            if w == self.selected_files_canvas:
                target_canvas = self.selected_files_canvas
                break
            w = w.master
        
        if target_canvas:
            if event.num==4: target_canvas.yview_scroll(-1,"units")
            elif event.num==5: target_canvas.yview_scroll(1,"units")
            else:
                d = int(-1*(event.delta/120)) if platform.system()=='Windows' else int(-1*event.delta)
                target_canvas.yview_scroll(d,"units")
        return "break"
    def restore_window_geometry(self):
        g = self.settings.get('window_geometry')
        if g: self.geometry(g)
        else: self.geometry("1000x700")
    def on_closing(self):
        has_unsaved_changes = (self.projects != self.baseline_projects or self.settings != self.baseline_settings)
        if has_unsaved_changes:
            result = show_yesnocancel_centered(self, "Unsaved Changes",
                                              "You have unsaved changes. Do you want to save before closing?",
                                              yes_text="Save", no_text="Don't Save", cancel_text="Cancel")
            if result == "yes":
                self.settings['window_geometry'] = self.geometry()
                self.save_app_settings()
                self.save_app_projects()
                self.destroy()
            elif result == "no":
                self.destroy()
            else: # "cancel"
                return
        else:
            current_geom = self.geometry()
            if self.settings.get('window_geometry') != current_geom:
                self.settings['window_geometry'] = current_geom
                self.save_app_settings()
            self.destroy()
    def add_project(self):
        dp = filedialog.askdirectory(title="Select Project Directory")
        if not dp: return
        n = os.path.basename(dp)
        if not n.strip():
            show_warning_centered(self,"Invalid Name","Cannot create a project with an empty name.")
            return
        if n in self.projects:
            show_error_centered(self,"Error",f"Project '{n}' already exists.")
            return
        self.projects[n] = {"path":dp,"last_files":[],"blacklist":[],"keep":[],"prefix":"","click_counts":{}, "last_usage":time.time(),"usage_count":1}
        self.save_app_projects()
        self.sort_and_set_projects(self.project_dropdown)
        self.project_var.set(n) # Directly set the string value
        self.load_project(n, is_new_project=True)
    def remove_project(self):
        disp = self.project_var.get()
        p = disp.split(' (')[0] if ' (' in disp else disp
        if not p:
            show_warning_centered(self,"No Project Selected","Please select a project to remove.")
            return
        if p not in self.projects:
            show_warning_centered(self,"Invalid Selection","Project not found.")
            return
        if show_yesno_centered(self,"Remove Project",f"Are you sure you want to remove the project '{p}'?\nThis action is irreversible."):
            if p in self.projects: del self.projects[p]
            self.save_app_projects()
            if self.settings.get('last_selected_project')==p:
                del self.settings['last_selected_project']
                self.save_app_settings()
            
            if self.current_project==p: self.current_project=None
            self.sort_and_set_projects(self.project_dropdown)
            
            all_projs = self.project_dropdown['values']
            if all_projs:
                self.project_var.set(all_projs[0])
                self.load_project(all_projs[0].split(' (')[0])
            else:
                self.project_var.set("")
                self.clear_project_view()
    def clear_project_view(self):
        self.all_items.clear()
        self.filtered_items.clear()
        with self.data_lock:
            self.file_vars.clear()
            self.file_hashes.clear()
            self.file_contents.clear()
            self.file_char_counts.clear()
        for w in self.inner_frame.winfo_children(): w.destroy()
        self.on_file_selection_changed()
    def on_project_selected(self, _):
        disp = self.project_var.get()
        n = disp.split(' (')[0] if ' (' in disp else disp
        self.load_project(n)
    def load_project(self, n, is_new_project=False):
        self.current_project = n
        self.settings['last_selected_project'] = n
        self.save_app_settings()
        p = self.projects[n]
        self.blacklist = p.get("blacklist",[])
        self.click_counts = p.get("click_counts",{})
        self.run_autoblacklist_in_background(n)
        self.load_templates(force_refresh=True)
        self.load_items_in_background(is_new_project=is_new_project)
    def load_templates(self, *, force_refresh=False):
        self.templates = self.settings.get("global_templates", {})
        
        default_name = self.settings.get("default_template_name")
        if default_name and default_name not in self.templates:
            self.settings["default_template_name"] = None
            self.save_app_settings()

        all_template_names = sorted(self.templates.keys())
        display_templates = [name for name in all_template_names if "{{CLIPBOARD}}" not in self.templates.get(name, "")]
        
        if not force_refresh and list(self.template_dropdown['values']) == display_templates:
            return

        self.template_dropdown['values'] = display_templates
        if display_templates:
            self.template_dropdown.config(height=min(len(display_templates), 15), width=max(max((len(x) for x in display_templates), default=0)+2, 20))
        
        quick_copy_templates = [name for name in all_template_names if "{{CLIPBOARD}}" in self.templates.get(name, "")]
        editor_tools = ["Replace \"**\"","Remove Duplicates","Sort Alphabetically","Sort by Length","Escape Text","Unescape Text"]
        qc_menu = []
        if quick_copy_templates: qc_menu.extend(["-- Template Content --"] + quick_copy_templates)
        if editor_tools: qc_menu.extend(["-- Text Editor Tools --"] + editor_tools)
        self.quick_copy_dropdown.config(values=qc_menu, height=min(len(qc_menu), 15))
        if qc_menu:
            self.quick_copy_dropdown.config(width=max(max((len(x) for x in qc_menu), default=0)+2, 20))
        self.quick_copy_var.set("")
        
        p = self.projects.get(self.current_project, {})
        last_selected_template = p.get("last_template", "")
        if last_selected_template in display_templates:
            self.template_var.set(last_selected_template)
        elif display_templates:
            self.template_var.set(display_templates[0])
        else:
            self.template_var.set("")
        
        self.update_default_template_button()
        self.on_template_selected(None)
    def update_default_template_button(self):
        if self.settings.get("default_template_name"):
            self.reset_template_btn.config(state=tk.NORMAL)
        else:
            self.reset_template_btn.config(state=tk.DISABLED)
    def reset_template_to_default(self):
        default_name = self.settings.get("default_template_name")
        if default_name and default_name in self.template_dropdown['values']:
            self.template_var.set(default_name)
            self.on_template_selected(None)
    def on_template_selected(self, _):
        if self.current_project:
            self.projects[self.current_project]["last_template"]=self.template_var.get()
            self.save_app_projects()
    def load_items_in_background(self, is_new_project=False, is_silent=False):
        if self.loading_thread and self.loading_thread.is_alive(): return
        self.status_label.config(text="Loading...")
        self.is_silent_refresh = is_silent
        if is_new_project: self.project_tree_scroll_pos = 0.0
        self.loading_thread = threading.Thread(target=self._load_items_worker, args=(is_new_project,), daemon=True)
        self.loading_thread.start()
    def _load_items_worker(self, is_new_project):
        if not self.current_project: return
        p = self.projects[self.current_project]
        pt = p["path"]
        if not os.path.isdir(pt):
            self.queue.put(('load_items_done', ("error",None,is_new_project)))
            return
        
        project_bl = p.get("blacklist",[])
        global_bl = self.settings.get("global_blacklist",[])
        combined_bl = list(set(project_bl + global_bl))
        project_kp = p.get("keep",[])
        global_kp = self.settings.get("global_keep",[])
        combined_kp = list(set(project_kp + global_kp))
        
        fi, fc, fe = [], 0, False
        bl_lower = [b.strip().lower().replace("\\", "/") for b in combined_bl]
        gp, gk = [], combined_kp
        if self.settings.get('respect_gitignore',True):
            gi = os.path.join(pt,'.gitignore')
            if os.path.isfile(gi): gp = parse_gitignore(gi)
        
        for r, ds, fs in os.walk(pt, topdown=True):
            if fc>=MAX_FILES: fe=True; break
            
            rr = os.path.relpath(r,pt).replace("\\","/")
            if rr == ".": rr = ""

            orig_ds = list(ds)
            ds[:] = []
            for d in sorted(orig_ds):
                dr = f"{rr}/{d}".lstrip("/").lower()
                is_ignored = path_should_be_ignored(dr, self.settings.get('respect_gitignore', True), gp, gk, bl_lower)
                if not is_ignored or is_dir_forced_kept(dr, gk):
                    ds.append(d)

            if rr: fi.append({"type":"dir","path":rr+"/","level":rr.count('/')})
            
            for f in sorted(fs):
                if fc>=MAX_FILES: fe=True; break
                relp = f"{rr}/{f}".lstrip("/")
                if not path_should_be_ignored(relp.lower(), self.settings.get('respect_gitignore',True), gp, gk, bl_lower):
                    ap = os.path.join(r,f)
                    if os.path.isfile(ap):
                        fi.append({"type":"file","path":relp,"level":relp.count('/')})
                        fc+=1
            if fe: break
        self.queue.put(('load_items_done', ("ok",(fi,fe,[]), is_new_project)))
    def load_items_result(self, data, is_new_project):
        with self.data_lock:
            self.file_contents.clear()
            self.file_char_counts.clear()
            self.file_hashes.clear()
            self.file_vars.clear()

        p = self.projects[self.current_project]
        self.all_items = data[0]
        if data[1]: show_warning_centered(self,"File Limit Exceeded",f"Too many files in the project. Only the first {MAX_FILES} files are loaded.")
        
        lf = p.get("last_files",[]) if not is_new_project else []
        if is_new_project: p["last_files"] = []
        
        self.file_labels.clear()
        self.row_frames.clear()
        self.all_files_count = sum(1 for it in self.all_items if it["type"]=="file")
        
        with self.data_lock:
            for it in self.all_items:
                if it["type"]=="file":
                    self.file_vars[it["path"]] = tk.BooleanVar(value=(it["path"] in lf))
                    self.previous_check_states[it["path"]] = self.file_vars[it["path"]].get()
        
        for path_var in self.file_vars:
            self.file_vars[path_var].trace_add('write', lambda *a, pv=path_var: self.on_checkbox_toggled(pv))
        
        self.filter_and_display_items()
        threading.Thread(target=self._load_file_contents_worker, daemon=True).start()
    def _load_file_contents_worker(self):
        if not self.current_project: return
        p = self.projects[self.current_project]
        pt = p["path"]
        
        files_to_load = [item["path"] for item in self.all_items if item["type"] == "file"]
        
        with self.data_lock:
            for rp in files_to_load:
                ap = os.path.join(pt, rp)
                if os.path.isfile(ap):
                    try:
                        fsize = os.path.getsize(ap)
                        self.file_char_counts[rp] = fsize
                        if fsize > MAX_FILE_SIZE:
                            self.file_contents[rp] = None 
                        else:
                            if rp not in self.file_contents:
                                self.file_contents[rp] = "" 
                    except OSError:
                        self.file_contents[rp], self.file_char_counts[rp] = None, 0

        self.queue.put(('file_contents_loaded', self.current_project))
    def check_and_auto_blacklist(self, pn, th=50):
        pr = self.projects[pn]
        pt = pr["path"]
        if not os.path.isdir(pt): return []
        exbl = pr.get("blacklist",[])
        glbl = self.settings.get("global_blacklist",[])
        cbl = exbl + glbl
        gp, gk = [], pr.get("keep",[]) + self.settings.get("global_keep",[])
        if self.settings.get('respect_gitignore',True):
            gi = os.path.join(pt,'.gitignore')
            if os.path.isfile(gi): gp = parse_gitignore(gi)
        new_blacklisted = []
        for r,ds,fs in os.walk(pt):
            ds.sort(); fs.sort()
            rr = os.path.relpath(r,pt).replace("\\","/").strip("/")
            if any(bb.lower() in rr.lower() for bb in cbl if rr): continue
            ff=[]
            for f in fs:
                rp = f"{rr}/{f}".strip("/").lower()
                if match_any_gitignore(rp,gp) and not match_any_keep(rp,gk): continue
                ff.append(f)
            if len(ff)>th and rr and rr.lower() not in [b.lower() for b in cbl]:
                new_blacklisted.append(rr)
        return new_blacklisted
    def run_autoblacklist_in_background(self, n):
        if self.autoblacklist_thread and self.autoblacklist_thread.is_alive(): return
        self.autoblacklist_thread = threading.Thread(target=self._auto_blacklist_worker, args=(n,), daemon=True)
        self.autoblacklist_thread.start()
    def _auto_blacklist_worker(self, n):
        na = self.check_and_auto_blacklist(n)
        if na: self.queue.put(('auto_bl',(n,na)))
    def on_auto_blacklist_done(self, n, dirs):
        pr = self.projects[n]
        pr["blacklist"]+=dirs
        pr["blacklist"] = list(dict.fromkeys(pr["blacklist"]))
        self.save_app_projects()
        if self.current_project==n: show_info_centered(self,"Auto-Blacklisted",f"These directories exceeded 50 files and were blacklisted:\n\n{', '.join(dirs)}")
    def on_search_changed(self, *args):
        if self.search_debounce_timer:
            self.after_cancel(self.search_debounce_timer)
        self.search_debounce_timer = self.after(200, self.filter_and_display_items)
    def filter_and_display_items(self, scroll_to_top=False):
        for w in self.inner_frame.winfo_children(): w.destroy()
        q = self.file_search_var.get().strip().lower()
        self.filtered_items = [it for it in self.all_items if q in it["path"].lower()] if q else self.all_items
        with self.data_lock:
            for it in self.filtered_items:
                if it["type"]=="dir":
                    rf = tk.Frame(self.inner_frame, bg='#F3F3F3')
                    rf.pack(fill=tk.X,anchor='w')
                    self.bind_mousewheel_events(rf)
                    indent = (4 + it["level"]*10, 2)
                    lbl = tk.Label(rf, text=f"{os.path.basename(it['path'].rstrip('/'))}/", bg='#F3F3F3', fg='#0066AA')
                    lbl.pack(side=tk.LEFT, padx=indent)
                    lbl.bind("<MouseWheel>", self.on_files_mousewheel, add='+')
                    lbl.bind("<Button-4>", self.on_files_mousewheel, add='+')
                    lbl.bind("<Button-5>", self.on_files_mousewheel, add='+')
                else:
                    p = it["path"]
                    rf = tk.Frame(self.inner_frame)
                    rf.pack(fill=tk.X,anchor='w')
                    self.bind_mousewheel_events(rf)
                    self.row_frames[p] = rf
                    self.update_row_color(p)
                    indent = (4 + it["level"]*10, 2)
                    chk = ttk.Checkbutton(rf, variable=self.file_vars.get(p), style='Modern.TCheckbutton')
                    chk.pack(side=tk.LEFT, padx=indent)
                    chk.bind("<MouseWheel>", self.on_files_mousewheel, add='+')
                    chk.bind("<Button-4>", self.on_files_mousewheel, add='+')
                    chk.bind("<Button-5>", self.on_files_mousewheel, add='+')
                    cnt = format_german_thousand_sep(self.file_char_counts.get(p,0))
                    lbl = tk.Label(rf, text=f"{os.path.basename(p)} [{cnt}]", bg=rf["bg"])
                    lbl.pack(side=tk.LEFT, padx=2)
                    lbl.bind("<Button-1>", lambda e, x=p: self.file_vars[x].set(not self.file_vars[x].get()))
                    lbl.bind("<MouseWheel>", self.on_files_mousewheel, add='+')
                    lbl.bind("<Button-4>", self.on_files_mousewheel, add='+')
                    lbl.bind("<Button-5>", self.on_files_mousewheel, add='+')
                    self.file_labels[p] = lbl
        self.on_file_selection_changed()
        
        if scroll_to_top or (self.reset_button_clicked and self.settings.get('reset_scroll_on_reset', True)):
            self.schedule_scroll_restore(0.0)
        else:
            self.schedule_scroll_restore(self.project_tree_scroll_pos)

        self.reset_button_clicked = False
        self.is_silent_refresh = False
    def on_checkbox_toggled(self, f):
        if self.bulk_update_active:
            self.previous_check_states[f] = self.file_vars[f].get()
            return
        old_val = self.previous_check_states.get(f,False)
        new_val = self.file_vars[f].get()
        if not old_val and new_val:
            self.click_counts[f] = min(self.click_counts.get(f,0)+1,100)
            if self.current_project:
                self.projects[self.current_project]['click_counts'] = self.click_counts
                self.save_app_projects()
        self.previous_check_states[f] = new_val
        self.update_row_color(f)
        if self.checkbox_toggle_timer: self.after_cancel(self.checkbox_toggle_timer)
        self.checkbox_toggle_timer = self.after(10, self._delayed_on_checkbox_toggled)
    def _delayed_on_checkbox_toggled(self):
        self.checkbox_toggle_timer = None
        self.on_file_selection_changed()
    def update_row_color(self, p):
        c = self.click_counts.get(p,0)
        ratio = min(c/100, 1.0)
        start_color = (243,243,243)
        end_color = (206,230,255)
        nr = int(start_color[0] + (end_color[0]-start_color[0])*ratio)
        ng = int(start_color[1] + (end_color[1]-start_color[1])*ratio)
        nb = int(start_color[2] + (end_color[2]-start_color[2])*ratio)
        hexcolor = f"#{nr:02x}{ng:02x}{nb:02x}"
        if p in self.row_frames:
            self.row_frames[p].config(bg=hexcolor)
            for w in self.row_frames[p].winfo_children():
                if isinstance(w, tk.Label): w.config(bg=hexcolor)
    def reset_selection(self):
        self.reset_button_clicked = True
        self.project_tree_scroll_pos = (
            0.0 if self.settings.get('reset_scroll_on_reset', True)
            else (self.files_canvas.yview()[0] if self.files_canvas.winfo_height() > 1 else 0.0)
        )
        self.file_search_var.set("")
        self.start_bulk_update_and_reselect([])
    def start_bulk_update_and_reselect(self, files_to_select):
        self.bulk_update_active = True
        self._bulk_update_list = list(self.file_vars.keys())
        self._bulk_update_selection = set(files_to_select)
        self._bulk_update_index = 0
        self._bulk_update_chunk_size = 100
        self.after(1, self._bulk_update_next_chunk)
    def _bulk_update_next_chunk(self):
        if self._bulk_update_index >= len(self._bulk_update_list):
            self.bulk_update_active = False
            self.on_file_selection_changed()
            if self.reset_button_clicked: self.filter_and_display_items()
            return

        end = min(self._bulk_update_index + self._bulk_update_chunk_size, len(self._bulk_update_list))
        for f in self._bulk_update_list[self._bulk_update_index:end]:
            self.file_vars[f].set(f in self._bulk_update_selection)
        
        self._bulk_update_index = end
        self.after(1, self._bulk_update_next_chunk)
    def open_history_selection(self):
        if not self.current_project: show_warning_centered(self,"No Project Selected","Please select a project first."); return
        HistorySelectionDialog(self)
    def open_output_files(self):
        OutputFilesDialog(self)
    def open_text_editor(self):
        TextEditorDialog(self, initial_text="")
    def refresh_files(self, is_manual=False):
        if not self.current_project: return
        self.project_tree_scroll_pos = self.files_canvas.yview()[0] if self.files_canvas.winfo_height() > 1 else 0.0
        s = [p for p,v in self.file_vars.items() if v.get()]
        self.load_items_in_background(is_silent=not is_manual)
        self.after(200, lambda: self.restore_selection_after_refresh(s))

    def restore_selection_after_refresh(self, selection_to_restore):
        self.start_bulk_update_and_reselect(selection_to_restore)

    def open_settings(self):
        if self.current_project:
            if self.settings_dialog and self.settings_dialog.winfo_exists(): self.settings_dialog.destroy()
            self.settings_dialog = SettingsDialog(self)
        else: show_warning_centered(self,"No Project Selected","Please select a project first.")
    def manage_templates(self):
        if self.current_project:
            if getattr(self, 'templates_dialog', None) and self.templates_dialog.winfo_exists():
                self.templates_dialog.destroy()
            self.templates_dialog = TemplatesDialog(self)
        else:
            show_warning_centered(self,"No Project Selected","Please select a project first.")
    def on_file_selection_changed(self, *a):
        s = [p for p,v in self.file_vars.items() if v.get()]
        c = len(s)
        if not self.current_project:
            self.file_selected_label.config(text=f"Files selected: {c} / 0 (Chars: 0)")
            return
        pj = self.projects[self.current_project]
        pj["last_files"] = s
        self.save_app_projects()
        self.file_selected_label.config(text=f"Files selected: {c} / {self.all_files_count} (Chars: Calculating...)")
        self.refresh_selected_files_list(s)
        self.update_select_all_button()
        self.request_precomputation()
    def refresh_selected_files_list(self, selected):
        for w in self.selected_files_inner.winfo_children(): w.destroy()
        max_len = 0
        display_data = []
        with self.data_lock:
            for f in selected:
                ccount = format_german_thousand_sep(self.file_char_counts.get(f,0))
                dt = f"{f} [{ccount}]"
                display_data.append((f, dt))
                if len(dt) > max_len: max_len = len(dt)
        for f, lbl_text in display_data:
            rf = ttk.Frame(self.selected_files_inner)
            rf.pack(fill=tk.X, anchor='w')
            xb = ttk.Button(rf, text="x", width=1, style='RemoveFile.TButton', command=lambda ff=f: self.file_vars[ff].set(False))
            xb.pack(side=tk.LEFT, padx=(0,5))
            xb.bind("<MouseWheel>", self.on_files_mousewheel, add='+')
            xb.bind("<Button-4>", self.on_files_mousewheel, add='+')
            xb.bind("<Button-5>", self.on_files_mousewheel, add='+')
            lbl = ttk.Label(rf, text=lbl_text, cursor="hand2")
            lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
            lbl.bind("<Button-1>", lambda e, ff=f: self.on_selected_file_clicked(ff))
            lbl.bind("<MouseWheel>", self.on_files_mousewheel, add='+')
            lbl.bind("<Button-4>", self.on_files_mousewheel, add='+')
            lbl.bind("<Button-5>", self.on_files_mousewheel, add='+')
        line_count = len(selected)
        h = line_count if line_count>0 else 1
        if h>20: h=20
        approx_width = min((max_len*7)+50, 1000)
        self.selected_files_container.config(width=max(300, approx_width))
        self.selected_files_canvas.config(height=h*20, width=approx_width)
        self.selected_files_canvas.yview_moveto(0)
    def on_selected_file_clicked(self, f):
        self.clipboard_clear()
        self.clipboard_append(f)
        self.set_status_temporary("Copied to clipboard")
    def start_precompute_worker(self):
        self.precompute_thread = threading.Thread(target=self._precompute_worker, daemon=True)
        self.precompute_thread.start()
    def request_precomputation(self):
        self.precompute_request.set()
    def _precompute_worker(self):
        while True:
            self.precompute_request.wait()
            with self.precompute_lock:
                self.precompute_request.clear()
                if not self.current_project: continue
                
                sel = [p for p,v in self.file_vars.items() if v.get()]
                template_name = self.template_var.get()
                
                self.update_file_contents(sel)
                
                prompt, total_chars = self.simulate_final_prompt(sel, template_name)
                
                key = self.get_precompute_key(sel, template_name)
                self.precomputed_prompt_cache = {key: (prompt, total_chars)}
                self.queue.put(('precomputation_done', (sel, total_chars)))
    def get_precompute_key(self, sel, template_name):
        sel_hash = hashlib.md5("".join(sorted(sel)).encode('utf-8')).hexdigest()
        return f"{sel_hash}-{template_name}"
    def simulate_final_prompt(self, sel, template_override=None):
        prompt, _, _ = self.simulate_generation(sel, template_override)
        prompt = prompt.rstrip('\n')+'\n'
        total_chars = len(prompt)
        return prompt, total_chars
    def simulate_generation(self, sel, template_override=None):
        pr = self.projects[self.current_project]
        pt = pr["path"]
        px = pr.get("prefix","").strip()
        s1 = f"### {px} File Structure" if px else "### File Structure"
        s2 = f"### {px} Code Files provided" if px else "### Code Files provided"
        s3 = f"### {px} Code Files" if px else "### Code Files"
        gp, gk = [], pr.get("keep",[]) + self.settings.get("global_keep",[])
        if self.settings.get('respect_gitignore',True):
            gi = os.path.join(pt,'.gitignore')
            if os.path.isfile(gi): gp = parse_gitignore(gi)
        dt = self.generate_directory_tree_custom(pt, pr.get('blacklist',[]) + self.settings.get("global_blacklist",[]), self.settings.get('respect_gitignore',True), gp, gk)
        tn = template_override if template_override is not None else self.template_var.get()
        tc = self.templates.get(tn,"")
        
        if "{{CLIPBOARD}}" in tc:
            try: clip_content = self.clipboard_get()
            except: clip_content = ""
            tc = tc.replace("{{CLIPBOARD}}", clip_content)

        cblocks, tsz = [], 0
        total_selection_chars = 0
        with self.data_lock:
            for rp in sel:
                d = self.file_contents.get(rp)
                if d is None or d == "": continue # Skip empty or unread files
                total_selection_chars += len(d)
                if tsz+len(d)>MAX_CONTENT_SIZE: break
                cblocks.append(f"--- {rp} ---\n{d}\n--- {rp} ---\n")
                tsz+=len(d)
        p = tc.replace("{{dirs}}", f"{s1}\n\n{dt.strip()}")
        if "{{files_provided}}" in p:
            lines = "".join(f"- {x}\n" for x in sel if x in self.file_contents and self.file_contents.get(x) is not None)
            p=p.replace("{{files_provided}}",f"\n\n{s2}\n{lines}".rstrip('\n'))
        else: p=p.replace("{{files_provided}}","")
        fc = f"\n\n{s3}\n\n{''.join(cblocks)}" if cblocks else ""
        return p.replace("{{file_contents}}", fc), cblocks, total_selection_chars
    def generate_directory_tree_custom(self, sp, bl, rg, gp, gk, md=10, ml=1000):
        lines = []
        lb = [b.strip().lower() for b in bl]
        stack = [(sp,0)]
        lc=0
        while stack and lc<ml:
            cp, cd = stack.pop()
            if lc>=ml: break
            rr = os.path.relpath(cp,sp).replace("\\","/")
            if rr=="." : rr=""
            i = '    '*cd
            fn = os.path.basename(cp) if cd>0 else os.path.basename(sp)
            lines.append(f"{i}{fn}/"); lc+=1
            if lc>=ml or cd>=md: continue
            try: entries = sorted(os.listdir(cp))
            except: continue
            dirs_in_this, files_in_this = [], []
            for ent in entries:
                fp = os.path.join(cp, ent)
                rel_ent = f"{rr}/{ent}".lstrip("/").lower()
                if path_should_be_ignored(rel_ent, rg, gp, gk, lb):
                    if os.path.isdir(fp) and is_dir_forced_kept(rel_ent, gk): dirs_in_this.append(ent)
                    continue
                if os.path.isdir(fp): dirs_in_this.append(ent)
                else: files_in_this.append(ent)
            if len(dirs_in_this)+len(files_in_this)>50 and rr:
                lines.append(f"{i}    {fn}/...")
                continue
            for d in reversed(sorted(dirs_in_this)): stack.append((os.path.join(cp,d), cd+1))
            for f in sorted(files_in_this):
                if lc>=ml: break
                lines.append(f"{i}    {f}")
                lc+=1
                if lc>=ml: break
        if lc>=ml: lines.append("... (output truncated due to size limits)")
        return "\n".join(lines)
    def toggle_select_all(self):
        fi = [i for i in self.filtered_items if i["type"]=="file"]
        if not fi: return
        all_sel = all(self.file_vars[i["path"]].get() for i in fi)
        new_state = not all_sel
        files_to_change = [item["path"] for item in fi]
        
        self.bulk_update_active = True
        self._bulk_update_list = files_to_change
        self._bulk_update_selection = set(files_to_change) if new_state else set()
        self._bulk_update_index = 0
        self._bulk_update_chunk_size = 100
        self.after(1, self._bulk_update_next_chunk)
    def update_select_all_button(self):
        fi = [x for x in self.filtered_items if x["type"]=="file"]
        if fi:
            if all(self.file_vars[x["path"]].get() for x in fi): self.select_all_button.config(text="Unselect All")
            else: self.select_all_button.config(text="Select All")
        else: self.select_all_button.config(text="Select All")
    def generate_output(self, template_override=None):
        if self.settings_dialog and self.settings_dialog.winfo_exists(): self.settings_dialog.save_settings()
        if not self.current_project:
            show_warning_centered(self,"No Project Selected","Please select a project first.")
            return
        sel = [p for p,v in self.file_vars.items() if v.get()]
        is_clipboard_template = False
        active_template = template_override if template_override is not None else self.template_var.get()
        if active_template:
            tpl_content = self.templates.get(active_template, "")
            if "{{CLIPBOARD}}" in tpl_content:
                is_clipboard_template = True

        if not sel and not is_clipboard_template:
            show_warning_centered(self,"Warning","No files selected.")
            return

        if len(sel)>MAX_FILES:
            show_warning_centered(self,"Warning",f"You have selected {len(sel)} files. Maximum allowed is {MAX_FILES}.")
            return
        pj = self.projects[self.current_project]
        if not os.path.isdir(pj["path"]):
            show_error_centered(self,"Invalid Path","Project directory does not exist.")
            return
        self.generate_button.config(state=tk.DISABLED)
        self.generate_menu_button.config(state=tk.DISABLED)
        self.status_label.config(text="Generating...")
        
        pj["last_files"] = sel
        if template_override is None:
            pj["last_template"] = self.template_var.get()
        self.save_app_projects()
        
        precompute_key = self.get_precompute_key(sel, active_template)
        if precompute_key in self.precomputed_prompt_cache:
            prompt, _ = self.precomputed_prompt_cache[precompute_key]
            self.finalize_generation(prompt, sel)
            return

        threading.Thread(target=self.generate_output_worker, args=(sel, template_override), daemon=True).start()
    def generate_output_worker(self, sel, template_override):
        try:
            self.update_file_hashes(sel)
            self.update_file_contents(sel)
            
            prompt, _ = self.simulate_final_prompt(sel, template_override)
            
            self.queue.put(('save_and_open', (prompt, sel)))
        except Exception as e:
            logger.error("Error generating output: %s", e, exc_info=True)
            self.queue.put(('error', "Error generating output."))
    def update_file_hashes(self, sf):
        pj = self.projects[self.current_project]
        pt = pj["path"]
        with self.data_lock:
            for rp in sf:
                ap = os.path.join(pt,rp)
                self.file_hashes[rp] = get_file_hash(ap)
    def update_file_contents(self, sf):
        pj = self.projects[self.current_project]
        pt = pj["path"]
        with self.data_lock:
            for rp in sf:
                if self.file_contents.get(rp) in [None, ""]:
                    ap = os.path.join(pt,rp)
                    if os.path.isfile(ap):
                        try:
                            fsz = os.path.getsize(ap)
                            if fsz<=MAX_FILE_SIZE:
                                d = safe_read_file(ap)
                                self.file_contents[rp] = d
                                self.file_char_counts[rp] = len(d)
                            else:
                                self.file_contents[rp], self.file_char_counts[rp] = None,""
                        except OSError:
                            self.file_contents[rp], self.file_char_counts[rp] = None,""
    def process_queue(self):
        try:
            while True:
                t,d = self.queue.get_nowait()
                if t=='save_and_open':
                    prompt, sel = d
                    self.finalize_generation(prompt, sel)
                elif t=='error':
                    show_error_centered(self,"Error",d)
                    self.generate_button.config(state=tk.NORMAL)
                    self.generate_menu_button.config(state=tk.NORMAL)
                    self.status_label.config(text="Ready")
                elif t=='show_warning':
                    title, msg = d
                    show_warning_centered(self, title, msg)
                elif t=='precomputation_done':
                    sel, total_chars = d
                    if sel == [p for p,v in self.file_vars.items() if v.get()]:
                        self.update_selection_char_count(len(sel), total_chars)
                elif t=='load_items_done':
                    status, data, is_new_project = d
                    if status=="error":
                        show_error_centered(self,"Invalid Path","Project directory does not exist.")
                        self.status_label.config(text="Ready")
                    else:
                        self.load_items_result(data, is_new_project)
                        self.status_label.config(text="Ready")
                elif t=='auto_bl':
                    n, dirs = d
                    self.on_auto_blacklist_done(n, dirs)
                elif t=='file_contents_loaded':
                    proj = d
                    if proj==self.current_project:
                        with self.data_lock:
                            for p, lbl in self.file_labels.items():
                                cnt = format_german_thousand_sep(self.file_char_counts.get(p,0))
                                lbl.config(text=f"{os.path.basename(p)} [{cnt}]")
                        sel_now = [p for p,v in self.file_vars.items() if v.get()]
                        self.refresh_selected_files_list(sel_now)
                        self.request_precomputation()
        except queue.Empty: pass
        self.after(50, self.process_queue)
    def update_selection_char_count(self, file_count, char_count):
        self.file_selected_label.config(
            text=f"Files selected: {file_count} / {self.all_files_count} "
                 f"(Total Chars: {format_german_thousand_sep(char_count)})"
        )
    def finalize_generation(self, out, sel):
        p = self.projects[self.current_project]
        p["last_usage"] = time.time()
        p["usage_count"] = p.get("usage_count",0)+1
        self.save_app_projects()
        self.sort_and_set_projects(self.project_dropdown)
        self.save_and_open(out)
        self.generate_button.config(state=tk.NORMAL)
        self.generate_menu_button.config(state=tk.NORMAL)
        self.status_label.config(text="Ready")
        self.add_history_selection(sel)
    def save_and_open(self, out):
        ts = datetime.now().strftime("%d.%m.%Y_%H.%M.%S")
        spn = ''.join(c for c in self.current_project if c.isalnum() or c in(' ','_')).rstrip()
        fn = f"{spn}_{ts}.md"
        fp = os.path.join(OUTPUT_DIR, fn)
        try:
            with open(fp,'w',encoding='utf-8', newline='\n') as f:
                f.write(out)
            open_in_editor(fp)
        except: logger.error("%s", traceback.format_exc()); show_error_centered(self,"Error","Failed to save output.")
    def add_history_selection(self, sel):
        hs = self.settings.get(HISTORY_SELECTION_KEY, [])
        sel_set = set(sel)
        found = None
        for h in hs:
            if set(h["files"])==sel_set and h.get("project") == self.current_project: 
                found = h
                break
        if found:
            found["gens"] = found.get("gens",0)+1
            found["timestamp"] = time.time()
        else:
            hs.append({
                "id": hashlib.md5(",".join(sorted(sel)).encode('utf-8')).hexdigest(),
                "files": sel,
                "timestamp": time.time(),
                "gens": 1,
                "project": self.current_project or "(Unknown)",
                "saved_project_name": self.current_project
            })
        hs_sorted = sorted(hs, key=lambda x: x["timestamp"], reverse=True)[:20]
        self.settings[HISTORY_SELECTION_KEY] = hs_sorted
        self.save_app_settings()
    def edit_config(self):
        try: cp = os.path.abspath('config.ini'); open_in_editor(cp)
        except: logger.error("%s", traceback.format_exc()); show_error_centered(None,"Error","Failed to open config.ini.")
    def sort_and_set_projects(self, combobox):
        projs = list(self.projects.keys())
        usage_list = []
        for k in projs:
            p = self.projects[k]
            usage_list.append((k, p.get("usage_count", 0), p.get("last_usage", 0)))
        usage_list.sort(key=lambda x: (-x[2], -x[1], x[0].lower()))
        
        sorted_display_values = []
        w = 0
        for (name, uc, lu) in usage_list:
            ago = get_relative_time_str(lu) if lu > 0 else ""
            disp = f"{name} ({ago})" if ago else name
            w = max(w, len(disp))
            sorted_display_values.append(disp)
        
        combobox['values'] = sorted_display_values
        
        current_display_value = self.project_var.get()
        if current_display_value in sorted_display_values:
            combobox.set(current_display_value)
        elif sorted_display_values:
            combobox.set(sorted_display_values[0])
        
        combobox.configure(width=max(w, 20))
    def save_and_open_notepadpp(self, content):
        ts = datetime.now().strftime("%d.%m.%Y_%H.%M.%S")
        spn = ''.join(c for c in (self.current_project or "temp") if c.isalnum() or c in(' ','_')).rstrip()
        if not spn: spn="temp"
        fn = f"{spn}_text_{ts}.txt"
        fp = os.path.join(OUTPUT_DIR, fn)
        try:
            content = unify_line_endings(content).rstrip('\n')
            with open(fp,'w',encoding='utf-8') as f: f.write(content)
            if platform.system()=='Windows':
                try: subprocess.Popen(["notepad++", fp])
                except FileNotFoundError:
                    os.startfile(fp)
            else:
                subprocess.call(('xdg-open', fp))
            self.set_status_temporary("Opened in Notepad++")
        except:
            logger.error("%s", traceback.format_exc())
            show_error_centered(self, "Error", "Failed to open in Notepad++ or default editor.")
    def watch_file_changes(self):
        changed_projects, changed_settings = False, False
        if os.path.exists(PROJECTS_FILE):
            mt = os.path.getmtime(PROJECTS_FILE)
            if mt > self.last_projects_mtime and abs(mt - LAST_OWN_WRITE_TIMES["projects"]) > 1.0:
                changed_projects = True
            self.last_projects_mtime = mt
        
        if os.path.exists(SETTINGS_FILE):
            mt = os.path.getmtime(SETTINGS_FILE)
            if mt > self.last_settings_mtime and abs(mt - LAST_OWN_WRITE_TIMES["settings"]) > 1.0:
                changed_settings = True
            self.last_settings_mtime = mt

        if changed_projects:
            logger.info("External change detected in projects.json, reloading.")
            self.projects = load_projects(self.queue)
            self.baseline_projects = copy.deepcopy(self.projects)
            self.sort_and_set_projects(self.project_dropdown)
            if self.current_project and self.current_project not in self.projects:
                self.current_project=None
                self.clear_project_view()
            elif self.current_project:
                self.refresh_files()

        if changed_settings:
            logger.info("External change detected in settings.json, reloading.")
            self.settings = load_settings(self.queue)
            self.baseline_settings = copy.deepcopy(self.settings)
            self.load_templates(force_refresh=True)

        if getattr(self, 'templates_dialog', None) and self.templates_dialog.winfo_exists() and changed_settings:
            self.templates_dialog.settings = self.settings
            self.templates_dialog.templates = copy.deepcopy(self.settings.get("global_templates", {}))
            self.templates_dialog.template_names = sorted(self.templates_dialog.templates.keys())
            self.templates_dialog.refresh_template_list()
        
        self.after(2000, self.watch_file_changes)
    def show_quick_generate_menu(self):
        quick_templates = [name for name, content in self.templates.items() if "{{CLIPBOARD}}" not in content]
        if not quick_templates:
            return
        menu = tk.Menu(self, tearoff=0)
        for tpl_name in quick_templates:
            menu.add_command(label=tpl_name, command=lambda t=tpl_name: self.generate_output(template_override=t))
        
        x = self.generate_menu_button.winfo_rootx()
        y = self.generate_menu_button.winfo_rooty() + self.generate_menu_button.winfo_height()
        menu.post(x, y)

if __name__=="__main__":
    try:
        load_config()
        ensure_data_dirs()
        app = CodePromptGeneratorApp()
        app.mainloop()
    except Exception as e:
        logger.error("Fatal Error: %s\n%s", e, traceback.format_exc())
        print(f"A fatal error occurred: {e}", file=sys.stderr)