# File: code_prompt_generator/app/views/dialogs/text_editor_dialog.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import tkinter as tk
from tkinter import ttk, scrolledtext
from app.utils.escape_utils import safe_escape, safe_unescape
from app.utils.ui_helpers import apply_modal_geometry, show_error_centered
from app.utils.system_utils import unify_line_endings

# Dialog: TextEditorDialog
# ------------------------------
class TextEditorDialog(tk.Toplevel):
    # Initialization
    # ------------------------------
    def __init__(self, parent, controller, initial_text="", opened_file=None):
        super().__init__(parent); self.parent = parent; self.controller = controller; self.opened_file = opened_file
        self.title("Text Editor")
        self.create_widgets()
        if initial_text: self.text_area.insert(tk.END, initial_text)
        self.on_close_handler = apply_modal_geometry(self, parent, "TextEditorDialog")

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
    def copy_and_close(self): self.update_clipboard(); self.on_close_handler()
    def open_in_notepad(self): self.controller.save_and_open_notepadpp(self.text_area.get('1.0', 'end-1c')); self.on_close_handler()
    def replace_stars(self):
        self.process_text(lambda t: '\n'.join([line[2:] if line.startswith('> ') else ('' if line == '>' else line.replace('**', '')) for line in unify_line_endings(t).split('\n')]))
    def remove_duplicates(self): self.process_text(lambda t: '\n'.join(dict.fromkeys(t.rstrip('\n').split('\n'))))
    def sort_alphabetically(self): self.process_text(lambda t: '\n'.join(sorted(t.rstrip('\n').split('\n'))))
    def sort_by_length(self): self.process_text(lambda t: '\n'.join(sorted(t.rstrip('\n').split('\n'), key=len)))
    def escape_text(self): self.process_text(lambda t: safe_escape(t.rstrip('\n')))
    def unescape_text(self):
        try: self.process_text(lambda t: safe_unescape(t.rstrip('\n')))
        except (ValueError, TypeError) as e: show_error_centered(self, "Unescape Error", f"Failed to unescape text: {e}")

    # Internal Helpers
    # ------------------------------
    def update_clipboard(self, msg="Copied to clipboard"):
        self.parent.update_clipboard(self.text_area.get('1.0', tk.END).strip(), msg)

    def process_text(self, func):
        new_text = func(self.text_area.get('1.0', tk.END))
        self.text_area.delete('1.0', tk.END); self.text_area.insert(tk.END, new_text)
        self.update_clipboard(); self.on_close_handler()