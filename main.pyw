# Filename: main.py
# Foldername: code_prompt_generator

import sys
import os
import logging
import traceback
import configparser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, simpledialog
from tkinter import scrolledtext
from datetime import datetime
import json
import threading
import hashlib
import queue
import platform
import subprocess

# Extend system path with custom utility libraries
sys.path.extend([
    '../custom_utility_libs/logging_setup',
    '../custom_utility_libs/google_sheets_module',
    '../custom_utility_libs/openai_utils',
    '../custom_utility_libs/gmail_module',
])

# Import custom modules
from setup_logging import setup_logging
from gmail_utils import get_service, create_message, send_message
from google_sheets_utils import (
    initialize_google_sheet,
    read_spreadsheet,
    append_to_spreadsheet_top,
    update_spreadsheet,
    fetch_sheet_headers
)

# Initialize logging and configuration
setup_logging(log_level=logging.DEBUG, blacklisted_files=['server.py'])
config = configparser.ConfigParser()

###############################################################################
#                          CACHE & JSON PATHS SETUP                           #
###############################################################################
CACHE_DIR = "cache"
def ensure_cache_dir():
    """Ensure the cache directory exists."""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

# Build file paths in the 'cache' folder
PROJECTS_FILE = os.path.join(CACHE_DIR, 'projects.json')
SETTINGS_FILE = os.path.join(CACHE_DIR, 'settings.json')

###############################################################################
#                          CONFIG & PROJECTS & SETTINGS                       #
###############################################################################
def load_config():
    if not os.path.exists('config.ini'):
        messagebox.showerror("Configuration Error", "config.ini file not found.")
        sys.exit()
    config.read('config.ini')

def load_projects():
    ensure_cache_dir()
    try:
        if os.path.exists(PROJECTS_FILE):
            with open(PROJECTS_FILE, 'r') as f:
                return json.load(f)
        else:
            return {}
    except Exception:
        logging.error("Error loading projects: %s", traceback.format_exc())
        return {}

def save_projects(projects):
    ensure_cache_dir()
    try:
        with open(PROJECTS_FILE, 'w') as f:
            json.dump(projects, f, indent=4)
    except Exception:
        logging.error("Error saving projects: %s", traceback.format_exc())

def load_settings():
    ensure_cache_dir()
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        else:
            return {}
    except Exception:
        logging.error("Error loading settings: %s", traceback.format_exc())
        return {}

def save_settings(settings):
    ensure_cache_dir()
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
    except Exception:
        logging.error("Error saving settings: %s", traceback.format_exc())

###############################################################################
#                               FILE HASHES                                   #
###############################################################################
def get_file_hash(file_path):
    try:
        hasher = hashlib.md5()
        with open(file_path, 'rb') as f:
            buf = f.read()
            hasher.update(buf)
        # Include the modification time in the hash
        mod_time = os.path.getmtime(file_path)
        hasher.update(str(mod_time).encode('utf-8'))
        return hasher.hexdigest()
    except Exception:
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
        if not os.path.exists(cache_file):
            return None
        with open(cache_file, 'r') as f:
            cache = json.load(f)
        return cache.get(cache_key)
    except Exception:
        logging.error("Error accessing cache: %s", traceback.format_exc())
        return None

def save_cached_output(project_name, cache_key, output):
    ensure_cache_dir()
    try:
        cache_file = os.path.join(CACHE_DIR, f'cache_{project_name}.json')
        cache = {}
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                cache = json.load(f)
        cache[cache_key] = output
        with open(cache_file, 'w') as f:
            json.dump(cache, f, indent=4)
    except Exception:
        logging.error("Error saving to cache: %s", traceback.format_exc())

###############################################################################
#                         OS UTILS AND HELPER FUNCTIONS                       #
###############################################################################
def open_in_editor(file_path):
    try:
        if platform.system() == 'Windows':
            os.startfile(file_path)
        elif platform.system() == 'Darwin':
            subprocess.call(('open', file_path))
        else:
            subprocess.call(('xdg-open', file_path))
    except Exception:
        logging.error("Error opening file: %s", traceback.format_exc())

