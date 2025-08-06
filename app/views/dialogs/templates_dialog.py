# File: code_prompt_generator/app/views/dialogs/templates_dialog.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import tkinter as tk
from tkinter import ttk, scrolledtext, simpledialog
import copy
from app.utils.ui_helpers import apply_modal_geometry, show_yesno_centered, show_warning_centered, show_error_centered, show_yesnocancel_centered, create_enhanced_text_widget
from app.views.dialogs.rename_template_dialog import RenameTemplateDialog
from app.views.dialogs.raw_edit_dialog import RawEditDialog

# Dialog: TemplatesDialog
# ------------------------------
class TemplatesDialog(tk.Toplevel):
	# Initialization
	# ------------------------------
	def __init__(self, parent, controller):
		super().__init__(parent); self.parent = parent; self.controller = controller; self.title("Manage Templates")
		self.templates = copy.deepcopy(self.controller.settings_model.get_all_templates())
		self.template_names = sorted(self.templates.keys())
		self.last_selected_index = None
		self.create_widgets()
		self.on_close_handler = apply_modal_geometry(self, parent, "TemplatesDialog")
		self.protocol("WM_DELETE_WINDOW", self.on_dialog_close)
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
		self.template_text = create_enhanced_text_widget(cf, height=15, takefocus=True)
		self.template_text.container.pack(fill=tk.BOTH, expand=True, pady=(5,0))

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
		self.is_default_var.set(t_name == self.controller.settings_model.get("default_template_name"))
		self.default_button.config(state=tk.NORMAL)

	def on_name_dbl_click(self, event):
		s = self.template_listbox.curselection()
		if not s: return
		old_name = self.template_listbox.get(s[0])
		new_name = RenameTemplateDialog(self, old_name).new_name
		if new_name is None or new_name == old_name: return
		if not new_name: return show_warning_centered(self, "Warning", "Template name cannot be empty.")
		if new_name in self.templates: return show_error_centered(self, "Error", "Template name already exists.")
		self.templates[new_name] = self.templates.pop(old_name)
		if self.controller.settings_model.get("default_template_name") == old_name: self.controller.settings_model.set("default_template_name", new_name)
		self.template_names = sorted(self.templates.keys())
		self.refresh_template_list(new_name)

	def add_template(self):
		name = simpledialog.askstring("Template Name", "Enter template name:", parent=self)
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
			del self.templates[t_name]; self.template_names.remove(t_name)
			if self.controller.settings_model.get("default_template_name") == t_name: self.controller.settings_model.set("default_template_name", None)
			self.refresh_template_list(); self.template_text.delete('1.0', tk.END)

	def save_and_close(self):
		self.save_current_template_content()
		self.controller.handle_raw_template_update(self.templates)
		self.on_close_handler()

	def raw_edit_all_templates(self): RawEditDialog(self, self.controller)
	
	def on_dialog_close(self):
		if self.has_unsaved_changes():
			response = show_yesnocancel_centered(self.parent, "Unsaved Changes", "You have unsaved changes. Do you want to save them?")
			if response == "yes": self.save_and_close()
			elif response == "no": self.on_close_handler()
			else: return # Cancel
		else:
			self.on_close_handler()

	# Internal Helpers
	# ------------------------------
	def has_unsaved_changes(self):
		self.save_current_template_content()
		original_templates = self.controller.settings_model.get_all_templates()
		return self.templates != original_templates or self.controller.settings_model.get("default_template_name") != self.controller.settings_model.baseline_settings.get("default_template_name")

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
			if self.templates.get(t_name) != content:
				self.templates[t_name] = content
				# Mark cache as dirty when template content changes
				self.controller.precomputed_prompt_cache.clear()

	def toggle_default_template(self):
		if not self.template_listbox.curselection(): return
		t_name = self.template_listbox.get(self.template_listbox.curselection()[0])
		if self.is_default_var.get(): self.controller.settings_model.set("default_template_name", t_name)
		elif self.controller.settings_model.get("default_template_name") == t_name: self.controller.settings_model.set("default_template_name", None)