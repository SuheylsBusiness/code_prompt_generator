# File: code_prompt_generator/main.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

import sys, os, logging, traceback, configparser, tkinter as tk, json, threading, hashlib, queue, platform, subprocess, fnmatch, time
from tkinter import filedialog, ttk, simpledialog, scrolledtext
from datetime import datetime

sys.path.extend(['../custom_utility_libs/logging_setup','../custom_utility_libs/openai_utils'])
from setup_logging import setup_logging
setup_logging(log_level=logging.DEBUG, excluded_files=['server.py'])
config = configparser.ConfigParser()
CACHE_DIR = "cache"
def ensure_cache_dir():
    if not os.path.exists(CACHE_DIR): os.makedirs(CACHE_DIR)
PROJECTS_FILE = os.path.join(CACHE_DIR, 'projects.json')
SETTINGS_FILE = os.path.join(CACHE_DIR, 'settings.json')
HISTORY_SELECTION_KEY = "history_selection"
CACHE_EXPIRY_SECONDS = 3600

def load_config():
    if not os.path.exists('config.ini'): show_error_centered(None,"Configuration Error","config.ini file not found."); sys.exit()
    config.read('config.ini')

def load_projects():
    ensure_cache_dir()
    try: return json.load(open(PROJECTS_FILE,'r')) if os.path.exists(PROJECTS_FILE) else {}
    except: logging.error("%s", traceback.format_exc()); return {}

def save_projects(projects):
    ensure_cache_dir()
    try: json.dump(projects, open(PROJECTS_FILE,'w'), indent=4)
    except: logging.error("%s", traceback.format_exc())

def load_settings():
    ensure_cache_dir()
    try: return json.load(open(SETTINGS_FILE,'r')) if os.path.exists(SETTINGS_FILE) else {}
    except: logging.error("%s", traceback.format_exc()); return {}

def save_settings(settings):
    ensure_cache_dir()
    try: json.dump(settings, open(SETTINGS_FILE,'w'), indent=4)
    except: logging.error("%s", traceback.format_exc())

def center_window(win, parent):
    win.update_idletasks()
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
        save_settings(parent.settings)
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
    apply_modal_geometry(w, parent, "InfoDialog")

def show_warning_centered(parent, title, message):
    w = tk.Toplevel()
    w.title(title)
    ttk.Label(w, text=message).pack(padx=20, pady=20)
    b = ttk.Button(w, text="OK", command=w.destroy)
    b.pack(pady=5)
    apply_modal_geometry(w, parent, "WarningDialog")

def show_error_centered(parent, title, message):
    w = tk.Toplevel()
    w.title(title)
    ttk.Label(w, text=message).pack(padx=20, pady=20)
    b = ttk.Button(w, text="OK", command=w.destroy)
    b.pack(pady=5)
    apply_modal_geometry(w, parent, "ErrorDialog")

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
    except: logging.error("%s", traceback.format_exc()); return None

def get_cache_key(selected_files, file_hashes):
    d = ''.join(sorted([f + file_hashes[f] for f in selected_files]))
    return hashlib.md5(d.encode('utf-8')).hexdigest()

def get_cached_output(project_name, cache_key):
    ensure_cache_dir()
    try:
        cf = os.path.join(CACHE_DIR, f'cache_{project_name}.json')
        if not os.path.exists(cf): return None
        c = json.load(open(cf,'r'))
        now_t = time.time()
        stale = []
        for k, v in list(c.items()):
            if not isinstance(v, dict): stale.append(k); continue
            t = v.get('time', 0)
            if now_t - t > CACHE_EXPIRY_SECONDS: stale.append(k)
        for sk in stale: del c[sk]
        json.dump(c, open(cf,'w'), indent=4)
        entry = c.get(cache_key)
        if not isinstance(entry, dict): return None
        return entry.get('data')
    except: logging.error("%s", traceback.format_exc()); return None

def save_cached_output(project_name, cache_key, output):
    ensure_cache_dir()
    try:
        cf = os.path.join(CACHE_DIR, f'cache_{project_name}.json')
        c = json.load(open(cf,'r')) if os.path.exists(cf) else {}
        c[cache_key] = {"time": time.time(), "data": output}
        json.dump(c, open(cf,'w'), indent=4)
    except: logging.error("%s", traceback.format_exc())

def open_in_editor(file_path):
    try:
        if platform.system()=='Windows': os.startfile(file_path)
        elif platform.system()=='Darwin': subprocess.call(('open', file_path))
        else: subprocess.call(('xdg-open', file_path))
    except: logging.error("%s", traceback.format_exc())

def resource_path(relative_path):
    try: return os.path.join(sys._MEIPASS, relative_path)
    except: return os.path.abspath(os.path.join(".", relative_path))

