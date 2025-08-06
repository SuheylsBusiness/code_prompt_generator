# File: code_prompt_generator/app/views/dialogs/raw_edit_dialog.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import tkinter as tk
from tkinter import ttk, scrolledtext
import json
from app.utils.ui_helpers import apply_modal_geometry, show_error_centered, create_enhanced_text_widget

# Dialog: RawEditDialog
# ------------------------------
class RawEditDialog(tk.Toplevel):
	# Initialization
	# ------------------------------
	def __init__(self, parent_dialog, controller):
		super().__init__(parent_dialog); self.parent_dialog = parent_dialog; self.controller = controller
		self.title("Raw Edit Templates JSON")
		self.on_close_handler = apply_modal_geometry(self, parent_dialog.parent, "RawEditDialog")
		self.create_widgets()

	# Widget Creation
	# ------------------------------
	def create_widgets(self):
		self.text_area = create_enhanced_text_widget(self, width=80, height=20)
		self.text_area.container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
		self.text_area.insert(tk.END, json.dumps(self.controller.settings_model.get_all_templates(), indent=4))
		btn_frame = ttk.Frame(self); btn_frame.pack(pady=5)
		ttk.Button(btn_frame, text="Save", command=self.save_json, takefocus=True).pack(side=tk.LEFT, padx=5)
		ttk.Button(btn_frame, text="Cancel", command=self.on_close_handler, takefocus=True).pack(side=tk.LEFT, padx=5)

	# Public API
	# ------------------------------
	def save_json(self):
		try: new_data = json.loads(self.text_area.get('1.0', tk.END).strip())
		except json.JSONDecodeError as e: show_error_centered(self, "Invalid JSON", f"Please fix JSON format.\n{e}"); return
		self.controller.handle_raw_template_update(new_data)
		self.on_close_handler()
		self.parent_dialog.on_close_handler()