# File: code_prompt_generator/main.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

import sys
import os
import logging
import traceback
import configparser
import tkinter as tk
from tkinter import filedialog, ttk, simpledialog, scrolledtext
from datetime import datetime
import json
import threading
import hashlib
import queue
import platform
import subprocess
import fnmatch

sys.path.extend([
    '../custom_utility_libs/logging_setup',
    '../custom_utility_libs/openai_utils',
])

from setup_logging import setup_logging

setup_logging(log_level=logging.DEBUG, blacklisted_files=['server.py'])
config = configparser.ConfigParser()

###############################################################################
#                          CACHE & JSON PATHS SETUP                           #
###############################################################################
CACHE_DIR = "cache"
def ensure_cache_dir():
    if not os.path.exists(CACHE_DIR): os.makedirs(CACHE_DIR)

PROJECTS_FILE = os.path.join(CACHE_DIR, 'projects.json')
SETTINGS_FILE = os.path.join(CACHE_DIR, 'settings.json')

###############################################################################
#                          CONFIG & PROJECTS & SETTINGS                       #
###############################################################################
def load_config():
    if not os.path.exists('config.ini'):
        show_error_centered(None, "Configuration Error", "config.ini file not found.")
        sys.exit()
    config.read('config.ini')

def load_projects():
    ensure_cache_dir()
    try:
        if os.path.exists(PROJECTS_FILE):
            with open(PROJECTS_FILE, 'r') as f: return json.load(f)
        else: return {}
    except:
        logging.error("Error loading projects: %s", traceback.format_exc())
        return {}

def save_projects(projects):
    ensure_cache_dir()
    try:
        with open(PROJECTS_FILE, 'w') as f: json.dump(projects, f, indent=4)
    except:
        logging.error("Error saving projects: %s", traceback.format_exc())

def load_settings():
    ensure_cache_dir()
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f: return json.load(f)
        else: return {}
    except:
        logging.error("Error loading settings: %s", traceback.format_exc())
        return {}

def save_settings(settings):
    ensure_cache_dir()
    try:
        with open(SETTINGS_FILE, 'w') as f: json.dump(settings, f, indent=4)
    except:
        logging.error("Error saving settings: %s", traceback.format_exc())

###############################################################################
#                        CUSTOM CENTERED DIALOG FUNCTIONS                     #
###############################################################################
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
    ttk.Label(w, text=message, style="Info.TLabel").pack(padx=20, pady=20)
    ttk.Button(w, text="OK", command=w.destroy).pack(pady=5)
    center_window(w, parent)
    w.wait_window()

def show_warning_centered(parent, title, message):
    w = tk.Toplevel(parent) if parent else tk.Toplevel()
    w.title(title)
    if parent: w.transient(parent)
    w.grab_set()
    ttk.Label(w, text=message, style="Warning.TLabel").pack(padx=20, pady=20)
    ttk.Button(w, text="OK", command=w.destroy).pack(pady=5)
    center_window(w, parent)
    w.wait_window()

def show_error_centered(parent, title, message):
    w = tk.Toplevel(parent) if parent else tk.Toplevel()
    w.title(title)
    if parent: w.transient(parent)
    w.grab_set()
    ttk.Label(w, text=message, style="Error.TLabel").pack(padx=20, pady=20)
    ttk.Button(w, text="OK", command=w.destroy).pack(pady=5)
    center_window(w, parent)
    w.wait_window()

def show_yesno_centered(parent, title, message):
    w = tk.Toplevel(parent) if parent else tk.Toplevel()
    w.title(title)
    if parent: w.transient(parent)
    w.grab_set()
    result = {"answer": False}
    ttk.Label(w, text=message).pack(padx=20, pady=20)
    def yes():
        result["answer"] = True
        w.destroy()
    def no():
        w.destroy()
    ttk.Button(w, text="Yes", command=yes).pack(side=tk.LEFT, padx=(20, 10), pady=5)
    ttk.Button(w, text="No", command=no).pack(side=tk.RIGHT, padx=(10, 20), pady=5)
    center_window(w, parent)
    w.wait_window()
    return result["answer"]

###############################################################################
#                               FILE HASHES                                   #
###############################################################################
def get_file_hash(file_path):
    try:
        hasher = hashlib.md5()
        with open(file_path, 'rb') as f: hasher.update(f.read())
        mod_time = os.path.getmtime(file_path)
        hasher.update(str(mod_time).encode('utf-8'))
        return hasher.hexdigest()
    except:
        logging.error("Error hashing file: %s", traceback.format_exc())
        return None

def get_cache_key(selected_files, file_hashes):
    data = ''.join(sorted([f + file_hashes[f] for f in selected_files]))
    return hashlib.md5(data.encode('utf-8')).hexdigest()

###############################################################################
#                                CACHE UTILS                                  #
###############################################################################
def get_cached_output(project_name, cache_key):
    ensure_cache_dir()
    try:
        cache_file = os.path.join(CACHE_DIR, f'cache_{project_name}.json')
        if not os.path.exists(cache_file): return None
        with open(cache_file, 'r') as f: cache = json.load(f)
        return cache.get(cache_key)
    except:
        logging.error("Error accessing cache: %s", traceback.format_exc())
        return None