def parse_gitignore(gitignore_path):
    p = []
    try:
        for l in open(gitignore_path,'r'):
            l = l.strip()
            if l and not l.startswith('#'): p.append(l)
    except: logging.error("%s", traceback.format_exc())
    return p

def match_any_gitignore(path_segment, patterns):
    return any(fnmatch.fnmatch(path_segment, x) or fnmatch.fnmatch(os.path.basename(path_segment), x) for x in patterns)

def match_any_keep(path_segment, patterns):
    return any(fnmatch.fnmatch(path_segment, x) or fnmatch.fnmatch(os.path.basename(path_segment), x) for x in patterns)

def path_should_be_ignored(r, rg, gp, gk, bl):
    r2 = r.replace("\\","/")
    if any(b in r2.lower() for b in bl):
        if match_any_keep(r2, gk): return False
        return True
    if rg and match_any_gitignore(r2, gp):
        if match_any_keep(r2, gk): return False
        return True
    return False

def safe_read_file(path):
    try: return open(path,'r',encoding='utf-8',errors='replace').read()
    except: logging.error("%s", traceback.format_exc()); return ""

def format_german_thousand_sep(num):
    return f"{num:,}".replace(",", ".")

def unify_line_endings_for_windows(text):
    return text.replace('\n','\r\n') if platform.system()=='Windows' else text

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

class SettingsDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__()
        self.title("Settings")
        self.parent = parent
        self.create_widgets()
        apply_modal_geometry(self, parent, "SettingsDialog")
    def create_widgets(self):
        ttk.Label(self, text="Prefix:").pack(pady=5)
        self.prefix_entry = ttk.Entry(self, takefocus=True)
        cp = self.parent.projects.get(self.parent.current_project,{})
        self.prefix_entry.insert(0,cp.get("prefix",""))
        self.prefix_entry.pack(fill=tk.X,padx=10)
        ttk.Separator(self,orient='horizontal').pack(fill=tk.X,padx=10,pady=5)
        self.respect_var = tk.BooleanVar(value=self.parent.settings.get('respect_gitignore',True))
        ttk.Checkbutton(self,text="Respect .gitignore",variable=self.respect_var,takefocus=True).pack(pady=5)
        ttk.Label(self, text="Extend/Set Further Items Into .gitignore:").pack(pady=5)
        self.extend_text = scrolledtext.ScrolledText(self, width=60, height=8, takefocus=True)
        self.extend_text.pack(fill=tk.BOTH,padx=10)
        pr = self.parent.projects.get(self.parent.current_project,{})
        lines = []
        for x in pr.get("blacklist",[]): lines.append(x)
        for y in pr.get("keep",[]): lines.append(f"-{y}")
        self.extend_text.insert('1.0',"\n".join(lines))
        ttk.Separator(self,orient='horizontal').pack(fill=tk.X,padx=10,pady=5)
        ttk.Button(self, text="Save", command=self.save_settings, takefocus=True).pack(pady=5)
    def save_settings(self):
        pr = self.parent.projects[self.parent.current_project]
        pr["prefix"] = self.prefix_entry.get().strip()
        self.parent.settings['respect_gitignore'] = self.respect_var.get()
        lines = [l.strip() for l in self.extend_text.get('1.0',tk.END).split('\n') if l.strip()]
        exclude, keep = [], []
        for l in lines:
            if l.startswith('-'): keep.append(l[1:].strip())
            else: exclude.append(l.strip())
        pr["blacklist"] = exclude
        pr["keep"] = keep
        save_projects(self.parent.projects)
        save_settings(self.parent.settings)
        self.destroy()
        self.parent.refresh_files()

class TemplatesDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__()
        self.title("Manage Templates")
        self.parent = parent
        self.settings = parent.settings
        self.templates = self.settings.get("global_templates", {})
        self.template_names = sorted(self.templates.keys())
        self.create_widgets()
        apply_modal_geometry(self, parent, "TemplatesDialog")
        self.select_current_template()
    def create_widgets(self):
        self.last_selected_index = None
        self.template_listbox = tk.Listbox(self, exportselection=False, takefocus=True)
        self.template_listbox.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        for t in self.template_names: self.template_listbox.insert(tk.END, t)
        self.template_listbox.bind('<<ListboxSelect>>', self.on_template_select)
        cf = ttk.Frame(self); cf.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        ttk.Label(cf, text="Template Content:").pack()
        self.template_text = scrolledtext.ScrolledText(cf, height=15, takefocus=True)
        self.template_text.pack(fill=tk.BOTH, expand=True)
        bf = ttk.Frame(cf); bf.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(bf, text="Add New", command=self.add_template, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text="Delete", command=self.delete_template, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text="Save", command=self.save_template, takefocus=True).pack(side=tk.RIGHT, padx=5)
    def select_current_template(self):
        ct = self.parent.template_var.get()
        if ct and ct in self.template_names:
            idx = self.template_names.index(ct)
            self.template_listbox.selection_clear(0, tk.END)
            self.template_listbox.selection_set(idx)
            self.template_listbox.activate(idx)
            self.last_selected_index = idx
            self.on_template_select(None)
        elif self.template_listbox.size()>0:
            self.template_listbox.selection_set(0)
            self.on_template_select(None)
    def on_template_select(self, _):
        s = self.template_listbox.curselection()
        if s:
            i = s[0]
            t = self.template_listbox.get(i)
            self.template_text.delete('1.0',tk.END)
            self.template_text.insert(tk.END,self.templates[t])
            self.last_selected_index = i
        else:
            if self.last_selected_index is not None: self.template_listbox.selection_set(self.last_selected_index)
            elif self.template_listbox.size()>0:
                self.template_listbox.selection_set(0)
                self.last_selected_index=0
                self.on_template_select(None)
    def add_template(self):
        n = simpledialog.askstring("Template Name","Enter template name:")
        if n and n not in self.templates:
            self.templates[n] = ""
            self.template_names = sorted(self.templates.keys())
            self.template_listbox.delete(0, tk.END)
            for t in self.template_names: self.template_listbox.insert(tk.END, t)
            idx = self.template_names.index(n)
            self.template_listbox.selection_clear(0, tk.END)
            self.template_listbox.selection_set(idx)
            self.template_listbox.activate(idx)
            self.last_selected_index = idx
            self.on_template_select(None)
        elif n in self.templates: show_error_centered(self,"Error","Template name already exists.")
        elif not n: show_warning_centered(self,"Warning","Template name cannot be empty.")
    def delete_template(self):
        s = self.template_listbox.curselection()
        if s:
            i = s[0]
            t = self.template_listbox.get(i)
            if show_yesno_centered(self,"Delete Template",f"Are you sure you want to delete '{t}'?"):
                del self.templates[t]
                self.template_names = sorted(self.templates.keys())
                self.template_listbox.delete(0, tk.END)
                for nm in self.template_names: self.template_listbox.insert(tk.END, nm)
                self.template_text.delete('1.0',tk.END)
                self.settings["global_templates"] = self.templates
                save_settings(self.settings)
                if self.template_listbox.size()>0:
                    self.template_listbox.selection_set(0)
                    self.last_selected_index=0
                    self.on_template_select(None)
                else: self.last_selected_index=None
    def save_template(self):
        s = self.template_listbox.curselection()
        if s:
            i = s[0]
            t = self.template_listbox.get(i)
            c = self.template_text.get('1.0',tk.END).rstrip('\n')
            self.templates[t] = c
            self.settings["global_templates"] = self.templates
            save_settings(self.settings)
            self.parent.load_templates()
            self.parent.template_var.set(t)
            self.destroy()