def resource_path(relative_path):
    """Get absolute path to resource, works for development and PyInstaller."""
    try:
        base_path = sys._MEIPASS  # PyInstaller temporary folder
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def generate_directory_tree(startpath, blacklist=None, max_depth=10, max_lines=1000):
    """
    Generate a visual tree of folders and files, skipping those whose
    relative path matches any entry in 'blacklist' (case-insensitive).
    """
    if blacklist is None:
        blacklist = ["__pycache__", "node_modules", ".git"]
    else:
        # Clean up and lowercase all blacklisted entries
        blacklist = [b.strip().lower() for b in blacklist]

    tree = ""
    line_count = 0

    for root_dir, dirs, files in os.walk(startpath):
        # Compute the relative path from startpath
        rel_root = os.path.relpath(root_dir, startpath).replace("\\", "/")
        if rel_root == ".":
            rel_root = ""

        # Filter out dirs if any blacklisted string is contained
        filtered_dirs = []
        for d in dirs:
            test_path = f"{rel_root}/{d}".strip("/").lower()
            if not any(bl in test_path for bl in blacklist):
                filtered_dirs.append(d)
        dirs[:] = filtered_dirs

        # If we've gone too deep, continue
        level = rel_root.count("/") if rel_root else 0
        if level > max_depth:
            continue

        indent = '    ' * level
        sub_indent = '    ' * (level + 1)

        # Add the folder name
        folder_name = os.path.basename(root_dir) if rel_root else os.path.basename(startpath)
        tree += f"{indent}{folder_name}/\n"
        line_count += 1
        if line_count >= max_lines:
            break

        # Filter out files if any blacklisted string is contained
        for f in files:
            test_file_path = f"{rel_root}/{f}".strip("/").lower()
            if any(bl in test_file_path for bl in blacklist):
                continue

            tree += f"{sub_indent}{f}\n"
            line_count += 1
            if line_count >= max_lines:
                break
        if line_count >= max_lines:
            break

    if line_count >= max_lines:
        tree += "... (output truncated due to size limits)\n"

    return tree