def save_cached_output(project_name, cache_key, output):
    ensure_cache_dir()
    try:
        cache_file = os.path.join(CACHE_DIR, f'cache_{project_name}.json')
        cache = {}
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f: cache = json.load(f)
        cache[cache_key] = output
        with open(cache_file, 'w') as f: json.dump(cache, f, indent=4)
    except:
        logging.error("Error saving to cache: %s", traceback.format_exc())

###############################################################################
#                         OS UTILS AND HELPER FUNCTIONS                       #
###############################################################################
def open_in_editor(file_path):
    try:
        if platform.system() == 'Windows': os.startfile(file_path)
        elif platform.system() == 'Darwin': subprocess.call(('open', file_path))
        else: subprocess.call(('xdg-open', file_path))
    except:
        logging.error("Error opening file: %s", traceback.format_exc())

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def parse_gitignore(gitignore_path):
    patterns = []
    try:
        with open(gitignore_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if line.endswith('/'):
                        logging.debug(f".gitignore directory pattern found: {line}")
                        patterns.append(line)
                        patterns.append(line.rstrip('/'))
                        patterns.append(line.rstrip('/')+'/*')
                    else:
                        patterns.append(line)
    except:
        logging.error("Error reading .gitignore: %s", traceback.format_exc())
    return patterns

def match_any_gitignore(path_segment, patterns):
    for p in patterns:
        if fnmatch.fnmatch(path_segment, p) or fnmatch.fnmatch(os.path.basename(path_segment), p): return True
    return False

def match_any_keep(path_segment, patterns):
    for p in patterns:
        if fnmatch.fnmatch(path_segment, p) or fnmatch.fnmatch(os.path.basename(path_segment), p): return True
    return False

def path_should_be_ignored(rel_path_lower, respect_gitignore, gitignore_patterns, gitignore_keep, blacklisted_lower):
    if any(bl in rel_path_lower for bl in blacklisted_lower): return True
    if respect_gitignore:
        if match_any_gitignore(rel_path_lower, gitignore_patterns) and not match_any_keep(rel_path_lower, gitignore_keep):
            return True
    return False

def generate_directory_tree(startpath, blacklist=None, respect_gitignore=False, gitignore_patterns=None, gitignore_keep=None, max_depth=10, max_lines=1000):
    if blacklist is None: blacklist = []
    if gitignore_patterns is None: gitignore_patterns = []
    if gitignore_keep is None: gitignore_keep = []
    startpath = os.path.normpath(startpath)
    base_depth = startpath.count(os.sep)
    blacklisted_lower = [b.strip().lower() for b in blacklist]
    tree = ""
    line_count = 0
    for root_dir, dirs, files in os.walk(startpath):
        dirs.sort()
        files.sort()
        root_dir = os.path.normpath(root_dir)
        level = root_dir.count(os.sep) - base_depth
        if level > max_depth: continue
        rel_root = os.path.relpath(root_dir, startpath).replace("\\", "/").strip("/")
        if rel_root == ".": rel_root = ""
        keep_dirs = []
        for d in dirs:
            d_rel = f"{rel_root}/{d}".strip("/").lower()
            if not path_should_be_ignored(d_rel, respect_gitignore, gitignore_patterns, gitignore_keep, blacklisted_lower):
                keep_dirs.append(d)
        dirs[:] = keep_dirs
        folder_name = os.path.basename(root_dir) if level > 0 else os.path.basename(startpath)
        indent = '    ' * level
        sub_indent = '    ' * (level + 1)
        tree += f"{indent}{folder_name}/\n"
        line_count += 1
        if line_count >= max_lines: break
        keep_files = []
        for f in files:
            f_rel = f"{rel_root}/{f}".strip("/").lower()
            if not path_should_be_ignored(f_rel, respect_gitignore, gitignore_patterns, gitignore_keep, blacklisted_lower):
                keep_files.append(f)
        for f in keep_files:
            tree += f"{sub_indent}{f}\n"
            line_count += 1
            if line_count >= max_lines: break
        if line_count >= max_lines: break
    if line_count >= max_lines: tree += "... (output truncated due to size limits)\n"
    return tree

def safe_read_file(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f: return f.read()
    except:
        logging.error("Error reading file: %s", traceback.format_exc())
        return ""

###############################################################################
#                              MAIN APPLICATION                               #
###############################################################################
class CodePromptGeneratorApp(tk.Tk):
    MAX_FILES = 500
    def __init__(self):
        super().__init__()
        self.title("Code Prompt Generator - Enhanced UI")
        self.style = ttk.Style(self)
        self.style.theme_use('vista')
        self.style.configure('.', font=('Segoe UI', 10))
        self.style.configure('TFrame', background='SystemButtonFace')
        self.style.configure('TLabel', background='SystemButtonFace', foreground='#000000')
        self.style.configure('TCheckbutton', background='SystemButtonFace', foreground='#000000')
        self.style.configure('ProjectOps.TLabelframe', background='SystemButtonFace', padding=10, foreground='#000000')
        self.style.configure('TemplateOps.TLabelframe', background='SystemButtonFace', padding=10, foreground='#000000')
        self.style.configure('FilesFrame.TLabelframe', background='SystemButtonFace', padding=10, foreground='#000000')
        self.style.configure('Generate.TButton', foreground='#000000', background='SystemButtonFace', padding=8, font=('Segoe UI', 9), borderwidth=0, relief='flat')
        self.style.map('Generate.TButton', background=[('active','SystemButtonFace')], relief=[('pressed','flat'), ('active','flat')])
        self.style.configure('TButton', foreground='#000000', background='SystemButtonFace', padding=6, borderwidth=0, relief='flat')
        self.style.map('TButton', background=[('active','SystemButtonFace')], relief=[('pressed','flat'), ('active','flat')])
        self.style.configure('Warning.TLabel', foreground='#cc6600', background='SystemButtonFace')
        self.style.configure('Error.TLabel', foreground='#c00', background='SystemButtonFace')
        self.style.configure('Info.TLabel', foreground='#0066cc', background='SystemButtonFace')
        self.configure(bg='SystemButtonFace')
        self.icon_path = resource_path('app_icon.ico')
        if os.path.exists(self.icon_path): self.iconbitmap(self.icon_path)
        self.projects = load_projects()
        self.settings = load_settings()
        self.settings.setdefault('respect_gitignore', True)
        self.settings.setdefault('gitignore_keep', "")
        self.gitignore_skipped = []
        self.current_project = None
        self.blacklist = []
        self.templates = {}
        self.file_vars = {}
        self.file_hashes = {}
        self.all_files = []
        self.filtered_files = []
        self.click_counts = {}
        self.previous_check_states = {}
        self.queue = queue.Queue()
        self.settings_dialog = None
        self.create_widgets()
        self.after(100, self.process_queue)
        last_project = self.settings.get('last_selected_project')
        if last_project and last_project in self.projects:
            self.project_var.set(last_project)
            self.load_project(last_project)
        self.restore_window_geometry()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def restore_window_geometry(self):
        geometry = self.settings.get('window_geometry')
        if geometry: self.geometry(geometry)
        else: self.geometry("900x650")

    def on_closing(self):
        self.settings['window_geometry'] = self.geometry()
        save_settings(self.settings)
        self.destroy()

    def create_widgets(self):
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, padx=10, pady=5)
        project_area = ttk.LabelFrame(top_frame, text="Project Operations", style='ProjectOps.TLabelframe')
        project_area.pack(side=tk.LEFT, fill=tk.Y, padx=(0,5))
        ttk.Label(project_area, text="Select Project:").pack(anchor='w', pady=(0, 2))
        self.project_var = tk.StringVar()
        self.project_dropdown = ttk.Combobox(project_area, textvariable=self.project_var, state='readonly', width=20, takefocus=True)
        self.project_dropdown['values'] = list(self.projects.keys())
        self.project_dropdown.bind("<<ComboboxSelected>>", self.on_project_selected)
        self.project_dropdown.pack(anchor='w', pady=(0,5))
        ops_frame = ttk.Frame(project_area)
        ops_frame.pack(anchor='w', pady=(5,0))
        ttk.Button(ops_frame, text="Add Project", command=self.add_project, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(ops_frame, text="Remove Project", command=self.remove_project, takefocus=True).pack(side=tk.LEFT, padx=5)
        template_frame = ttk.LabelFrame(top_frame, text="Template", style='TemplateOps.TLabelframe')
        template_frame.pack(side=tk.RIGHT, fill=tk.Y)
        ttk.Label(template_frame, text="Select Template:").pack(anchor='w', pady=(0, 2))
        self.template_var = tk.StringVar()
        self.template_dropdown = ttk.Combobox(template_frame, textvariable=self.template_var, state='readonly', width=20, takefocus=True)
        self.template_dropdown.bind("<<ComboboxSelected>>", self.on_template_selected)
        self.template_dropdown.pack(anchor='w', pady=(0,5))
        ttk.Button(template_frame, text="Manage Templates", command=self.manage_templates, takefocus=True).pack(anchor='w', pady=5)
        self.file_frame = ttk.LabelFrame(self, text="Project Files", style='FilesFrame.TLabelframe')
        self.file_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(5,0))
        search_frame = ttk.Frame(self.file_frame)
        search_frame.pack(anchor='w', padx=5, pady=(5, 2))
        ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT, padx=(0,5))
        self.file_search_var = tk.StringVar()
        self.file_search_var.trace_add("write", lambda *args: self.filter_and_display_files())
        ttk.Entry(search_frame, textvariable=self.file_search_var, width=25, takefocus=True).pack(side=tk.LEFT)
        toggle_frame = ttk.Frame(self.file_frame)
        toggle_frame.pack(anchor='w', padx=5, pady=(5,2))
        self.select_all_button = ttk.Button(toggle_frame, text="Select All", command=self.toggle_select_all, takefocus=True)
        self.select_all_button.pack(side=tk.LEFT, padx=5)
        self.invert_button = ttk.Button(toggle_frame, text="Invert Selection", command=self.invert_selection, takefocus=True)
        self.invert_button.pack(side=tk.LEFT, padx=5)
        self.file_selected_label = ttk.Label(toggle_frame, text="Files selected: 0 / 0", width=30)
        self.file_selected_label.pack(side=tk.LEFT, padx=(10,0))
        self.scroll_canvas = tk.Canvas(self.file_frame, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.file_frame, orient="vertical", command=self.scroll_canvas.yview)
        self.scroll_canvas.configure(yscrollcommand=self.scrollbar.set)
        self.inner_frame = ttk.Frame(self.scroll_canvas)
        self.inner_frame.bind("<Configure>", lambda e: self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox("all")))
        self.scroll_canvas.create_window((0, 0), window=self.inner_frame, anchor='nw')
        self.scroll_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.scroll_canvas.bind_all("<MouseWheel>", self.on_mousewheel)
        control_frame = ttk.Frame(self)
        control_frame.pack(fill=tk.X, padx=10, pady=5)
        self.generate_button = ttk.Button(control_frame, text="Generate", style='Generate.TButton', width=12, command=self.generate_output, takefocus=True)
        self.generate_button.pack(side=tk.LEFT, padx=5)
        self.refresh_button = ttk.Button(control_frame, text="Refresh Files", style='Generate.TButton', width=12, command=self.refresh_files, takefocus=True)
        self.refresh_button.pack(side=tk.LEFT, padx=5)
        self.settings_button = ttk.Button(control_frame, text="Settings", command=self.open_settings, takefocus=True)
        self.settings_button.pack(side=tk.RIGHT, padx=5)
        self.status_label = ttk.Label(control_frame, text="Ready")
        self.status_label.pack(side=tk.RIGHT, padx=5)

    def on_mousewheel(self, event):
        self.scroll_canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    def add_project(self):
        dir_path = filedialog.askdirectory(title="Select Project Directory")
        if not dir_path: return
        name = os.path.basename(dir_path)
        if not name.strip():
            show_warning_centered(self, "Invalid Name", "Cannot create a project with an empty name.")
            return
        if name in self.projects:
            show_error_centered(self, "Error", f"Project '{name}' already exists.")
            return
        self.projects[name] = {"path": dir_path, "last_files": [], "blacklist": [], "templates": {}, "last_template": "", "prefix": "", "click_counts": {}}
        self.projects[name]["templates"][name] = "Your task is to\n\n{{dirs}}{{files_provided}}{{file_contents}}"
        save_projects(self.projects)
        self.project_dropdown['values'] = list(self.projects.keys())
        self.project_dropdown.set(name)
        self.load_project(name)

    def remove_project(self):
        project_to_remove = self.project_var.get()
        if not project_to_remove:
            show_warning_centered(self, "No Project Selected", "Please select a project to remove.")
            return
        if project_to_remove not in self.projects:
            show_warning_centered(self, "Invalid Selection", "Project not found.")
            return
        if show_yesno_centered(self, "Remove Project", f"Are you sure you want to remove the project '{project_to_remove}'?\nThis action is irreversible."):
            del self.projects[project_to_remove]
            save_projects(self.projects)
            if self.settings.get('last_selected_project') == project_to_remove:
                self.settings['last_selected_project'] = None
                save_settings(self.settings)
            cache_file = os.path.join(CACHE_DIR, f"cache_{project_to_remove}.json")
            if os.path.exists(cache_file):
                try: os.remove(cache_file)
                except: logging.error("Error removing cache file for '%s': %s", project_to_remove, traceback.format_exc())
            if self.current_project == project_to_remove: self.current_project = None
            all_project_names = list(self.projects.keys())
            self.project_dropdown['values'] = all_project_names
            if all_project_names:
                self.project_var.set(all_project_names[0])
                self.load_project(all_project_names[0])
            else:
                self.project_var.set("")
                self.file_vars = {}
                self.file_hashes = {}
                for w in self.inner_frame.winfo_children(): w.destroy()

    def on_project_selected(self, event):
        self.load_project(self.project_var.get())

    def load_project(self, name):
        self.current_project = name
        self.settings['last_selected_project'] = name
        save_settings(self.settings)
        proj = self.projects[name]
        self.blacklist = proj.get("blacklist", [])
        self.templates = proj.get("templates", {})
        self.click_counts = proj.get("click_counts", {})
        self.check_and_auto_blacklist(name)
        self.load_templates()
        self.load_files()

    def load_templates(self):
        templates = list(self.templates.keys())
        self.template_dropdown['values'] = templates
        last_template = self.projects[self.current_project].get("last_template")
        if last_template in templates:
            self.template_var.set(last_template)
        elif templates:
            self.template_var.set(templates[0])
            self.projects[self.current_project]["last_template"] = templates[0]
            save_projects(self.projects)
        else:
            self.template_var.set("")
        self.on_template_selected(None)

    def on_template_selected(self, event):
        if self.current_project:
            self.projects[self.current_project]["last_template"] = self.template_var.get()
            save_projects(self.projects)

    def load_files(self):
        for w in self.inner_frame.winfo_children(): w.destroy()
        self.file_vars = {}
        self.file_hashes = {}
        self.all_files = []
        proj = self.projects[self.current_project]
        path = proj["path"]
        if not os.path.isdir(path):
            show_error_centered(self, "Invalid Path", "Project directory does not exist.")
            return
        file_count = 0
        files_exceeded = False
        blacklisted_lower = [b.strip().lower() for b in proj.get("blacklist", [])]
        self.gitignore_skipped = []
        gitignore_patterns = []
        gitignore_keep = [p.strip() for p in self.settings.get('gitignore_keep', "").split(',') if p.strip()]
        if self.settings.get('respect_gitignore', True):
            git_path = os.path.join(path, '.gitignore')
            if os.path.isfile(git_path): gitignore_patterns = parse_gitignore(git_path)
        for root, dirs, files in os.walk(path):
            dirs.sort()
            files.sort()
            rel_root = os.path.relpath(root, path).replace("\\", "/")
            if rel_root == ".": rel_root = ""
            filtered_dirs = []
            for d in dirs:
                test_dir_path = f"{rel_root}/{d}".strip("/").lower()
                if any(bl in test_dir_path for bl in blacklisted_lower): continue
                if self.settings.get('respect_gitignore', True) and match_any_gitignore(d, gitignore_patterns) and not match_any_keep(d, gitignore_keep):
                    self.gitignore_skipped.append(d)
                    continue
                filtered_dirs.append(d)
            dirs[:] = filtered_dirs
            for file in files:
                if file_count >= self.MAX_FILES:
                    files_exceeded = True
                    break
                rel_file_path = f"{rel_root}/{file}".strip("/")
                rel_file_path_lower = rel_file_path.lower()
                if any(bl in rel_file_path_lower for bl in blacklisted_lower): continue
                if self.settings.get('respect_gitignore', True) and match_any_gitignore(rel_file_path, gitignore_patterns) and not match_any_keep(rel_file_path, gitignore_keep):
                    self.gitignore_skipped.append(rel_file_path)
                    continue
                abs_path = os.path.join(root, file)
                if not os.path.isfile(abs_path): continue
                self.all_files.append(rel_file_path)
                file_count += 1
            if files_exceeded: break
        if files_exceeded:
            show_warning_centered(self, "File Limit Exceeded", f"Too many files in the project. Only the first {self.MAX_FILES} files are loaded.")
        last_files = proj.get("last_files", [])
        for f in self.all_files: self.file_hashes[f] = get_file_hash(os.path.join(path, f))
        self.file_vars = {f: tk.BooleanVar(value=(f in last_files)) for f in self.all_files}
        for v in self.file_vars.values():
            v.trace_add('write', self.on_file_selection_changed)
        self.filter_and_display_files()

    def filter_and_display_files(self):
        for w in self.inner_frame.winfo_children(): w.destroy()
        query = self.file_search_var.get().strip().lower()
        self.filtered_files = [f for f in self.all_files if query in f.lower()] if query else self.all_files
        for f in self.filtered_files:
            count = self.click_counts.get(f, 0)
            row_frame = tk.Frame(self.inner_frame, bg=self.get_gradient_color(count))
            row_frame.pack(fill=tk.X, anchor='w')
            indent_level = f.count('/')
            indent_str = '    ' * indent_level
            cbtn = tk.Checkbutton(row_frame, text=f"{indent_str}{f}", variable=self.file_vars[f], bg=row_frame['bg'], anchor='w', command=lambda ff=f, rf=row_frame: self.on_checkbox_click(ff, rf))
            cbtn.pack(side=tk.LEFT, padx=5)
        selected_count = sum(v.get() for v in self.file_vars.values())
        self.file_selected_label.config(text=f"Files selected: {selected_count} / {len(self.all_files)}")
        self.update_select_all_button()
        self.scroll_canvas.yview_moveto(0)

    def on_checkbox_click(self, f, row_frame):
        old_val = self.previous_check_states.get(f, False)
        new_val = self.file_vars[f].get()
        if not old_val and new_val:
            self.click_counts[f] = min(self.click_counts.get(f, 0) + 1, 100)
            color = self.get_gradient_color(self.click_counts[f])
            row_frame.config(bg=color)
            for c in row_frame.winfo_children(): c.config(bg=color)
            if self.current_project:
                self.projects[self.current_project]['click_counts'] = self.click_counts
                save_projects(self.projects)
        self.previous_check_states[f] = new_val
        self.on_file_selection_changed()

    def refresh_files(self):
        selected_files = {f for f, var in self.file_vars.items() if var.get()}
        self.load_files()
        for f, var in self.file_vars.items():
            if f in selected_files: var.set(True)

    def open_settings(self):
        if self.current_project:
            if self.settings_dialog and self.settings_dialog.winfo_exists():
                self.settings_dialog.destroy()
            self.settings_dialog = SettingsDialog(self)
        else:
            show_warning_centered(self, "No Project Selected", "Please select a project first.")

    def manage_templates(self):
        if self.current_project: TemplatesDialog(self)
        else: show_warning_centered(self, "No Project Selected", "Please select a project first.")

    def generate_output(self):
        if self.settings_dialog and self.settings_dialog.winfo_exists():
            self.settings_dialog.save_settings()
        if not self.current_project:
            show_warning_centered(self, "No Project Selected", "Please select a project first.")
            return
        selected = [f for f, v in self.file_vars.items() if v.get()]
        if not selected:
            show_warning_centered(self, "Warning", "No files selected.")
            return
        if len(selected) > self.MAX_FILES:
            show_warning_centered(self, "Warning", f"You have selected {len(selected)} files. Maximum allowed is {self.MAX_FILES}.")
            return
        if not self.template_var.get():
            show_warning_centered(self, "Warning", "No template selected.")
            return
        proj = self.projects[self.current_project]
        if not os.path.isdir(proj["path"]):
            show_error_centered(self, "Invalid Path", "Project directory does not exist.")
            return
        self.generate_button.config(state=tk.DISABLED)
        self.status_label.config(text="Generating...")
        proj["last_files"] = selected
        proj["last_template"] = self.template_var.get()
        save_projects(self.projects)
        self.update_file_hashes(selected)
        gitignore_patterns = []
        gitignore_keep = [p.strip() for p in self.settings.get('gitignore_keep', "").split(',') if p.strip()]
        if self.settings.get('respect_gitignore', True):
            git_path = os.path.join(proj["path"], '.gitignore')
            if os.path.isfile(git_path): gitignore_patterns = parse_gitignore(git_path)
        dir_tree = generate_directory_tree(
            startpath=proj["path"],
            blacklist=proj.get("blacklist", []),
            respect_gitignore=self.settings.get('respect_gitignore', True),
            gitignore_patterns=gitignore_patterns,
            gitignore_keep=gitignore_keep,
            max_depth=10,
            max_lines=1000
        )
        dir_tree_hash = hashlib.md5(dir_tree.encode('utf-8')).hexdigest()
        cache_key = get_cache_key(selected, self.file_hashes) + dir_tree_hash
        cached_output = get_cached_output(self.current_project, cache_key)
        if cached_output:
            self.save_and_open(cached_output)
            self.generate_button.config(state=tk.NORMAL)
            self.status_label.config(text="Ready")
        else:
            threading.Thread(target=self.generate_output_content, args=(selected, cache_key, dir_tree)).start()

    def on_file_selection_changed(self, *args):
        selected_count = sum(v.get() for v in self.file_vars.values())
        self.file_selected_label.config(text=f"Files selected: {selected_count} / {len(self.all_files)}")
        if self.current_project:
            proj = self.projects[self.current_project]
            proj["last_files"] = [f for f, v in self.file_vars.items() if v.get()]
            save_projects(self.projects)
        self.update_select_all_button()

    def toggle_select_all(self):
        if not self.filtered_files: return
        all_selected = all(self.file_vars[f].get() for f in self.filtered_files)
        new_state = not all_selected
        for f in self.filtered_files: self.file_vars[f].set(new_state)
        self.update_select_all_button()

    def invert_selection(self):
        if not self.filtered_files: return
        for f in self.filtered_files:
            self.file_vars[f].set(not self.file_vars[f].get())
        self.update_select_all_button()

    def update_select_all_button(self):
        if self.filtered_files:
            if all(self.file_vars[f].get() for f in self.filtered_files):
                self.select_all_button.config(text="Unselect All")
            else:
                self.select_all_button.config(text="Select All")
        else:
            self.select_all_button.config(text="Select All")

    def update_file_hashes(self, selected_files):
        proj = self.projects[self.current_project]
        path = proj["path"]
        for rel_path in selected_files:
            abs_path = os.path.join(path, rel_path)
            old_hash = self.file_hashes.get(rel_path)
            new_hash = get_file_hash(abs_path)
            self.file_hashes[rel_path] = new_hash
            logging.debug(f"File {rel_path}: old_hash={old_hash}, new_hash={new_hash}")

    def generate_output_content(self, selected, cache_key, dir_tree):
        try:
            proj = self.projects[self.current_project]
            path = proj["path"]
            proj_prefix = proj.get("prefix", "").strip()
            if proj_prefix:
                title_fs = f"### {proj_prefix} File Structure"
                title_fp = f"### {proj_prefix} Code Files provided"
                title_cf = f"### {proj_prefix} Code Files"
            else:
                title_fs = "### File Structure"
                title_fp = "### Code Files provided"
                title_cf = "### Code Files"
            MAX_CONTENT_SIZE = 2000000
            MAX_FILE_SIZE = 500000
            total_size = 0
            content_blocks = []
            for rel_path in selected:
                abs_path = os.path.join(path, rel_path)
                if not os.path.isfile(abs_path): continue
                file_size = os.path.getsize(abs_path)
                if file_size > MAX_FILE_SIZE: continue
                if total_size + file_size > MAX_CONTENT_SIZE: break
                file_data = safe_read_file(abs_path)
                total_size += file_size
                block = f"--- {rel_path} ---\n{file_data}\n--- {rel_path} ---\n"
                content_blocks.append(block)
            if not content_blocks:
                self.queue.put(('error', "No file content to process."))
                return
            files_content_str = "\n".join(content_blocks).strip()
            template_name = self.template_var.get()
            template_content = self.templates[template_name]
            prompt = template_content.replace("{{dirs}}", f"{title_fs}\n\n{dir_tree.strip()}")
            if "{{files_provided}}" in prompt:
                files_provided_text = f"\n\n{title_fp}\n" + "".join(f"- {sf}\n" for sf in selected)
                prompt = prompt.replace("{{files_provided}}", files_provided_text.rstrip('\n'))
            else:
                prompt = prompt.replace("{{files_provided}}", "")
            file_contents_text = f"\n\n{title_cf}\n\n{files_content_str}"
            prompt = prompt.replace("{{file_contents}}", file_contents_text.rstrip('\n'))
            save_cached_output(self.current_project, cache_key, prompt)
            self.queue.put(('save_and_open', prompt))
        except:
            logging.error("Generation error: %s", traceback.format_exc())
            self.queue.put(('error', "Error generating output."))

    def process_queue(self):
        try:
            while True:
                task, data = self.queue.get_nowait()
                if task == 'save_and_open': self.save_and_open(data)
                elif task == 'error': show_error_centered(self, "Error", data)
                self.generate_button.config(state=tk.NORMAL)
                self.status_label.config(text="Ready")
        except queue.Empty:
            pass
        finally:
            self.after(100, self.process_queue)

    def save_and_open(self, output):
        ts = datetime.now().strftime("%d.%m.%Y_%H.%M.%S")
        safe_project_name = ''.join(c for c in self.current_project if c.isalnum() or c in (' ', '_')).rstrip()
        fname = f"{safe_project_name}_{ts}.md"
        script_dir = os.path.dirname(os.path.abspath(__file__))
        out_dir = os.path.join(script_dir, "output")
        os.makedirs(out_dir, exist_ok=True)
        fpath = os.path.join(out_dir, fname)
        try:
            with open(fpath, 'w', encoding='utf-8') as f: f.write(output)
            open_in_editor(fpath)
        except:
            logging.error("Error saving output: %s", traceback.format_exc())
            show_error_centered(self, "Error", "Failed to save output.")

    def edit_config(self):
        try:
            config_path = os.path.abspath('config.ini')
            open_in_editor(config_path)
        except:
            logging.error("Error opening config.ini: %s", traceback.format_exc())
            show_error_centered(None, "Error", "Failed to open config.ini.")

    def check_and_auto_blacklist(self, project_name, threshold=50):
        proj = self.projects[project_name]
        path = proj["path"]
        if not os.path.isdir(path): return
        existing_bl = proj.get("blacklist", [])
        newly_added = []
        gitignore_patterns = []
        gitignore_keep = [p.strip() for p in self.settings.get('gitignore_keep', "").split(',') if p.strip()]
        git_path = os.path.join(path, '.gitignore')
        if self.settings.get('respect_gitignore', True) and os.path.isfile(git_path):
            gitignore_patterns = parse_gitignore(git_path)
        for root, dirs, files in os.walk(path):
            dirs.sort()
            files.sort()
            rel_root = os.path.relpath(root, path).replace("\\", "/").strip("/")
            if any(bl.lower() in rel_root.lower() for bl in existing_bl if rel_root): continue
            filtered_files = []
            for f in files:
                rel_fp = f"{rel_root}/{f}".strip("/")
                if match_any_gitignore(rel_fp, gitignore_patterns) and not match_any_keep(rel_fp, gitignore_keep): continue
                filtered_files.append(f)
            if len(filtered_files) > threshold:
                if rel_root and rel_root.lower() not in [b.lower() for b in existing_bl]: newly_added.append(rel_root)
        if newly_added:
            proj["blacklist"].extend(newly_added)
            proj["blacklist"] = list(dict.fromkeys(proj["blacklist"]))
            save_projects(self.projects)
            if self.current_project == project_name:
                msg = f"These directories exceeded {threshold} files and were blacklisted:\n\n{', '.join(newly_added)}"
                show_info_centered(self, "Auto-Blacklisted", msg)

    def get_gradient_color(self, count):
        fraction = min(1, count/100)
        r1, g1, b1 = 255, 255, 255
        r2, g2, b2 = 135, 206, 235
        r = int(r1 + (r2 - r1)*fraction)
        g = int(g1 + (g2 - g1)*fraction)
        b = int(b1 + (b2 - b1)*fraction)
        return f"#{r:02x}{g:02x}{b:02x}"