class TextEditorDialog(tk.Toplevel):
    def __init__(self, parent, initial_text="", opened_file=None):
        super().__init__()
        self.title("Text Editor")
        self.opened_file = opened_file
        self.create_widgets()
        if initial_text: self.text_area.insert(tk.END, initial_text)
        apply_modal_geometry(self, parent, "TextEditorDialog")
    def create_widgets(self):
        bf = ttk.Frame(self); bf.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(bf, text='Replace "**', command=self.replace_stars, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text='Remove Duplicates', command=self.remove_duplicates, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text='Sort Alphabetically', command=self.sort_alphabetically, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text='Sort by Length', command=self.sort_by_length, takefocus=True).pack(side=tk.LEFT, padx=5)
        self.text_area = scrolledtext.ScrolledText(self, width=80, height=25, wrap='none')
        self.text_area.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    def update_clipboard(self):
        txt = self.text_area.get('1.0', tk.END)
        self.clipboard_clear()
        self.clipboard_append(txt)
    def replace_stars(self):
        txt = self.text_area.get('1.0', tk.END).replace("**","")
        self.text_area.delete('1.0', tk.END)
        self.text_area.insert(tk.END, txt)
        self.update_clipboard()
    def remove_duplicates(self):
        txt = self.text_area.get('1.0', tk.END).rstrip('\n')
        lines = txt.split('\n')
        seen = set()
        out = []
        for line in lines:
            if line not in seen: seen.add(line); out.append(line)
        self.text_area.delete('1.0', tk.END)
        self.text_area.insert(tk.END, '\n'.join(out))
        self.update_clipboard()
    def sort_alphabetically(self):
        txt = self.text_area.get('1.0', tk.END).rstrip('\n')
        lines = txt.split('\n')
        lines.sort()
        self.text_area.delete('1.0', tk.END)
        self.text_area.insert(tk.END, '\n'.join(lines))
        self.update_clipboard()
    def sort_by_length(self):
        txt = self.text_area.get('1.0', tk.END).rstrip('\n')
        lines = txt.split('\n')
        lines.sort(key=len)
        self.text_area.delete('1.0', tk.END)
        self.text_area.insert(tk.END, '\n'.join(lines))
        self.update_clipboard()

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
    def on_mousewheel(self, event):
        if event.num==4: self.canvas.yview_scroll(-1,"units")
        elif event.num==5: self.canvas.yview_scroll(1,"units")
        else:
            d = int(-1*(event.delta/120)) if platform.system()=='Windows' else int(-1*event.delta)
            self.canvas.yview_scroll(d,"units")
        return "break"
    def create_widgets(self):
        self.canvas = tk.Canvas(self, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.content_frame = ttk.Frame(self.canvas)
        self.canvas.create_window((0,0), window=self.content_frame, anchor='nw')
        self.content_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.bind_mousewheel_events(self.canvas)
        self.load_history()
    def load_history(self):
        hs = self.parent.settings.get(HISTORY_SELECTION_KEY, [])
        usage_sorted = sorted(hs, key=lambda x: x.get("gens",0), reverse=True)
        top_three = usage_sorted[:3]
        all_sorted = sorted(hs, key=lambda x: x.get("timestamp",0), reverse=True)
        lr_frame = ttk.Frame(self.content_frame)
        lr_frame.pack(fill=tk.BOTH, expand=True)
        left_col = ttk.Frame(lr_frame)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,5))
        right_col = ttk.Frame(lr_frame)
        right_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5,0))
        if top_three:
            ttk.Label(left_col, text="Top Three Selection Sets:", style='Info.TLabel').pack(anchor='w', pady=5)
            self.render_sets(top_three, left_col, top_mode=True)
        if all_sorted:
            ttk.Label(right_col, text="All Historical Sets:", style='Info.TLabel').pack(anchor='w', pady=5)
            self.render_sets(all_sorted, right_col, top_mode=False)
    def render_sets(self, sets_list, container, top_mode=False):
        for s in sets_list:
            fr = ttk.Frame(container)
            fr.pack(fill=tk.X, pady=5)
            dt_str = datetime.fromtimestamp(s["timestamp"]).strftime("%d.%m.%Y %H:%M:%S")
            rel_str = get_relative_time_str(s["timestamp"])
            gens = s.get("gens",0)
            lbl_txt = f"{dt_str} ({rel_str}, {gens} gens)" if top_mode else f"{dt_str} ({rel_str})"
            ttk.Label(fr, text=lbl_txt, style='Info.TLabel').pack(anchor='w')
            st = scrolledtext.ScrolledText(fr, width=60, height=4)
            st.pack(fill=tk.X, expand=True, pady=2)
            st.config(state='normal')
            for ff in s["files"]: st.insert(tk.END, f"{ff}\n")
            st.config(state='disabled')
            r_btn = ttk.Button(fr, text="Re-select", command=lambda setdata=s: self.reselect_set(setdata))
            r_btn.pack(fill=tk.X, pady=(1,0))
            r_btn.config(width=10)
            missing = any(ff not in self.parent.file_vars for ff in s["files"])
            if missing: r_btn.config(state=tk.DISABLED)
    def reselect_set(self, s):
        with self.parent.bulk_update_mode():
            for fv in self.parent.file_vars.values(): fv.set(False)
            missing = False
            for ff in s["files"]:
                if ff in self.parent.file_vars: self.parent.file_vars[ff].set(True)
                else: missing = True
        if missing: show_warning_centered(self, "Missing Files", "Some files in this historical set are no longer available.")
        save_settings(self.parent.settings)
        self.destroy()

class OutputFilesDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__()
        self.title("View Outputs")
        apply_modal_geometry(self, parent, "OutputFilesDialog")
        self.parent = parent
        self.files_list = []
        self.create_widgets()
    def create_widgets(self):
        self.list_frame = ttk.Frame(self)
        self.list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.lb = tk.Listbox(self.list_frame, height=15, width=60)
        self.lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(self.list_frame, orient="vertical", command=self.lb.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.lb.configure(yscrollcommand=sb.set)
        self.load_files()
        self.lb.bind("<Double-Button-1>", self.on_file_double_click)
    def load_files(self):
        op_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
        if not os.path.isdir(op_dir): return
        files = sorted(os.listdir(op_dir), key=lambda f: os.path.getmtime(os.path.join(op_dir,f)), reverse=True)
        for f in files:
            fp = os.path.join(op_dir,f)
            if os.path.isfile(fp):
                rt = get_relative_time_str(os.path.getmtime(fp))
                self.lb.insert(tk.END, f"{f} ({rt})")
                self.files_list.append(f)
    def on_file_double_click(self, event):
        sel = self.lb.curselection()
        if not sel: return
        idx = sel[0]
        if idx>=len(self.files_list): return
        fname = self.files_list[idx]
        op_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
        fp = os.path.join(op_dir, fname)
        txt = safe_read_file(fp)
        self.destroy()
        TextEditorDialog(self.parent, initial_text=txt, opened_file=fp)

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
        self.style.configure('Modern.TCheckbutton', background='#F3F3F3')
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
        self.settings.setdefault("global_templates", {})
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
        self.queue = queue.Queue()
        self.settings_dialog = None
        self.simulation_thread = None
        self.simulation_lock = threading.Lock()
        self.selected_files_cache = []
        self.row_frames = {}
        self.bulk_update_active = False
        self.checkbox_toggle_timer = None
        self.loading_thread = None
        self.autoblacklist_thread = None
        self.create_layout()
        self.after(50, self.process_queue)
        lp = self.settings.get('last_selected_project')
        if lp and lp in self.projects: self.project_var.set(lp); self.load_project(lp)
        self.restore_window_geometry()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
    from contextlib import contextmanager
    @contextmanager
    def bulk_update_mode(self):
        self.bulk_update_active = True
        try: yield
        finally:
            self.bulk_update_active = False
            self.on_file_selection_changed()
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
        self.sort_and_set_projects(cb)
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
        self.reset_button = ttk.Button(tf, text="Reset", command=self.reset_selection, takefocus=True)
        self.reset_button.pack(side=tk.LEFT, padx=5)
        self.history_button = ttk.Button(tf, text="History Selection", command=self.open_history_selection, takefocus=True)
        self.history_button.pack(side=tk.RIGHT, padx=5)
        self.file_selected_label = ttk.Label(tf, text="Files selected: 0 / 0 (Chars: 0)", width=40)
        self.file_selected_label.pack(side=tk.LEFT, padx=(10,0))
        self.view_outputs_button = ttk.Button(tf, text="View Outputs", command=self.open_output_files, takefocus=True)
        self.view_outputs_button.pack(side=tk.RIGHT, padx=5)
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
        self.text_editor_button = ttk.Button(c, text="Open Text Editor", command=self.open_text_editor, takefocus=True)
        self.text_editor_button.pack(side=tk.RIGHT, padx=5)
        self.status_label = ttk.Label(c, text="Ready")
        self.status_label.pack(side=tk.RIGHT, padx=5)
    def on_files_mousewheel(self, event):
        if event.num==4: self.files_canvas.yview_scroll(-1,"units")
        elif event.num==5: self.files_canvas.yview_scroll(1,"units")
        else:
            d = int(-1*(event.delta/120)) if platform.system()=='Windows' else int(-1*event.delta)
            self.files_canvas.yview_scroll(d,"units")
        return "break"
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
        if not n.strip(): show_warning_centered(self,"Invalid Name","Cannot create a project with an empty name."); return
        if n in self.projects: show_error_centered(self,"Error",f"Project '{n}' already exists."); return
        self.projects[n] = {"path":dp,"last_files":[],"blacklist":[],"templates":{},"last_template":"","prefix":"","click_counts":{}, "last_usage":time.time(),"usage_count":1,"keep":[]}
        save_projects(self.projects)
        self.sort_and_set_projects(self.project_dropdown)
        self.project_dropdown.set(n)
        self.load_project(n)
    def remove_project(self):
        p = self.project_var.get()
        if not p: show_warning_centered(self,"No Project Selected","Please select a project to remove."); return
        if p not in self.projects: show_warning_centered(self,"Invalid Selection","Project not found."); return
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
            self.sort_and_set_projects(self.project_dropdown)
            if nm:
                self.project_var.set(nm[0])
                self.load_project(nm[0])
            else:
                self.project_var.set("")
                self.file_vars,self.file_hashes={},{}
                for w in self.inner_frame.winfo_children(): w.destroy()
    def on_project_selected(self, _):
        disp = self.project_var.get()
        if ' (' in disp: n = disp.split(' (')[0]
        else: n = disp
        self.load_project(n)
    def load_project(self, n):
        self.current_project = n
        self.settings['last_selected_project'] = n
        save_settings(self.settings)
        p = self.projects[n]
        self.blacklist = p.get("blacklist",[])
        self.templates = self.settings.get("global_templates",{})
        self.click_counts = p.get("click_counts",{})
        self.run_autoblacklist_in_background(n)
        self.load_templates()
        self.load_items_in_background()
    def load_templates(self):
        t = list(self.templates.keys())
        self.template_dropdown['values'] = t
        p = self.projects[self.current_project]
        lt = p.get("last_template","")
        if lt in t: self.template_var.set(lt)
        elif t:
            self.template_var.set(t[0])
            p["last_template"] = t[0]
            save_projects(self.projects)
        else: self.template_var.set("")
        self.on_template_selected(None)
    def on_template_selected(self, _):
        if self.current_project:
            self.projects[self.current_project]["last_template"]=self.template_var.get()
            save_projects(self.projects)
    def load_items_in_background(self):
        if self.loading_thread and self.loading_thread.is_alive(): return
        self.status_label.config(text="Loading...")
        self.loading_thread = threading.Thread(target=self._load_items_worker, daemon=True)
        self.loading_thread.start()
    def _load_items_worker(self):
        if not self.current_project: return
        p = self.projects[self.current_project]
        pt = p["path"]
        if not os.path.isdir(pt):
            self.queue.put(('load_items_done', ("error",None)))
            return
        fi, fc, fe = [], 0, False
        bl_lower = [b.strip().lower() for b in p.get("blacklist",[])]
        gp, gk = [], p.get("keep",[])
        if self.settings.get('respect_gitignore',True):
            gi = os.path.join(pt,'.gitignore')
            if os.path.isfile(gi): gp = parse_gitignore(gi)
        gitignore_skipped_local = []
        for r, ds, fs in os.walk(pt):
            if fc>=self.MAX_FILES: fe=True; break
            ds.sort(); fs.sort()
            rr = os.path.relpath(r,pt).replace("\\","/")
            if rr=="." : rr=""
            rl = rr.count('/') if rr else 0
            if rr: fi.append({"type":"dir","path":rr+"/","level":rl})
            new_ds = []
            for d in ds:
                dr = f"{rr}/{d}".lstrip("/").lower()
                if path_should_be_ignored(dr,self.settings.get('respect_gitignore',True),gp,gk,bl_lower):
                    if os.path.isdir(os.path.join(r,d)) and is_dir_forced_kept(dr,gk): new_ds.append(d)
                    else: gitignore_skipped_local.append(dr)
                    continue
                new_ds.append(d)
            ds[:] = new_ds
            for f in fs:
                if fc>=self.MAX_FILES: fe=True; break
                relp = f"{rr}/{f}".lstrip("/")
                rpl = relp.lower()
                if path_should_be_ignored(rpl,self.settings.get('respect_gitignore',True),gp,gk,bl_lower):
                    gitignore_skipped_local.append(relp)
                    continue
                ap = os.path.join(r,f)
                if not os.path.isfile(ap): continue
                fi.append({"type":"file","path":relp,"level":relp.count('/')})
                fc+=1
            if fe: break
        self.queue.put(('load_items_done', ("ok",(fi,fe,gitignore_skipped_local))))
    def load_items_result(self, data):
        p = self.projects[self.current_project]
        pt = p["path"]
        self.gitignore_skipped = data[2]
        self.all_items = data[0]
        if data[1]: show_warning_centered(self,"File Limit Exceeded",f"Too many files in the project. Only the first {self.MAX_FILES} files are loaded.")
        lf = p.get("last_files",[])
        self.file_vars.clear()
        self.file_hashes.clear()
        self.file_contents.clear()
        self.file_char_counts.clear()
        self.file_labels.clear()
        self.row_frames.clear()
        self.all_files_count = sum(1 for it in self.all_items if it["type"]=="file")
        for it in self.all_items:
            if it["type"]=="file":
                self.file_vars[it["path"]] = tk.BooleanVar(value=(it["path"] in lf))
                self.previous_check_states[it["path"]] = self.file_vars[it["path"]].get()
        for path_var in self.file_vars:
            self.file_vars[path_var].trace_add('write', lambda *a, pv=path_var: self.on_checkbox_toggled(pv))
        self.filter_and_display_items()
        threading.Thread(target=self._load_file_contents_worker, args=(lf,), daemon=True).start()
    def _load_file_contents_worker(self, keep_sel):
        if not self.current_project: return
        p = self.projects[self.current_project]
        pt = p["path"]
        for it in self.all_items:
            if it["type"]=="file":
                rp = it["path"]
                ap = os.path.join(pt,rp)
                if os.path.isfile(ap):
                    fsiz = os.path.getsize(ap)
                    if fsiz<=self.MAX_FILE_SIZE:
                        d = safe_read_file(ap)
                        self.file_contents[rp] = d
                        self.file_char_counts[rp] = len(d)
                    else:
                        self.file_contents[rp], self.file_char_counts[rp] = None,0
        s = [p for p,v in self.file_vars.items() if v.get()]
        if set(s)!=set(keep_sel): self.on_file_selection_changed()
        else: self.run_simulation_in_background(s)
        self.queue.put(('file_contents_loaded', self.current_project))
    def check_and_auto_blacklist(self, pn, th=50):
        pr = self.projects[pn]
        pt = pr["path"]
        if not os.path.isdir(pt): return []
        exbl = pr.get("blacklist",[])
        gp, gk = [], pr.get("keep",[])
        if self.settings.get('respect_gitignore',True):
            gi = os.path.join(pt,'.gitignore')
            if os.path.isfile(gi): gp = parse_gitignore(gi)
        new_blacklisted = []
        for r,ds,fs in os.walk(pt):
            ds.sort(); fs.sort()
            rr = os.path.relpath(r,pt).replace("\\","/").strip("/")
            if any(bb.lower() in rr.lower() for bb in exbl if rr): continue
            ff=[]
            for f in fs:
                rp = f"{rr}/{f}".strip("/")
                if match_any_gitignore(rp,gp) and not match_any_keep(rp,gk): continue
                ff.append(f)
            if len(ff)>th and rr and rr.lower() not in [b.lower() for b in exbl]:
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
        save_projects(self.projects)
        if self.current_project==n: show_info_centered(self,"Auto-Blacklisted",f"These directories exceeded 50 files and were blacklisted:\n\n{', '.join(dirs)}")
    def filter_and_display_items(self):
        for w in self.inner_frame.winfo_children(): w.destroy()
        q = self.file_search_var.get().strip().lower()
        self.filtered_items = [it for it in self.all_items if q in it["path"].lower()] if q else self.all_items
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
                chk = ttk.Checkbutton(rf, variable=self.file_vars[p], style='Modern.TCheckbutton')
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
        self.files_canvas.yview_moveto(0)
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
                save_projects(self.projects)
        self.previous_check_states[f] = new_val
        self.update_row_color(f)
        if self.checkbox_toggle_timer: self.after_cancel(self.checkbox_toggle_timer)
        self.checkbox_toggle_timer = self.after(50, self._delayed_on_checkbox_toggled)
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
                elif isinstance(w, ttk.Checkbutton): w.config(style='Modern.TCheckbutton')
    def reset_selection(self):
        with self.bulk_update_mode():
            self.file_search_var.set("")
            for v in self.file_vars.values(): v.set(False)
    def open_history_selection(self):
        if not self.current_project: show_warning_centered(self,"No Project Selected","Please select a project first."); return
        HistorySelectionDialog(self)
    def open_output_files(self):
        OutputFilesDialog(self)
    def open_text_editor(self):
        TextEditorDialog(self, initial_text="")
    def refresh_files(self):
        if not self.current_project: return
        s = [p for p,v in self.file_vars.items() if v.get()]
        self.load_items_in_background()
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
            self.file_selected_label.config(text=f"Files selected: {c} / 0 (Chars: 0)")
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
        gp, gk = [], pr.get("keep",[])
        if self.settings.get('respect_gitignore',True):
            gi = os.path.join(pt,'.gitignore')
            if os.path.isfile(gi): gp = parse_gitignore(gi)
        dt = self.generate_directory_tree_custom(pt, pr.get('blacklist',[]), self.settings.get('respect_gitignore',True), gp, gk)
        tn = self.template_var.get()
        tc = self.templates.get(tn,"")
        cblocks, tsz = [], 0
        for rp in sel:
            d = self.file_contents.get(rp)
            if not d: continue
            if tsz+len(d)>self.MAX_CONTENT_SIZE: break
            cblocks.append(f"--- {rp} ---\n{d}\n--- {rp} ---\n")
            tsz+=len(d)
        p = tc.replace("{{dirs}}", f"{s1}\n\n{dt.strip()}")
        if "{{files_provided}}" in p:
            lines = "".join(f"- {x}\n" for x in sel if x in self.file_contents and self.file_contents[x] is not None)
            p=p.replace("{{files_provided}}",f"\n\n{s2}\n{lines}".rstrip('\n'))
        else: p=p.replace("{{files_provided}}","")
        fc = f"\n\n{s3}\n\n{''.join(cblocks)}" if cblocks else ""
        return p.replace("{{file_contents}}", fc), cblocks
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
            for d in sorted(dirs_in_this): stack.append((os.path.join(cp,d), cd+1))
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
        with self.bulk_update_mode():
            for i in fi: self.file_vars[i["path"]].set(not all_sel)
    def update_select_all_button(self):
        fi = [x for x in self.filtered_items if x["type"]=="file"]
        if fi:
            if all(self.file_vars[x["path"]].get() for x in fi): self.select_all_button.config(text="Unselect All")
            else: self.select_all_button.config(text="Select All")
        else: self.select_all_button.config(text="Select All")
    def update_file_hashes(self, sf):
        pj = self.projects[self.current_project]
        pt = pj["path"]
        for rp in sf:
            ap = os.path.join(pt,rp)
            self.file_hashes[rp] = get_file_hash(ap)
    def update_file_contents(self, sf):
        pj = self.projects[self.current_project]
        pt = pj["path"]
        for rp in sf:
            ap = os.path.join(pt,rp)
            if os.path.isfile(ap):
                fsz = os.path.getsize(ap)
                if fsz<=self.MAX_FILE_SIZE:
                    d = safe_read_file(ap)
                    self.file_contents[rp] = d
                    self.file_char_counts[rp] = len(d)
                else:
                    self.file_contents[rp], self.file_char_counts[rp] = None,0
    def generate_output(self):
        if self.settings_dialog and self.settings_dialog.winfo_exists(): self.settings_dialog.save_settings()
        if not self.current_project: show_warning_centered(self,"No Project Selected","Please select a project first."); return
        sel = [p for p,v in self.file_vars.items() if v.get()]
        if not sel: show_warning_centered(self,"Warning","No files selected."); return
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
        self.update_file_contents(sel)
        prompt = self.simulate_final_prompt(sel)
        ck = self.make_cache_key_for_prompt(sel,prompt)
        co = get_cached_output(self.current_project, ck)
        if co: self.finalize_generation(co, sel)
        else: threading.Thread(target=self.generate_output_content, args=(prompt,ck,sel), daemon=True).start()
    def make_cache_key_for_prompt(self, sel, prompt):
        s1 = hashlib.md5("".join(sel).encode('utf-8')).hexdigest()
        s2 = hashlib.md5(prompt.encode('utf-8')).hexdigest()
        return s1+s2
    def generate_output_content(self, prompt, ck, sel):
        try:
            save_cached_output(self.current_project, ck, prompt)
            self.queue.put(('save_and_open',(prompt, sel)))
        except: logging.error("%s", traceback.format_exc()); self.queue.put(('error',"Error generating output."))
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
                elif t=='load_items_done':
                    status, data = d
                    if status=="error":
                        show_error_centered(self,"Invalid Path","Project directory does not exist.")
                        self.status_label.config(text="Ready")
                    else:
                        self.load_items_result(data)
                        self.status_label.config(text="Ready")
                elif t=='auto_bl':
                    n, dirs = d
                    self.on_auto_blacklist_done(n, dirs)
                elif t=='file_contents_loaded':
                    if d==self.current_project:
                        for p, lbl in self.file_labels.items():
                            cnt = format_german_thousand_sep(self.file_char_counts.get(p,0))
                            lbl.config(text=f"{os.path.basename(p)} [{cnt}]")
        except queue.Empty: pass
        self.after(50, self.process_queue)
    def finalize_generation(self, out, sel):
        p = self.projects[self.current_project]
        p["last_usage"] = time.time()
        p["usage_count"] = p.get("usage_count",0)+1
        save_projects(self.projects)
        self.sort_and_set_projects(self.project_dropdown)
        self.save_and_open(out)
        self.generate_button.config(state=tk.NORMAL)
        self.status_label.config(text="Ready")
        self.add_history_selection(sel)
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
        except: logging.error("%s", traceback.format_exc()); show_error_centered(self,"Error","Failed to save output.")
    def add_history_selection(self, sel):
        hs = self.settings.get(HISTORY_SELECTION_KEY, [])
        sel_set = set(sel)
        found = None
        for h in hs:
            if set(h["files"])==sel_set: found = h; break
        if found:
            found["gens"] = found.get("gens",0)+1
            found["timestamp"] = time.time()
        else:
            hs.append({"id": hashlib.md5(",".join(sorted(sel)).encode('utf-8')).hexdigest(),"files": sel,"timestamp": time.time(),"gens": 1})
        self.settings[HISTORY_SELECTION_KEY] = hs
        save_settings(self.settings)
    def edit_config(self):
        try: cp = os.path.abspath('config.ini'); open_in_editor(cp)
        except: logging.error("%s", traceback.format_exc()); show_error_centered(None,"Error","Failed to open config.ini.")
    def update_select_all_button(self):
        fi = [x for x in self.filtered_items if x["type"]=="file"]
        if fi:
            if all(self.file_vars[x["path"]].get() for x in fi): self.select_all_button.config(text="Unselect All")
            else: self.select_all_button.config(text="Select All")
        else: self.select_all_button.config(text="Select All")
    def sort_and_set_projects(self, combobox):
        projs = list(self.projects.keys())
        usage_list = []
        for k in projs:
            p = self.projects[k]
            usage_list.append((k, p.get("usage_count",0), p.get("last_usage",0)))
        usage_list.sort(key=lambda x: (-x[1], -x[2]))
        sorted_values = []
        w=0
        for (name, uc, lu) in usage_list:
            ago = get_relative_time_str(lu) if lu>0 else ""
            disp = f"{name} ({ago})" if ago else name
            w = max(w, len(disp))
            sorted_values.append(disp)
        combobox['values'] = sorted_values
        curproj = self.current_project
        found_idx = None
        if curproj:
            for idx, val in enumerate(sorted_values):
                if val.startswith(curproj+" (") or val==curproj: found_idx=idx; break
        if found_idx is not None: combobox.current(found_idx)
        elif sorted_values: combobox.current(0)
        combobox.configure(width=max(w,20))

if __name__=="__main__":
    try:
        load_config()
        app = CodePromptGeneratorApp()
        app.mainloop()
    except:
        logging.error("%s", traceback.format_exc())
        show_error_centered(None, "Fatal Error", "An unexpected error occurred. See log for details.")