###############################################################################
#                              MAIN APPLICATION                               #
###############################################################################
class CodePromptGeneratorApp(tk.Tk):
    MAX_FILES = 500

    def __init__(self):
        super().__init__()
        self.title("Code Prompt Generator")
        self.icon_path = resource_path('app_icon.ico')
        if os.path.exists(self.icon_path):
            self.iconbitmap(self.icon_path)
        self.projects = load_projects()
        self.settings = load_settings()
        self.current_project = None
        self.blacklist = []
        self.templates = {}
        self.file_vars = {}
        self.file_hashes = {}
        self.queue = queue.Queue()
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
        if geometry:
            self.geometry(geometry)
        else:
            self.geometry("900x650")

    def on_closing(self):
        self.settings['window_geometry'] = self.geometry()
        save_settings(self.settings)
        self.destroy()

    def create_widgets(self):
        # Menu Bar
        self.create_menu_bar()

        # Project Selection Frame
        project_frame = ttk.Frame(self)
        project_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(project_frame, text="Select Project:").pack(side=tk.LEFT)
        self.project_var = tk.StringVar()
        self.project_dropdown = ttk.Combobox(
            project_frame, textvariable=self.project_var, state='readonly', width=20
        )
        self.project_dropdown['values'] = list(self.projects.keys())
        self.project_dropdown.bind("<<ComboboxSelected>>", self.on_project_selected)
        self.project_dropdown.pack(side=tk.LEFT, padx=5)

        ttk.Button(project_frame, text="Add Project", command=self.add_project).pack(side=tk.LEFT, padx=5)
        ttk.Button(project_frame, text="Settings", command=self.open_settings).pack(side=tk.LEFT, padx=5)

        # Template Selection
        ttk.Label(project_frame, text="Select Template:").pack(side=tk.LEFT, padx=20)
        self.template_var = tk.StringVar()
        self.template_dropdown = ttk.Combobox(
            project_frame, textvariable=self.template_var, state='readonly', width=20
        )
        self.template_dropdown.bind("<<ComboboxSelected>>", self.on_template_selected)
        self.template_dropdown.pack(side=tk.LEFT, padx=5)

        ttk.Button(project_frame, text="Manage Templates", command=self.manage_templates).pack(side=tk.LEFT, padx=5)

        # File Selection Frame
        self.file_frame = ttk.LabelFrame(self, text="Select Files to Include")
        self.file_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Add Select/Unselect All button
        toggle_frame = ttk.Frame(self.file_frame)
        toggle_frame.pack(anchor='w', padx=5, pady=5)
        self.select_all_button = ttk.Button(toggle_frame, text="Select All", command=self.toggle_select_all)
        self.select_all_button.pack(side=tk.LEFT, padx=5)

        # Control Buttons Frame
        control_frame = ttk.Frame(self)
        control_frame.pack(fill=tk.X, padx=10, pady=5)

        self.generate_button = ttk.Button(control_frame, text="Generate", command=self.generate_output)
        self.generate_button.pack(side=tk.LEFT, padx=5)

        ttk.Button(control_frame, text="Refresh Files", command=self.refresh_files).pack(side=tk.LEFT, padx=5)

        self.status_label = ttk.Label(control_frame, text="Ready")
        self.status_label.pack(side=tk.RIGHT, padx=5)

    def create_menu_bar(self):
        menu_bar = tk.Menu(self)
        file_menu = tk.Menu(menu_bar, tearoff=0)
        file_menu.add_command(label="Exit", command=self.on_closing)
        menu_bar.add_cascade(label="File", menu=file_menu)

        settings_menu = tk.Menu(menu_bar, tearoff=0)
        settings_menu.add_command(label="Edit config.ini", command=self.edit_config)
        menu_bar.add_cascade(label="Settings", menu=settings_menu)

        self.config(menu=menu_bar)

    def add_project(self):
        """
        Adds a new project. Along with it, automatically creates a default
        template whose name = project folder's name, and content:
            Your task is to 

            {{dirs}}

            {{files_provided}}

            {{file_contents}}
        """
        dir_path = filedialog.askdirectory(title="Select Project Directory")
        if dir_path:
            name = os.path.basename(dir_path)
            if name in self.projects:
                messagebox.showerror("Error", f"Project '{name}' already exists.")
                return
            self.projects[name] = {
                "path": dir_path,
                "last_files": [],
                "blacklist": [],
                "templates": {},
                "last_template": ""
            }
            # Create a default template named same as the project
            default_template = (
                "Your task is to \n\n"
                "{{dirs}}\n\n"
                "{{files_provided}}\n\n"
                "{{file_contents}}"
            )
            self.projects[name]["templates"][name] = default_template

            save_projects(self.projects)
            self.project_dropdown['values'] = list(self.projects.keys())
            self.project_dropdown.set(name)
            self.load_project(name)

    def on_project_selected(self, event):
        self.load_project(self.project_var.get())

    def load_project(self, name):
        self.current_project = name
        self.settings['last_selected_project'] = name
        save_settings(self.settings)
        proj = self.projects[name]
        self.blacklist = proj.get("blacklist", [])
        self.templates = proj.get("templates", {})
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
        # Clear out old items, but keep the toggle_frame with the select_all_button
        for widget in self.file_frame.winfo_children():
            if widget is not self.select_all_button.master:
                if widget != self.select_all_button:
                    widget.destroy()

        proj = self.projects[self.current_project]
        path = proj["path"]

        MAX_FILES = self.MAX_FILES
        file_count = 0
        files_exceeded = False

        canvas = tk.Canvas(self.file_frame)
        scrollbar = ttk.Scrollbar(self.file_frame, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scroll_frame, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.file_vars = {}
        self.file_hashes = {}
        last_files = proj.get("last_files", [])

        # Build a lowercase list of blacklisted entries
        blacklisted_lower = [b.strip().lower() for b in proj.get("blacklist", [])]

        for root, dirs, files in os.walk(path):
            rel_root = os.path.relpath(root, path).replace("\\", "/")
            if rel_root == ".":
                rel_root = ""

            # Filter dirs
            filtered_dirs = []
            for d in dirs:
                test_dir_path = f"{rel_root}/{d}".strip("/").lower()
                if not any(bl in test_dir_path for bl in blacklisted_lower):
                    filtered_dirs.append(d)
            dirs[:] = filtered_dirs

            for file in files:
                # Check if we reached file limit
                if file_count >= MAX_FILES:
                    files_exceeded = True
                    break

                rel_file_path = f"{rel_root}/{file}".strip("/")
                rel_file_path_lower = rel_file_path.lower()
                # Skip if blacklisted
                if any(bl in rel_file_path_lower for bl in blacklisted_lower):
                    continue

                abs_path = os.path.join(root, file)
                var = tk.BooleanVar()
                var.set(rel_file_path in last_files)
                var.trace_add('write', self.on_file_selection_changed)

                chk = ttk.Checkbutton(scroll_frame, text=rel_file_path, variable=var)
                chk.pack(anchor='w')

                self.file_vars[rel_file_path] = var
                self.file_hashes[rel_file_path] = get_file_hash(abs_path)
                file_count += 1

            if files_exceeded:
                break

        if files_exceeded:
            messagebox.showwarning(
                "File Limit Exceeded",
                f"Too many files in the project. Only the first {MAX_FILES} files are loaded."
            )

        self.update_select_all_button()

    def refresh_files(self):
        selected_files = {file for file, var in self.file_vars.items() if var.get()}
        self.file_vars = {}
        self.file_hashes = {}
        self.load_files()

        for file, var in self.file_vars.items():
            if file in selected_files:
                var.set(True)

    def open_settings(self):
        if self.current_project:
            SettingsDialog(self)
        else:
            messagebox.showwarning("No Project Selected", "Please select a project first.")

    def manage_templates(self):
        if self.current_project:
            TemplatesDialog(self)
        else:
            messagebox.showwarning("No Project Selected", "Please select a project first.")

    def generate_output(self):
        if not self.current_project:
            messagebox.showwarning("No Project Selected", "Please select a project first.")
            return
        selected = [f for f, v in self.file_vars.items() if v.get()]
        if not selected:
            messagebox.showwarning("Warning", "No files selected.")
            return
        MAX_FILES = self.MAX_FILES
        if len(selected) > MAX_FILES:
            messagebox.showwarning("Warning", f"You have selected {len(selected)} files. Maximum allowed is {MAX_FILES}.")
            return
        if not self.template_var.get():
            messagebox.showwarning("Warning", "No template selected.")
            return

        self.generate_button.config(state=tk.DISABLED)
        self.status_label.config(text="Generating...")

        proj = self.projects[self.current_project]
        proj["last_files"] = selected
        proj["last_template"] = self.template_var.get()
        save_projects(self.projects)

        self.update_file_hashes(selected)
        dir_tree = generate_directory_tree(proj["path"], proj.get("blacklist", []), max_depth=10, max_lines=1000)
        dir_tree_hash = hashlib.md5(dir_tree.encode('utf-8')).hexdigest()
        cache_key = get_cache_key(selected, self.file_hashes) + dir_tree_hash
        logging.debug(f"Cache key: {cache_key}")

        cached_output = get_cached_output(self.current_project, cache_key)
        if cached_output:
            self.save_and_open(cached_output)
            self.generate_button.config(state=tk.NORMAL)
            self.status_label.config(text="Ready")
        else:
            threading.Thread(target=self.generate_output_content, args=(selected, cache_key, dir_tree)).start()

    def on_file_selection_changed(self, *args):
        selected_files = [f for f, v in self.file_vars.items() if v.get()]
        if self.current_project:
            proj = self.projects[self.current_project]
            proj["last_files"] = selected_files
            save_projects(self.projects)
        self.update_select_all_button()

    def toggle_select_all(self):
        all_selected = all(v.get() for v in self.file_vars.values()) if self.file_vars else False
        new_state = not all_selected
        for var in self.file_vars.values():
            var.set(new_state)
        self.update_select_all_button()

    def update_select_all_button(self):
        if self.file_vars:
            if all(v.get() for v in self.file_vars.values()):
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
            content = ""
            total_size = 0
            MAX_CONTENT_SIZE = 2_000_000
            MAX_FILE_SIZE = 500_000

            for rel_path in selected:
                abs_path = os.path.join(path, rel_path)
                file_size = os.path.getsize(abs_path)
                if file_size > MAX_FILE_SIZE:
                    logging.warning(f"File {rel_path} exceeds maximum allowed size. Skipping.")
                    continue
                if total_size + file_size > MAX_CONTENT_SIZE:
                    logging.warning(f"Total content size exceeds limit. Stopping at {total_size} bytes.")
                    break
                with open(abs_path, 'r', encoding='utf-8') as f:
                    rel_path_normalized = rel_path.replace('\\', '/')
                    file_content = f.read()
                    content += f"--- {rel_path_normalized} ---\n"
                    content += file_content + "\n"
                    content += f"--- {rel_path_normalized} ---\n\n"
                    total_size += file_size

            if total_size == 0:
                self.queue.put(('error', "No file content to process."))
                return

            template_name = self.template_var.get()
            template_content = self.templates[template_name]

            # Inject directory tree
            prompt = template_content.replace(
                "{{dirs}}", f"### File Structure\n\n{dir_tree}\n"
            )

            # Inject file contents
            prompt = prompt.replace(
                "{{file_contents}}", f"### Code Files\n\n{content}\n"
            )

            # If template has {{files_provided}}, replace it line by line
            if "{{files_provided}}" in prompt:
                files_provided_text = "### Code Files provided\n"
                for sf in selected:
                    files_provided_text += f"- {sf}\n"
                prompt = prompt.replace("{{files_provided}}", files_provided_text)
            else:
                # If someone forgot or removed it, just replace to empty
                prompt = prompt.replace("{{files_provided}}", "")

            # Cache the output
            if cache_key:
                save_cached_output(self.current_project, cache_key, prompt)

            self.queue.put(('save_and_open', prompt))

        except Exception:
            logging.error("Generation error: %s", traceback.format_exc())
            self.queue.put(('error', "Error generating output."))

    def process_queue(self):
        try:
            while True:
                task, data = self.queue.get_nowait()
                if task == 'save_and_open':
                    self.save_and_open(data)
                elif task == 'error':
                    messagebox.showerror("Error", data)
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
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(output)
            open_in_editor(fpath)
        except Exception:
            logging.error("Error saving output: %s", traceback.format_exc())
            messagebox.showerror("Error", "Failed to save output.")

    def edit_config(self):
        try:
            config_path = os.path.abspath('config.ini')
            open_in_editor(config_path)
        except Exception:
            logging.error("Error opening config.ini: %s", traceback.format_exc())
            messagebox.showerror("Error", "Failed to open config.ini.")

###############################################################################
#                              SETTINGS DIALOG                                #
###############################################################################
class SettingsDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Settings")
        self.parent = parent
        self.transient(parent)
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
        self.blacklist_entry = ttk.Entry(self)
        self.blacklist_entry.insert(0, ','.join(self.parent.blacklist))
        self.blacklist_entry.pack(fill=tk.X, padx=10)

        ttk.Button(self, text="Save", command=self.save_settings).pack(pady=5)

    def save_settings(self):
        blacklist = [b.strip().lower() for b in self.blacklist_entry.get().split(',') if b.strip()]
        proj = self.parent.projects[self.parent.current_project]
        proj["blacklist"] = blacklist
        self.parent.blacklist = blacklist
        save_projects(self.parent.projects)
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
        self.templates = self.parent.templates
        self.transient(parent)
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
        self.last_selected_index = None
        self.template_listbox = tk.Listbox(self, exportselection=False)
        self.template_listbox.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        for template_name in self.templates:
            self.template_listbox.insert(tk.END, template_name)
        self.template_listbox.bind('<<ListboxSelect>>', self.on_template_select)

        self.template_listbox.bind('<Control-a>', lambda e: 'break')

        content_frame = ttk.Frame(self)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        ttk.Label(content_frame, text="Template Content:").pack()
        self.template_text = scrolledtext.ScrolledText(content_frame, height=15)
        self.template_text.pack(fill=tk.BOTH, expand=True)

        self.template_text.bind('<Control-a>', self.select_all_text)

        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(button_frame, text="Add New", command=self.add_template).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Delete", command=self.delete_template).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Save", command=self.save_template).pack(side=tk.RIGHT, padx=5)

        if self.template_listbox.size() > 0:
            self.template_listbox.selection_set(0)
            self.on_template_select(None)

    def select_all_text(self, event):
        self.template_text.tag_add(tk.SEL, "1.0", tk.END)
        self.template_text.mark_set(tk.INSERT, "1.0")
        self.template_text.see(tk.INSERT)
        return 'break'

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
            messagebox.showerror("Error", "Template name already exists.")
        elif not name:
            messagebox.showwarning("Warning", "Template name cannot be empty.")

    def delete_template(self):
        selection = self.template_listbox.curselection()
        if selection:
            index = selection[0]
            template_name = self.template_listbox.get(index)
            if messagebox.askyesno("Delete Template", f"Are you sure you want to delete '{template_name}'?", parent=self):
                del self.templates[template_name]
                self.template_listbox.delete(index)
                self.template_text.delete('1.0', tk.END)
                self.parent.projects[self.parent.current_project]["templates"] = self.templates
                save_projects(self.parent.projects)
                self.parent.load_templates()
                if self.template_listbox.size() > 0:
                    self.template_listbox.selection_set(0)
                    self.on_template_select(None)
                else:
                    self.last_selected_index = None

    def save_template(self):
        selection = self.template_listbox.curselection()
        if selection:
            index = selection[0]
            template_name = self.template_listbox.get(index)
            content = self.template_text.get('1.0', tk.END).strip()
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
    except Exception:
        logging.error("Unhandled exception: %s", traceback.format_exc())
        messagebox.showerror("Fatal Error", "An unexpected error occurred. See log for details.")
