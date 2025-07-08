# File: code_prompt_generator/app/views/dialogs/rename_template_dialog.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import tkinter as tk
from tkinter import ttk
from app.utils.ui_helpers import apply_modal_geometry

# Dialog: RenameTemplateDialog
# ------------------------------
class RenameTemplateDialog(tk.Toplevel):
    # Initialization
    # ------------------------------
    def __init__(self, parent, old_name):
        super().__init__(parent); self.parent = parent; self.title("Rename Template")
        self.new_name = None; self.old_name = old_name
        self.create_widgets()
        # The parent of this dialog is TemplatesDialog, whose parent is the main view.
        self.on_close_handler = apply_modal_geometry(self, self.parent.parent, "RenameTemplateDialog")
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
    def on_ok(self): self.new_name = self.entry_var.get().strip(); self.on_close_handler()
    def on_cancel(self): self.new_name = None; self.on_close_handler()