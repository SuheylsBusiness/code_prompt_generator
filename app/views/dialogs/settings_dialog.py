# File: code_prompt_generator/app/views/dialogs/settings_dialog.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import tkinter as tk
from tkinter import ttk, scrolledtext
import platform, os
from app.utils.ui_helpers import apply_modal_geometry, show_warning_centered, handle_mousewheel
from app.utils.system_utils import open_in_editor
from app.config import LOG_PATH

# Dialog: SettingsDialog
# ------------------------------
class SettingsDialog(tk.Toplevel):
    # Initialization
    # ------------------------------
    def __init__(self, parent, controller):
        super().__init__(parent); self.parent = parent; self.controller = controller; self.title("Settings")
        self.create_widgets()
        self.on_close_handler = apply_modal_geometry(self, parent, "SettingsDialog")

    # Widget Creation
    # ------------------------------
    def create_widgets(self):
        proj_name = self.controller.project_model.current_project_name
        proj_conf = self.controller.project_model.projects.get(proj_name, {})
        self.grid_rowconfigure(0, weight=1); self.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(self, borderwidth=0); self.canvas.grid(row=0, column=0, sticky='nsew')
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview); self.scrollbar.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.content_frame = ttk.Frame(self.canvas); self.content_frame.columnconfigure(0, weight=1)
        self._cwin_id = self.canvas.create_window((0, 0), window=self.content_frame, anchor='nw')
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfig(self._cwin_id, width=e.width), add='+')
        self.content_frame.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")), add='+')
        
        mousewheel_binder = lambda widget: widget.bind('<MouseWheel>', lambda e: handle_mousewheel(e, self.canvas), '+')
        mousewheel_binder(self)
        mousewheel_binder(self.canvas)

        proj_frame = ttk.LabelFrame(self.content_frame, text="Project-Specific Settings")
        proj_frame.grid(row=0, column=0, padx=10, pady=10, sticky='ew'); proj_frame.columnconfigure(0, weight=1)
        ttk.Label(proj_frame, text="Prefix:").pack(pady=(5,0), anchor='center', padx=10)
        self.prefix_entry = ttk.Entry(proj_frame, takefocus=True); self.prefix_entry.insert(0, proj_conf.get("prefix", "")); self.prefix_entry.pack(fill=tk.X, padx=10, pady=(0,10))
        ttk.Label(proj_frame, text="Project-specific .gitignore & Keep List:").pack(pady=(5,0), anchor='center', padx=10)
        self.extend_text = scrolledtext.ScrolledText(proj_frame, width=60, height=8, takefocus=True)
        self.extend_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0,10))
        self.extend_text.insert('1.0', "\n".join(proj_conf.get("blacklist", []) + [f"-{k}" for k in proj_conf.get("keep", [])]))
        ttk.Button(proj_frame, text="Open Project Logs Folder", command=self.open_project_logs, takefocus=True).pack(pady=5, padx=10)

        glob_frame = ttk.LabelFrame(self.content_frame, text="Global Settings")
        glob_frame.grid(row=1, column=0, padx=10, pady=10, sticky='ew'); glob_frame.columnconfigure(0, weight=1)
        self.respect_var = tk.BooleanVar(value=self.controller.settings_model.get('respect_gitignore', True))
        ttk.Checkbutton(glob_frame, text="Respect .gitignore", variable=self.respect_var, takefocus=True).pack(pady=5, anchor='center', padx=10)
        self.reset_scroll_var = tk.BooleanVar(value=self.controller.settings_model.get('reset_scroll_on_reset', True))
        ttk.Checkbutton(glob_frame, text="Reset project tree scroll on Reset", variable=self.reset_scroll_var, takefocus=True).pack(pady=5, anchor='center', padx=10)
        ttk.Label(glob_frame, text="Global .gitignore & Keep List:").pack(pady=(5,0), anchor='center', padx=10)
        self.global_extend_text = scrolledtext.ScrolledText(glob_frame, width=60, height=8, takefocus=True)
        self.global_extend_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0,10))
        self.global_extend_text.insert('1.0', "\n".join(self.controller.settings_model.get("global_blacklist", []) + [f"-{k}" for k in self.controller.settings_model.get("global_keep", [])]))

        btn_container = ttk.Frame(self.content_frame); btn_container.grid(row=2, column=0, padx=10, pady=10, sticky='ew')
        btn_container.columnconfigure(0, weight=1)
        ttk.Button(btn_container, text="Save & Close", command=self.save_and_close, takefocus=True).pack()

    # Event Handlers & Public API
    # ------------------------------
    def save_and_close(self):
        self.save_settings()
        self.controller.refresh_files(is_manual=True)
        self.on_close_handler()

    def open_project_logs(self):
        project_name = self.controller.project_model.current_project_name
        if not project_name: return show_warning_centered(self, "No Project", "No project is currently selected.")
        safe_project_name = "".join(c for c in project_name if c.isalnum() or c in (' ', '_', '-')).rstrip()
        project_log_dir = os.path.join(LOG_PATH, safe_project_name)
        os.makedirs(project_log_dir, exist_ok=True); open_in_editor(project_log_dir)

    def save_settings(self):
        proj_name = self.controller.project_model.current_project_name
        if not proj_name: return

        proj_lines = [l.strip() for l in self.extend_text.get('1.0', tk.END).split('\n') if l.strip()]
        proj_data = {
            "prefix": self.prefix_entry.get().strip(),
            "blacklist": [l for l in proj_lines if not l.startswith('-')],
            "keep": [l[1:].strip() for l in proj_lines if l.startswith('-')]
        }
        self.controller.update_project_settings(proj_name, proj_data)

        glob_lines = [l.strip() for l in self.global_extend_text.get('1.0', tk.END).split('\n') if l.strip()]
        global_data = {
            "respect_gitignore": self.respect_var.get(),
            "reset_scroll_on_reset": self.reset_scroll_var.get(),
            "global_blacklist": [l for l in glob_lines if not l.startswith('-')],
            "global_keep": [l[1:].strip() for l in glob_lines if l.startswith('-')]
        }
        self.controller.update_global_settings(global_data)