###############################################################################
#                              SETTINGS DIALOG                                #
###############################################################################
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
        parent_x = self.parent.winfo_rootx()
        parent_y = self.parent.winfo_rooty()
        parent_width = self.parent.winfo_width()
        parent_height = self.parent.winfo_height()
        width = self.winfo_width()
        height = self.winfo_height()
        x = parent_x + (parent_width // 2) - (width // 2)
        y = parent_y + (parent_height // 2) - (height // 2)
        self.geometry(f"+{x}+{y}")

    def create_widgets(self):
        ttk.Label(self, text="Blacklisted Folders/Files (comma-separated):").pack(pady=5)
        self.blacklist_entry = ttk.Entry(self, takefocus=True)
        self.blacklist_entry.insert(0, ','.join(self.parent.blacklist))
        self.blacklist_entry.pack(fill=tk.X, padx=10)
        ttk.Separator(self, orient='horizontal').pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(self, text="Prefix:").pack(pady=5)
        self.prefix_entry = ttk.Entry(self, takefocus=True)
        current_proj = self.parent.projects.get(self.parent.current_project, {})
        self.prefix_entry.insert(0, current_proj.get("prefix", ""))
        self.prefix_entry.pack(fill=tk.X, padx=10)
        ttk.Separator(self, orient='horizontal').pack(fill=tk.X, padx=10, pady=5)
        self.respect_var = tk.BooleanVar(value=self.parent.settings.get('respect_gitignore', True))
        self.chk_gitignore = ttk.Checkbutton(self, text="Respect .gitignore", variable=self.respect_var, takefocus=True)
        self.chk_gitignore.pack(pady=5)
        ttk.Label(self, text="Gitignore Keep Patterns (comma-separated):").pack(pady=5)
        self.keepignore_entry = ttk.Entry(self, takefocus=True)
        self.keepignore_entry.insert(0, self.parent.settings.get('gitignore_keep', ""))
        self.keepignore_entry.pack(fill=tk.X, padx=10)
        ttk.Separator(self, orient='horizontal').pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(self, text="Excluded by .gitignore (info only):").pack(pady=5)
        self.excluded_text = ttk.Entry(self, state='readonly')
        excluded_joined = ', '.join(self.parent.gitignore_skipped) if self.parent.gitignore_skipped else ""
        self.excluded_text.config(state='normal')
        self.excluded_text.delete(0, tk.END)
        self.excluded_text.insert(0, excluded_joined)
        self.excluded_text.config(state='readonly')
        self.excluded_text.pack(fill=tk.X, padx=10)
        ttk.Separator(self, orient='horizontal').pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(self, text="Save", command=self.save_settings, takefocus=True).pack(pady=5)

    def save_settings(self):
        blacklist = [b.strip().lower() for b in self.blacklist_entry.get().split(',') if b.strip()]
        proj = self.parent.projects[self.parent.current_project]
        proj["blacklist"] = blacklist
        self.parent.blacklist = blacklist
        prefix = self.prefix_entry.get().strip()
        proj["prefix"] = prefix
        self.parent.settings['respect_gitignore'] = self.respect_var.get()
        self.parent.settings['gitignore_keep'] = self.keepignore_entry.get()
        save_projects(self.parent.projects)
        save_settings(self.parent.settings)
        self.destroy()
        self.parent.refresh_files()

###############################################################################
#                             TEMPLATES DIALOG                                #
###############################################################################
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
        parent_x = self.parent.winfo_rootx()
        parent_y = self.parent.winfo_rooty()
        parent_width = self.parent.winfo_width()
        parent_height = self.parent.winfo_height()
        width = self.winfo_width()
        height = self.winfo_height()
        x = parent_x + (parent_width // 2) - (width // 2)
        y = parent_y + (parent_height // 2) - (height // 2)
        self.geometry(f"+{x}+{y}")

    def create_widgets(self):
        self.last_selected_index = None
        self.template_listbox = tk.Listbox(self, exportselection=False, takefocus=True)
        self.template_listbox.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        for template_name in self.templates: self.template_listbox.insert(tk.END, template_name)
        self.template_listbox.bind('<<ListboxSelect>>', self.on_template_select)
        content_frame = ttk.Frame(self)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        ttk.Label(content_frame, text="Template Content:").pack()
        self.template_text = scrolledtext.ScrolledText(content_frame, height=15, takefocus=True)
        self.template_text.pack(fill=tk.BOTH, expand=True)
        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(button_frame, text="Add New", command=self.add_template, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Delete", command=self.delete_template, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Save", command=self.save_template, takefocus=True).pack(side=tk.RIGHT, padx=5)
        if self.template_listbox.size() > 0:
            self.template_listbox.selection_set(0)
            self.on_template_select(None)

    def on_template_select(self, event):
        selection = self.template_listbox.curselection()
        if selection:
            index = selection[0]
            self.last_selected_index = index
            template_name = self.template_listbox.get(index)
            self.template_text.delete('1.0', tk.END)
            self.template_text.insert(tk.END, self.templates[template_name])
        else:
            if self.last_selected_index is not None:
                self.template_listbox.selection_set(self.last_selected_index)
            else:
                if self.template_listbox.size() > 0:
                    self.template_listbox.selection_set(0)
                    self.last_selected_index = 0
                    self.on_template_select(None)

    def add_template(self):
        name = simpledialog.askstring("Template Name", "Enter template name:", parent=self)
        if name and name not in self.templates:
            self.templates[name] = ""
            self.template_listbox.insert(tk.END, name)
            self.template_listbox.select_clear(0, tk.END)
            self.template_listbox.selection_set(tk.END)
            self.on_template_select(None)
        elif name in self.templates:
            show_error_centered(self, "Error", "Template name already exists.")
        elif not name:
            show_warning_centered(self, "Warning", "Template name cannot be empty.")

    def delete_template(self):
        selection = self.template_listbox.curselection()
        if selection:
            index = selection[0]
            template_name = self.template_listbox.get(index)
            if show_yesno_centered(self, "Delete Template", f"Are you sure you want to delete '{template_name}'?"):
                del self.templates[template_name]
                self.template_listbox.delete(index)
                self.template_text.delete('1.0', tk.END)
                self.parent.projects[self.parent.current_project]["templates"] = self.templates
                save_projects(self.parent.projects)
                self.parent.load_templates()
                if self.template_listbox.size() > 0:
                    self.template_listbox.selection_set(0)
                    self.on_template_select(None)
                else: self.last_selected_index = None

    def save_template(self):
        selection = self.template_listbox.curselection()
        if selection:
            index = selection[0]
            template_name = self.template_listbox.get(index)
            content = self.template_text.get('1.0', tk.END).rstrip('\n')
            self.templates[template_name] = content
            self.parent.projects[self.parent.current_project]["templates"] = self.templates
            save_projects(self.parent.projects)
            self.parent.load_templates()
            self.destroy()

###############################################################################
#                                  MAIN                                       #
###############################################################################
if __name__ == "__main__":
    try:
        load_config()
        app = CodePromptGeneratorApp()
        app.mainloop()
    except:
        logging.error("Unhandled exception: %s", traceback.format_exc())
        show_error_centered(None, "Fatal Error", "An unexpected error occurred. See log for details.")
