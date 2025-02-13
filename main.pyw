# File: code_prompt_generator/main.py 
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

import sys, os, logging, traceback, configparser, tkinter as tk, json, threading, hashlib, queue, platform, subprocess, fnmatch
from tkinter import filedialog, ttk, simpledialog, scrolledtext
from datetime import datetime

sys.path.extend(['../custom_utility_libs/logging_setup','../custom_utility_libs/openai_utils'])
from setup_logging import setup_logging
setup_logging(log_level=logging.DEBUG, excluded_files=['server.py'])
config = configparser.ConfigParser()

# Cache & JSON Paths Setup
# ------------------------------
CACHE_DIR = "cache"
def ensure_cache_dir():
    if not os.path.exists(CACHE_DIR): os.makedirs(CACHE_DIR)
PROJECTS_FILE = os.path.join(CACHE_DIR, 'projects.json')
SETTINGS_FILE = os.path.join(CACHE_DIR, 'settings.json')

# Config & Projects & Settings
# ------------------------------
def load_config():
    if not os.path.exists('config.ini'):
        show_error_centered(None, "Configuration Error", "config.ini file not found.")
        sys.exit()
    config.read('config.ini')

def load_projects():
    ensure_cache_dir()
    try:
        return json.load(open(PROJECTS_FILE,'r')) if os.path.exists(PROJECTS_FILE) else {}
    except:
        logging.error("Error loading projects: %s", traceback.format_exc())
        return {}

def save_projects(projects):
    ensure_cache_dir()
    try:
        json.dump(projects, open(PROJECTS_FILE,'w'), indent=4)
    except:
        logging.error("Error saving projects: %s", traceback.format_exc())

def load_settings():
    ensure_cache_dir()
    try:
        return json.load(open(SETTINGS_FILE,'r')) if os.path.exists(SETTINGS_FILE) else {}
    except:
        logging.error("Error loading settings: %s", traceback.format_exc())
        return {}

def save_settings(settings):
    ensure_cache_dir()
    try:
        json.dump(settings, open(SETTINGS_FILE,'w'), indent=4)
    except:
        logging.error("Error saving settings: %s", traceback.format_exc())

# Custom Centered Dialog Functions
# ------------------------------
def center_window(win, parent):
    win.update_idletasks()
    if parent:
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - (win.winfo_width() // 2)
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - (win.winfo_height() // 2)
    else:
        x = win.winfo_screenwidth() // 2 - win.winfo_width() // 2
        y = win.winfo_screenheight() // 2 - win.winfo_height() // 2
    win.geometry(f"+{x}+{y}")

def show_info_centered(parent, title, message):
    w = tk.Toplevel(parent) if parent else tk.Toplevel()
    w.title(title)
    if parent: w.transient(parent)
    w.grab_set()
    ttk.Label(w, text=message).pack(padx=20, pady=20)
    ttk.Button(w, text="OK", command=w.destroy).pack(pady=5)
    center_window(w, parent)
    w.wait_window()

def show_warning_centered(parent, title, message):
    w = tk.Toplevel(parent) if parent else tk.Toplevel()
    w.title(title)
    if parent: w.transient(parent)
    w.grab_set()
    ttk.Label(w, text=message).pack(padx=20, pady=20)
    ttk.Button(w, text="OK", command=w.destroy).pack(pady=5)
    center_window(w, parent)
    w.wait_window()

def show_error_centered(parent, title, message):
    w = tk.Toplevel(parent) if parent else tk.Toplevel()
    w.title(title)
    if parent: w.transient(parent)
    w.grab_set()
    ttk.Label(w, text=message).pack(padx=20, pady=20)
    ttk.Button(w, text="OK", command=w.destroy).pack(pady=5)
    center_window(w, parent)
    w.wait_window()

def show_yesno_centered(parent, title, message):
    w = tk.Toplevel(parent) if parent else tk.Toplevel()
    w.title(title)
    if parent: w.transient(parent)
    w.grab_set()
    r = {"answer": False}
    ttk.Label(w, text=message).pack(padx=20, pady=20)
    def yes(): r["answer"] = True; w.destroy()
    def no(): w.destroy()
    ttk.Button(w, text="Yes", command=yes).pack(side=tk.LEFT, padx=(20,10), pady=5)
    ttk.Button(w, text="No", command=no).pack(side=tk.RIGHT, padx=(10,20), pady=5)
    center_window(w, parent)
    w.wait_window()
    return r["answer"]

# File Hashes
# ------------------------------
def get_file_hash(file_path):
    try:
        h = hashlib.md5()
        with open(file_path, 'rb') as f:
            b = f.read(65536)
            while b: h.update(b); b = f.read(65536)
        h.update(str(os.path.getmtime(file_path)).encode('utf-8'))
        return h.hexdigest()
    except:
        logging.error("%s", traceback.format_exc())
        return None

def get_cache_key(selected_files, file_hashes):
    d = ''.join(sorted([f + file_hashes[f] for f in selected_files]))
    return hashlib.md5(d.encode('utf-8')).hexdigest()

# Cache Utils
# ------------------------------
def get_cached_output(project_name, cache_key):
    ensure_cache_dir()
    try:
        cf = os.path.join(CACHE_DIR, f'cache_{project_name}.json')
        if not os.path.exists(cf): return None
        c = json.load(open(cf,'r'))
        return c.get(cache_key)
    except:
        logging.error("%s", traceback.format_exc())
        return None

def save_cached_output(project_name, cache_key, output):
    ensure_cache_dir()
    try:
        cf = os.path.join(CACHE_DIR, f'cache_{project_name}.json')
        c = json.load(open(cf,'r')) if os.path.exists(cf) else {}
        c[cache_key] = output
        json.dump(c, open(cf,'w'), indent=4)
    except:
        logging.error("%s", traceback.format_exc())

# OS Utils and Helper Functions
# ------------------------------
def open_in_editor(file_path):
    try:
        if platform.system() == 'Windows': os.startfile(file_path)
        elif platform.system() == 'Darwin': subprocess.call(('open', file_path))
        else: subprocess.call(('xdg-open', file_path))
    except:
        logging.error("%s", traceback.format_exc())

def resource_path(relative_path):
    try: return os.path.join(sys._MEIPASS, relative_path)
    except: return os.path.abspath(os.path.join(".", relative_path))

def parse_gitignore(gitignore_path):
    p = []
    try:
        for l in open(gitignore_path,'r'): 
            l = l.strip()
            if l and not l.startswith('#'): p.append(l)
    except:
        logging.error("%s", traceback.format_exc())
    return p

def match_any_gitignore(path_segment, patterns):
    return any(fnmatch.fnmatch(path_segment, x) or fnmatch.fnmatch(os.path.basename(path_segment), x) for x in patterns)

def match_any_keep(path_segment, patterns):
    return any(fnmatch.fnmatch(path_segment, x) or fnmatch.fnmatch(os.path.basename(path_segment), x) for x in patterns)

def path_should_be_ignored(r, rg, gp, gk, bl):
    if any(b in r for b in bl): return True
    if rg and match_any_gitignore(r, gp) and not match_any_keep(r, gk): return True
    return False

def generate_directory_tree(sp, bl=None, rg=False, gp=None, gk=None, md=10, ml=1000):
    if not bl: bl = []
    if not gp: gp = []
    if not gk: gk = []
    sp = os.path.normpath(sp)
    bd = sp.count(os.sep)
    lb = [b.strip().lower() for b in bl]
    lc = 0
    lines, stack = [], [(sp,0)]
    while stack and lc<ml:
        cp, cd = stack.pop()
        if lc>=ml: break
        rr = os.path.relpath(cp,sp).replace("\\","/")
        if rr=="." : rr=""
        i = '    '*cd
        fn = os.path.basename(cp) if cd>0 else os.path.basename(sp)
        lines.append(f"{i}{fn}/"); lc+=1
        if lc>=ml or cd>=md: continue
        try: e = sorted(os.listdir(cp))
        except: continue
        dp=[]
        for f in e:
            fp = os.path.join(cp,f)
            r2 = (f"{rr}/{f}").lstrip("/").lower()
            if path_should_be_ignored(r2,rg,gp,gk,lb): continue
            if os.path.isdir(fp): dp.append(fp)
            else:
                if lc>=ml: break
                lines.append(f"{i}    {f}")
                lc+=1
                if lc>=ml: break
        for d in reversed(dp): stack.append((d, cd+1))
    if lc>=ml: lines.append("... (output truncated due to size limits)")
    return "\n".join(lines)

def safe_read_file(path):
    try: return open(path,'r',encoding='utf-8',errors='replace').read()
    except:
        logging.error("%s", traceback.format_exc())
        return ""

def format_german_thousand_sep(num):
    return f"{num:,}".replace(",", ".")

def unify_line_endings_for_windows(text):
    return text.replace('\n','\r\n') if platform.system()=='Windows' else text

# Settings Dialog
# ------------------------------
class SettingsDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Settings")
        self.parent = parent
        if parent: self.transient(parent)
        self.grab_set()
        self.create_widgets()
        self.center_window()

    def center_window(self):
        self.update_idletasks()
        px, py = self.parent.winfo_rootx(), self.parent.winfo_rooty()
        pw, ph = self.parent.winfo_width(), self.parent.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        x = px + (pw//2)-(w//2)
        y = py + (ph//2)-(h//2)
        self.geometry(f"+{x}+{y}")

    def create_widgets(self):
        ttk.Label(self, text="Blacklisted Folders/Files (comma-separated):").pack(pady=5)
        self.blacklist_entry = ttk.Entry(self, takefocus=True)
        self.blacklist_entry.insert(0,','.join(self.parent.blacklist))
        self.blacklist_entry.pack(fill=tk.X,padx=10)
        ttk.Separator(self,orient='horizontal').pack(fill=tk.X,padx=10,pady=5)
        ttk.Label(self, text="Prefix:").pack(pady=5)
        self.prefix_entry = ttk.Entry(self, takefocus=True)
        cp = self.parent.projects.get(self.parent.current_project,{})
        self.prefix_entry.insert(0,cp.get("prefix",""))
        self.prefix_entry.pack(fill=tk.X,padx=10)
        ttk.Separator(self,orient='horizontal').pack(fill=tk.X,padx=10,pady=5)
        self.respect_var = tk.BooleanVar(value=self.parent.settings.get('respect_gitignore',True))
        ttk.Checkbutton(self,text="Respect .gitignore",variable=self.respect_var,takefocus=True).pack(pady=5)
        ttk.Label(self, text="Gitignore Keep Patterns (comma-separated):").pack(pady=5)
        self.keepignore_entry = ttk.Entry(self, takefocus=True)
        self.keepignore_entry.insert(0,self.parent.settings.get('gitignore_keep',""))
        self.keepignore_entry.pack(fill=tk.X,padx=10)
        ttk.Separator(self,orient='horizontal').pack(fill=tk.X,padx=10,pady=5)
        ttk.Label(self, text="Excluded by .gitignore (info only):").pack(pady=5)
        self.excluded_text = ttk.Entry(self, state='readonly')
        ej = ', '.join(self.parent.gitignore_skipped) if self.parent.gitignore_skipped else ""
        self.excluded_text.config(state='normal'); self.excluded_text.delete(0,tk.END)
        self.excluded_text.insert(0,ej); self.excluded_text.config(state='readonly')
        self.excluded_text.pack(fill=tk.X,padx=10)
        ttk.Separator(self,orient='horizontal').pack(fill=tk.X,padx=10,pady=5)
        ttk.Button(self, text="Save", command=self.save_settings, takefocus=True).pack(pady=5)

    def save_settings(self):
        bl = [x.strip().lower() for x in self.blacklist_entry.get().split(',') if x.strip()]
        pr = self.parent.projects[self.parent.current_project]
        pr["blacklist"] = bl
        self.parent.blacklist = bl
        pr["prefix"] = self.prefix_entry.get().strip()
        self.parent.settings['respect_gitignore'] = self.respect_var.get()
        self.parent.settings['gitignore_keep'] = self.keepignore_entry.get()
        save_projects(self.parent.projects)
        save_settings(self.parent.settings)
        self.destroy()
        self.parent.refresh_files()

# Templates Dialog
# ------------------------------
class TemplatesDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Manage Templates")
        self.parent = parent
        if parent: self.transient(parent)
        self.grab_set()
        self.templates = self.parent.templates
        self.create_widgets()
        self.center_window()

    def center_window(self):
        self.update_idletasks()
        px, py = self.parent.winfo_rootx(), self.parent.winfo_rooty()
        pw, ph = self.parent.winfo_width(), self.parent.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        x = px + (pw//2)-(w//2)
        y = py + (ph//2)-(h//2)
        self.geometry(f"+{x}+{y}")

    def create_widgets(self):
        self.last_selected_index = None
        lb = tk.Listbox(self, exportselection=False, takefocus=True)
        lb.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        for t in self.templates: lb.insert(tk.END, t)
        lb.bind('<<ListboxSelect>>', self.on_template_select)
        self.template_listbox = lb
        cf = ttk.Frame(self); cf.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        ttk.Label(cf, text="Template Content:").pack()
        self.template_text = scrolledtext.ScrolledText(cf, height=15, takefocus=True)
        self.template_text.pack(fill=tk.BOTH, expand=True)
        bf = ttk.Frame(self); bf.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(bf, text="Add New", command=self.add_template, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text="Delete", command=self.delete_template, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text="Save", command=self.save_template, takefocus=True).pack(side=tk.RIGHT, padx=5)
        if lb.size()>0:
            lb.selection_set(0)
            self.on_template_select(None)

    def on_template_select(self, _):
        s = self.template_listbox.curselection()
        if s:
            i = s[0]
            self.last_selected_index = i
            t = self.template_listbox.get(i)
            self.template_text.delete('1.0',tk.END)
            self.template_text.insert(tk.END,self.templates[t])
        else:
            if self.last_selected_index is not None:
                self.template_listbox.selection_set(self.last_selected_index)
            elif self.template_listbox.size()>0:
                self.template_listbox.selection_set(0)
                self.last_selected_index = 0
                self.on_template_select(None)

    def add_template(self):
        n = simpledialog.askstring("Template Name","Enter template name:",parent=self)
        if n and n not in self.templates:
            self.templates[n] = ""
            self.template_listbox.insert(tk.END,n)
            self.template_listbox.select_clear(0,tk.END)
            self.template_listbox.selection_set(tk.END)
            self.on_template_select(None)
        elif n in self.templates:
            show_error_centered(self,"Error","Template name already exists.")
        elif not n:
            show_warning_centered(self,"Warning","Template name cannot be empty.")

    def delete_template(self):
        s = self.template_listbox.curselection()
        if s:
            i = s[0]
            t = self.template_listbox.get(i)
            if show_yesno_centered(self,"Delete Template",f"Are you sure you want to delete '{t}'?"):
                del self.templates[t]
                self.template_listbox.delete(i)
                self.template_text.delete('1.0',tk.END)
                self.parent.projects[self.parent.current_project]["templates"] = self.templates
                save_projects(self.parent.projects)
                self.parent.load_templates()
                if self.template_listbox.size()>0:
                    self.template_listbox.selection_set(0)
                    self.on_template_select(None)
                else:
                    self.last_selected_index=None

    def save_template(self):
        s = self.template_listbox.curselection()
        if s:
            i = s[0]
            t = self.template_listbox.get(i)
            c = self.template_text.get('1.0',tk.END).rstrip('\n')
            self.templates[t] = c
            self.parent.projects[self.parent.current_project]["templates"] = self.templates
            save_projects(self.parent.projects)
            self.parent.load_templates()
            self.destroy()

# Main Application
# ------------------------------
class CodePromptGeneratorApp(tk.Tk):
    MAX_FILES = 500
    MAX_CONTENT_SIZE = 2000000
    MAX_FILE_SIZE = 500000
    def __init__(self):
        super().__init__()
        self.title("Code Prompt Generator - Modern UI")
        self.style = ttk.Style(self)
        self.style.theme_use('vista')
        self.style.configure('.', font=('Segoe UI', 10), background='#F3F3F3')
        self.style.configure('TFrame', background='#F3F3F3')
        self.style.configure('TLabel', background='#F3F3F3', foreground='#1E1E1E')
        self.style.configure('TCheckbutton', background='#F3F3F3', foreground='#1E1E1E')
        self.style.configure('ProjectOps.TLabelframe', background='#F3F3F3', padding=10, foreground='#444444')
        self.style.configure('TemplateOps.TLabelframe', background='#F3F3F3', padding=10, foreground='#444444')
        self.style.configure('FilesFrame.TLabelframe', background='#F3F3F3', padding=10, foreground='#444444')
        self.style.configure('TButton', foreground='black', background='#F0F0F0', padding=6, font=('Segoe UI',10,'normal'))
        self.style.map('TButton', foreground=[('disabled','#7A7A7A'),('active','black')], background=[('active','#E0E0E0'),('disabled','#F0F0F0')])
        self.style.configure('Warning.TLabel', foreground='#AA6000')
        self.style.configure('Error.TLabel', foreground='#AA0000')
        self.style.configure('Info.TLabel', foreground='#0066AA')
        self.icon_path = resource_path('app_icon.ico')
        if os.path.exists(self.icon_path): self.iconbitmap(self.icon_path)
        self.projects = load_projects()
        self.settings = load_settings()
        self.settings.setdefault('respect_gitignore',True)
        self.settings.setdefault('gitignore_keep',"")
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
        self.all_files_count = 0
        self.queue = queue.Queue()
        self.settings_dialog = None
        self.simulation_thread = None
        self.simulation_lock = threading.Lock()
        self.selected_files_cache = []
        self.create_layout()
        self.after(100, self.process_queue)
        lp = self.settings.get('last_selected_project')
        if lp and lp in self.projects: self.project_var.set(lp); self.load_project(lp)
        self.restore_window_geometry()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_layout(self):
        self.top_frame = ttk.Frame(self); self.top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)
        self.create_top_widgets(self.top_frame)
        self.file_frame = ttk.LabelFrame(self, text="Project Files", style='FilesFrame.TLabelframe')
        self.file_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(5,0))
        self.create_file_widgets(self.file_frame)
        self.control_frame = ttk.Frame(self); self.control_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=5)
        self.create_bottom_widgets(self.control_frame)

    def create_top_widgets(self, c):
        pa = ttk.LabelFrame(c, text="Project Operations", style='ProjectOps.TLabelframe')
        pa.pack(side=tk.LEFT, fill=tk.Y, padx=(0,5))
        ttk.Label(pa, text="Select Project:").pack(anchor='w', pady=(0,2))
        self.project_var = tk.StringVar()
        cb = ttk.Combobox(pa, textvariable=self.project_var, state='readonly', width=20, takefocus=True)
        cb.pack(anchor='w', pady=(0,5))
        cb.bind("<<ComboboxSelected>>", self.on_project_selected)
        cb['values'] = list(self.projects.keys())
        of = ttk.Frame(pa); of.pack(anchor='w', pady=(5,0))
        ttk.Button(of, text="Add Project", command=self.add_project, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(of, text="Remove Project", command=self.remove_project, takefocus=True).pack(side=tk.LEFT, padx=5)
        tf = ttk.LabelFrame(c, text="Template", style='TemplateOps.TLabelframe')
        tf.pack(side=tk.RIGHT, fill=tk.Y)
        ttk.Label(tf, text="Select Template:").pack(anchor='w', pady=(0,2))
        self.template_var = tk.StringVar()
        td = ttk.Combobox(tf, textvariable=self.template_var, state='readonly', width=20, takefocus=True)
        td.pack(anchor='w', pady=(0,5))
        td.bind("<<ComboboxSelected>>", self.on_template_selected)
        self.manage_templates_btn = ttk.Button(tf, text="Manage Templates", command=self.manage_templates, takefocus=True)
        self.manage_templates_btn.pack(anchor='w', pady=5)
        self.project_dropdown = cb
        self.template_dropdown = td

    def create_file_widgets(self, c):
        sf = ttk.Frame(c); sf.pack(anchor='w', padx=5, pady=(5,2))
        ttk.Label(sf, text="Search:").pack(side=tk.LEFT, padx=(0,5))
        self.file_search_var = tk.StringVar()
        self.file_search_var.trace_add("write", lambda *a: self.filter_and_display_items())
        se = ttk.Entry(sf, textvariable=self.file_search_var, width=25, takefocus=True); se.pack(side=tk.LEFT)
        csb = ttk.Button(sf, text="✕", command=lambda: self.file_search_var.set(""))
        csb.pack(side=tk.LEFT, padx=(5,0)); csb.configure(style='Toolbutton')
        tf = ttk.Frame(c); tf.pack(anchor='w', padx=5, pady=(5,2))
        self.select_all_button = ttk.Button(tf, text="Select All", command=self.toggle_select_all, takefocus=True)
        self.select_all_button.pack(side=tk.LEFT, padx=5)
        self.invert_button = ttk.Button(tf, text="Invert Selection", command=self.invert_selection, takefocus=True)
        self.invert_button.pack(side=tk.LEFT, padx=5)
        self.file_selected_label = ttk.Label(tf, text="Files selected: 0 / 0 (Chars: 0)", width=40)
        self.file_selected_label.pack(side=tk.LEFT, padx=(10,0))
        mf = ttk.Frame(c); mf.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
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
        self.selected_files_frame = ttk.Frame(mf)
        self.selected_files_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(5,0))
        ttk.Label(self.selected_files_frame, text="Selected Files:").pack(anchor='nw')
        self.selected_files_list_text = scrolledtext.ScrolledText(self.selected_files_frame, height=10, width=30, wrap='none')
        self.selected_files_list_text.pack(fill=tk.BOTH, expand=True)
        self.selected_files_list_text.config(state='disabled')

    def bind_mousewheel_events(self, w):
        w.bind("<MouseWheel>", self.on_files_mousewheel, add='+')
        w.bind("<Button-4>", self.on_files_mousewheel, add='+')
        w.bind("<Button-5>", self.on_files_mousewheel, add='+')

    def create_bottom_widgets(self, c):
        self.generate_button = ttk.Button(c, text="Generate", width=12, command=self.generate_output, takefocus=True)
        self.generate_button.pack(side=tk.LEFT, padx=5)
        self.refresh_button = ttk.Button(c, text="Refresh Files", width=12, command=self.refresh_files, takefocus=True)
        self.refresh_button.pack(side=tk.LEFT, padx=5)
        self.settings_button = ttk.Button(c, text="Settings", command=self.open_settings, takefocus=True)
        self.settings_button.pack(side=tk.RIGHT, padx=5)
        self.status_label = ttk.Label(c, text="Ready")
        self.status_label.pack(side=tk.RIGHT, padx=5)

    def on_files_mousewheel(self, event):
        if event.num==4: self.files_canvas.yview_scroll(-1,"units")
        elif event.num==5: self.files_canvas.yview_scroll(1,"units")
        else:
            d = int(-1*(event.delta/120)) if platform.system()=='Windows' else int(-1*event.delta)
            self.files_canvas.yview_scroll(d,"units")

    def restore_window_geometry(self):
        g = self.settings.get('window_geometry')
        if g: self.geometry(g)
        else: self.geometry("1000x700")

    def on_closing(self):
        self.settings['window_geometry'] = self.geometry()
        save_settings(self.settings)
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
        self.projects[n] = {"path":dp,"last_files":[],"blacklist":[],"templates":{},"last_template":"","prefix":"","click_counts":{}}
        self.projects[n]["templates"][n] = "Your task is to\n\n{{dirs}}{{files_provided}}{{file_contents}}"
        save_projects(self.projects)
        self.project_dropdown['values'] = list(self.projects.keys())
        self.project_dropdown.set(n)
        self.load_project(n)

    def remove_project(self):
        p = self.project_var.get()
        if not p:
            show_warning_centered(self,"No Project Selected","Please select a project to remove.")
            return
        if p not in self.projects:
            show_warning_centered(self,"Invalid Selection","Project not found.")
            return
        if show_yesno_centered(self,"Remove Project",f"Are you sure you want to remove the project '{p}'?\nThis action is irreversible."):
            del self.projects[p]
            save_projects(self.projects)
            if self.settings.get('last_selected_project')==p:
                self.settings['last_selected_project']=None
                save_settings(self.settings)
            cf = os.path.join(CACHE_DIR,f"cache_{p}.json")
            if os.path.exists(cf):
                try: os.remove(cf)
                except: logging.error("%s", traceback.format_exc())
            if self.current_project==p: self.current_project=None
            nm = list(self.projects.keys())
            self.project_dropdown['values'] = nm
            if nm:
                self.project_var.set(nm[0])
                self.load_project(nm[0])
            else:
                self.project_var.set("")
                self.file_vars,self.file_hashes={},{}
                for w in self.inner_frame.winfo_children(): w.destroy()

    def on_project_selected(self, _):
        self.load_project(self.project_var.get())

    def load_project(self, n):
        self.current_project = n
        self.settings['last_selected_project'] = n
        save_settings(self.settings)
        p = self.projects[n]
        self.blacklist = p.get("blacklist",[])
        self.templates = p.get("templates",{})
        self.click_counts = p.get("click_counts",{})
        self.check_and_auto_blacklist(n)
        self.load_templates()
        self.load_items()

    def load_templates(self):
        t = list(self.templates.keys())
        self.template_dropdown['values'] = t
        lt = self.projects[self.current_project].get("last_template")
        if lt in t: self.template_var.set(lt)
        elif t:
            self.template_var.set(t[0])
            self.projects[self.current_project]["last_template"] = t[0]
            save_projects(self.projects)
        else: self.template_var.set("")
        self.on_template_selected(None)

    def on_template_selected(self, _):
        if self.current_project:
            self.projects[self.current_project]["last_template"]=self.template_var.get()
            save_projects(self.projects)

    def load_items(self):
        for w in self.inner_frame.winfo_children(): w.destroy()
        self.file_vars,self.file_hashes,self.file_contents,self.file_char_counts={}, {}, {}, {}
        self.all_items,self.all_files_count = [],0
        p = self.projects[self.current_project]
        pt = p["path"]
        if not os.path.isdir(pt):
            show_error_centered(self,"Invalid Path","Project directory does not exist.")
            return
        fc,fe = 0,False
        bl_lower = [b.strip().lower() for b in p.get("blacklist",[])]
        self.gitignore_skipped = []
        gp, gk = [], [x.strip() for x in self.settings.get('gitignore_keep',"").split(',') if x.strip()]
        if self.settings.get('respect_gitignore',True):
            gi = os.path.join(pt,'.gitignore')
            if os.path.isfile(gi): gp = parse_gitignore(gi)
        for r, ds, fs in os.walk(pt):
            if fc>=self.MAX_FILES: break
            ds.sort(); fs.sort()
            rr = os.path.relpath(r,pt).replace("\\","/")
            if rr=="." : rr=""
            rl = rr.count('/') if rr else 0
            if rr: self.all_items.append({"type":"dir","path":rr+"/","level":rl})
            kd=[]
            for d in ds:
                dr = f"{rr}/{d}".lstrip("/").lower()
                if any(bb in dr for bb in bl_lower): continue
                if self.settings.get('respect_gitignore',True) and match_any_gitignore(dr,gp) and not match_any_keep(dr,gk): self.gitignore_skipped.append(d)
                else: kd.append(d)
            ds[:] = kd
            for f in fs:
                if fc>=self.MAX_FILES: fe=True; break
                relp = f"{rr}/{f}".lstrip("/")
                rpl = relp.lower()
                if any(bb in rpl for bb in bl_lower): continue
                if self.settings.get('respect_gitignore',True) and match_any_gitignore(relp,gp) and not match_any_keep(relp,gk):
                    self.gitignore_skipped.append(relp); continue
                ap = os.path.join(r,f)
                if not os.path.isfile(ap): continue
                self.all_items.append({"type":"file","path":relp,"level":relp.count('/')})
                self.file_hashes[relp] = get_file_hash(ap)
                fsiz = os.path.getsize(ap)
                if fsiz<=self.MAX_FILE_SIZE:
                    dt = safe_read_file(ap)
                    self.file_contents[relp] = dt
                    self.file_char_counts[relp] = len(dt)
                else:
                    self.file_contents[relp] = None
                    self.file_char_counts[relp] = 0
                fc+=1
            if fe: break
        if fe: show_warning_centered(self,"File Limit Exceeded",f"Too many files in the project. Only the first {self.MAX_FILES} files are loaded.")
        lf = p.get("last_files",[])
        for it in self.all_items:
            if it["type"]=="file":
                self.file_vars[it["path"]] = tk.BooleanVar(value=(it["path"] in lf))
        for v in self.file_vars.values():
            v.trace_add('write', self.on_file_selection_changed)
        self.all_files_count = sum(1 for it in self.all_items if it["type"]=="file")
        self.filter_and_display_items()

    def filter_and_display_items(self):
        for w in self.inner_frame.winfo_children(): w.destroy()
        q = self.file_search_var.get().strip().lower()
        self.filtered_items = [it for it in self.all_items if q in it["path"].lower()] if q else self.all_items
        for it in self.filtered_items:
            rf = ttk.Frame(self.inner_frame); rf.pack(fill=tk.X,anchor='w')
            self.bind_mousewheel_events(rf)
            i = '    '*it["level"]
            if it["type"]=="dir":
                lbl = ttk.Label(rf, text=f"{i}{os.path.basename(it['path'].rstrip('/'))}/", style='Info.TLabel')
                lbl.pack(side=tk.LEFT, padx=5)
                self.bind_mousewheel_events(lbl)
            else:
                p = it["path"]
                chk = ttk.Checkbutton(rf, variable=self.file_vars[p])
                chk.pack(side=tk.LEFT, padx=(4+it["level"]*10,2))
                cnt = format_german_thousand_sep(self.file_char_counts.get(p,0))
                lbl = ttk.Label(rf, text=f"{os.path.basename(p)} [{cnt}]")
                lbl.pack(side=tk.LEFT, padx=2)
                lbl.bind("<Button-1>", lambda e, x=p: self.toggle_file_var(x))
                self.bind_mousewheel_events(chk)
                self.bind_mousewheel_events(lbl)
        self.on_file_selection_changed()
        self.files_canvas.yview_moveto(0)

    def toggle_file_var(self, p):
        self.file_vars[p].set(not self.file_vars[p].get())

    def on_checkbox_click(self, f, _):
        ov = self.previous_check_states.get(f,False)
        nv = self.file_vars[f].get()
        if not ov and nv:
            self.click_counts[f] = min(self.click_counts.get(f,0)+1,100)
            if self.current_project:
                self.projects[self.current_project]['click_counts'] = self.click_counts
                save_projects(self.projects)
        self.previous_check_states[f] = nv
        self.on_file_selection_changed()

    def refresh_files(self):
        s = [p for p,v in self.file_vars.items() if v.get()]
        self.load_items()
        for f in s:
            if f in self.file_vars: self.file_vars[f].set(True)

    def open_settings(self):
        if self.current_project:
            if self.settings_dialog and self.settings_dialog.winfo_exists(): self.settings_dialog.destroy()
            self.settings_dialog = SettingsDialog(self)
        else: show_warning_centered(self,"No Project Selected","Please select a project first.")

    def manage_templates(self):
        if self.current_project: TemplatesDialog(self)
        else: show_warning_centered(self,"No Project Selected","Please select a project first.")

    def on_file_selection_changed(self, *a):
        s = [p for p,v in self.file_vars.items() if v.get()]
        c = len(s)
        if not self.current_project:
            self.file_selected_label.config(text=f"Files selected: {c} / {self.all_files_count} (Chars: 0)")
            return
        pj = self.projects[self.current_project]
        pj["last_files"] = s
        save_projects(self.projects)
        self.file_selected_label.config(text=f"Files selected: {c} / {self.all_files_count} (Chars: ...)")
        self.selected_files_list_text.config(state='normal')
        self.selected_files_list_text.delete('1.0',tk.END)
        ml = 30
        for f in s:
            self.selected_files_list_text.insert(tk.END,f"{f}\n")
            ml = max(ml,len(f))
        ml = min(ml,120)
        self.selected_files_list_text.config(width=ml)
        self.selected_files_list_text.config(state='disabled')
        self.update_select_all_button()
        self.run_simulation_in_background(s)

    def run_simulation_in_background(self, sel):
        if self.simulation_thread and self.simulation_thread.is_alive():
            self.selected_files_cache = sel
            return
        def worker(s0):
            while True:
                with self.simulation_lock:
                    local_sel = self.selected_files_cache or s0
                    self.selected_files_cache = []
                fp = self.simulate_final_prompt(local_sel)
                fm = self.get_file_len_map(local_sel)
                self.queue.put(('simulation_done',(local_sel,fp,fm)))
                with self.simulation_lock:
                    if not self.selected_files_cache: break
        self.selected_files_cache = sel
        self.simulation_thread = threading.Thread(target=worker, args=(sel,), daemon=True)
        self.simulation_thread.start()

    def simulate_final_prompt(self, sel):
        p,_ = self.simulate_generation(sel)
        return p.rstrip('\n')+'\n'

    def get_file_len_map(self, sel):
        r={}
        for f in sel:
            o = len(f"--- {f} ---\n")
            d = self.file_contents.get(f)
            r[f] = len(d)+2*o if d else 0
        return r

    def simulate_generation(self, sel):
        pr = self.projects[self.current_project]
        pt = pr["path"]
        px = pr.get("prefix","").strip()
        s1 = f"### {px} File Structure" if px else "### File Structure"
        s2 = f"### {px} Code Files provided" if px else "### Code Files provided"
        s3 = f"### {px} Code Files" if px else "### Code Files"
        gp, gk = [], [x.strip() for x in self.settings.get('gitignore_keep',"").split(',') if x.strip()]
        if self.settings.get('respect_gitignore',True):
            gi = os.path.join(pt,'.gitignore')
            if os.path.isfile(gi): gp = parse_gitignore(gi)
        dt = generate_directory_tree(pt, pr.get("blacklist",[]), self.settings.get('respect_gitignore',True), gp, gk,10,1000)
        tn = self.template_var.get()
        tc = self.templates.get(tn,"")
        cblocks, tsz = [], 0
        for rp in sel:
            d = self.file_contents.get(rp)
            if not d: continue
            if tsz+len(d)>self.MAX_CONTENT_SIZE: break
            o = len(f"--- {rp} ---\n")
            cblocks.append(f"--- {rp} ---\n{d}\n--- {rp} ---\n")
            tsz+=len(d)
        p = tc.replace("{{dirs}}", f"{s1}\n\n{dt.strip()}")
        if "{{files_provided}}" in p:
            lines = "".join(f"- {x}\n" for x in sel if x in self.file_contents and self.file_contents[x] is not None)
            p=p.replace("{{files_provided}}",f"\n\n{s2}\n{lines}".rstrip('\n'))
        else: p=p.replace("{{files_provided}}","")
        fc = f"\n\n{s3}\n\n{''.join(cblocks)}" if cblocks else ""
        return p.replace("{{file_contents}}", fc), cblocks

    def toggle_select_all(self):
        if not self.filtered_items: return
        fi = [i for i in self.filtered_items if i["type"]=="file"]
        if not fi: return
        all_sel = all(self.file_vars[i["path"]].get() for i in fi)
        for i in fi: self.file_vars[i["path"]].set(not all_sel)
        self.update_select_all_button()

    def invert_selection(self):
        if not self.filtered_items: return
        for i in [x for x in self.filtered_items if x["type"]=="file"]:
            self.file_vars[i["path"]].set(not self.file_vars[i["path"]].get())
        self.update_select_all_button()

    def update_select_all_button(self):
        fi = [x for x in self.filtered_items if x["type"]=="file"]
        if fi:
            if all(self.file_vars[x["path"]].get() for x in fi):
                self.select_all_button.config(text="Unselect All")
            else:
                self.select_all_button.config(text="Select All")
        else:
            self.select_all_button.config(text="Select All")

    def generate_output(self):
        if self.settings_dialog and self.settings_dialog.winfo_exists():
            self.settings_dialog.save_settings()
        if not self.current_project:
            show_warning_centered(self,"No Project Selected","Please select a project first.")
            return
        sel = [p for p,v in self.file_vars.items() if v.get()]
        if not sel:
            show_warning_centered(self,"Warning","No files selected.")
            return
        if len(sel)>self.MAX_FILES:
            show_warning_centered(self,"Warning",f"You have selected {len(sel)} files. Maximum allowed is {self.MAX_FILES}.")
            return
        pj = self.projects[self.current_project]
        if not os.path.isdir(pj["path"]):
            show_error_centered(self,"Invalid Path","Project directory does not exist.")
            return
        self.generate_button.config(state=tk.DISABLED)
        self.status_label.config(text="Generating...")
        pj["last_files"] = sel
        pj["last_template"] = self.template_var.get()
        save_projects(self.projects)
        self.update_file_hashes(sel)
        prompt = self.simulate_final_prompt(sel)
        ck = self.make_cache_key_for_prompt(sel,prompt)
        co = get_cached_output(self.current_project, ck)
        if co:
            self.save_and_open(co)
            self.generate_button.config(state=tk.NORMAL)
            self.status_label.config(text="Ready")
        else:
            threading.Thread(target=self.generate_output_content, args=(prompt,ck), daemon=True).start()

    def update_file_hashes(self, sf):
        pj = self.projects[self.current_project]
        pt = pj["path"]
        for rp in sf:
            ap = os.path.join(pt,rp)
            self.file_hashes[rp] = get_file_hash(ap)

    def make_cache_key_for_prompt(self, sel, prompt):
        s1 = hashlib.md5("".join(sel).encode('utf-8')).hexdigest()
        s2 = hashlib.md5(prompt.encode('utf-8')).hexdigest()
        return s1+s2

    def generate_output_content(self, prompt, ck):
        try:
            save_cached_output(self.current_project, ck, prompt)
            self.queue.put(('save_and_open',prompt))
        except:
            logging.error("%s", traceback.format_exc())
            self.queue.put(('error',"Error generating output."))

    def process_queue(self):
        try:
            while True:
                t,d = self.queue.get_nowait()
                if t=='save_and_open':
                    self.save_and_open(d)
                    self.generate_button.config(state=tk.NORMAL)
                    self.status_label.config(text="Ready")
                elif t=='error':
                    show_error_centered(self,"Error",d)
                    self.generate_button.config(state=tk.NORMAL)
                    self.status_label.config(text="Ready")
                elif t=='simulation_done':
                    sel,fp,fm = d
                    if sel == [p for p,v in self.file_vars.items() if v.get()]:
                        tsz = len(unify_line_endings_for_windows(fp))
                        self.file_selected_label.config(text=f"Files selected: {len(sel)} / {self.all_files_count} (Chars: {format_german_thousand_sep(tsz)})")
                        self.selected_files_list_text.config(state='normal')
                        self.selected_files_list_text.delete('1.0',tk.END)
                        ml=30
                        for f in sel:
                            ln = fm.get(f,0)
                            self.selected_files_list_text.insert(tk.END,f"{f} [{format_german_thousand_sep(ln)}]\n")
                            ml = max(ml,len(f)+8)
                        ml = min(ml,120)
                        self.selected_files_list_text.config(width=ml)
                        self.selected_files_list_text.config(state='disabled')
        except queue.Empty: pass
        self.after(100, self.process_queue)

    def save_and_open(self, out):
        ts = datetime.now().strftime("%d.%m.%Y_%H.%M.%S")
        spn = ''.join(c for c in self.current_project if c.isalnum() or c in(' ','_')).rstrip()
        fn = f"{spn}_{ts}.md"
        sd = os.path.dirname(os.path.abspath(__file__))
        od = os.path.join(sd,"output")
        os.makedirs(od,exist_ok=True)
        fp = os.path.join(od,fn)
        try:
            open(fp,'w',encoding='utf-8').write(out)
            open_in_editor(fp)
        except:
            logging.error("%s", traceback.format_exc())
            show_error_centered(self,"Error","Failed to save output.")

    def edit_config(self):
        try:
            cp = os.path.abspath('config.ini')
            open_in_editor(cp)
        except:
            logging.error("%s", traceback.format_exc())
            show_error_centered(None,"Error","Failed to open config.ini.")

    def check_and_auto_blacklist(self, pn, th=50):
        pr = self.projects[pn]
        pt = pr["path"]
        if not os.path.isdir(pt): return
        exbl = pr.get("blacklist",[])
        na=[]
        gp, gk = [], [x.strip() for x in self.settings.get('gitignore_keep',"").split(',') if x.strip()]
        gi = os.path.join(pt,'.gitignore')
        if self.settings.get('respect_gitignore',True) and os.path.isfile(gi): gp = parse_gitignore(gi)
        for r,ds,fs in os.walk(pt):
            ds.sort(); fs.sort()
            rr = os.path.relpath(r,pt).replace("\\","/").strip("/")
            if any(bb.lower() in rr.lower() for bb in exbl if rr): continue
            ff=[]
            for f in fs:
                rp = f"{rr}/{f}".strip("/")
                if match_any_gitignore(rp,gp) and not match_any_keep(rp,gk): continue
                ff.append(f)
            if len(ff)>th and rr and rr.lower() not in [b.lower() for b in exbl]: na.append(rr)
        if na:
            pr["blacklist"]+=na
            pr["blacklist"]=list(dict.fromkeys(pr["blacklist"]))
            save_projects(self.projects)
            if self.current_project==pn:
                msg = f"These directories exceeded {th} files and were blacklisted:\n\n{', '.join(na)}"
                show_info_centered(self,"Auto-Blacklisted",msg)

# Main
# ------------------------------
if __name__ == "__main__":
    try:
        load_config()
        app = CodePromptGeneratorApp()
        app.mainloop()
    except:
        logging.error("%s", traceback.format_exc())
        show_error_centered(None, "Fatal Error", "An unexpected error occurred. See log for details.")