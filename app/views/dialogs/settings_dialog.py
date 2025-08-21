# File: code_prompt_generator/app/views/dialogs/settings_dialog.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import tkinter as tk
from tkinter import ttk, scrolledtext, colorchooser
import platform, os
from app.utils.ui_helpers import apply_modal_geometry, show_warning_centered, create_enhanced_text_widget, handle_mousewheel
from app.utils.system_utils import open_in_editor
from app.config import LOG_PATH
from app.views.widgets.scrolled_frame import ScrolledFrame

# Dialog: SettingsDialog
# ------------------------------
class SettingsDialog(tk.Toplevel):
	# Initialization
	# ------------------------------
	def __init__(self, parent, controller):
		super().__init__(parent); self.parent = parent; self.controller = controller; self.title("Settings")
		self.on_close_handler = apply_modal_geometry(self, parent, "SettingsDialog")
		self.create_widgets()

	# Widget Creation
	# ------------------------------
	def create_widgets(self):
		proj_name = self.controller.project_model.current_project_name
		proj_conf = self.controller.project_model.projects.get(proj_name, {})
		self.grid_rowconfigure(0, weight=1); self.grid_columnconfigure(0, weight=1)

		scrolled_frame = ScrolledFrame(self, side=tk.TOP, fill=tk.BOTH, expand=True, padx=0, pady=0)
		self.content_frame = scrolled_frame.inner_frame
		self.content_frame.columnconfigure(0, weight=1)

		proj_frame = ttk.LabelFrame(self.content_frame, text="Project-Specific Settings")
		proj_frame.grid(row=0, column=0, padx=10, pady=10, sticky='ew'); proj_frame.columnconfigure(0, weight=1)
		ttk.Label(proj_frame, text="Prefix:").pack(pady=(5,0), anchor='center', padx=10)
		self.prefix_entry = ttk.Entry(proj_frame, takefocus=True); self.prefix_entry.insert(0, proj_conf.get("prefix", "")); self.prefix_entry.pack(fill=tk.X, padx=10, pady=(0,10))
		ttk.Label(proj_frame, text="Project-specific .gitignore & Keep List:").pack(pady=(5,0), anchor='center', padx=10)
		self.extend_text = create_enhanced_text_widget(proj_frame, width=60, height=8, takefocus=True)
		self.extend_text.container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0,10))
		self.extend_text.insert('1.0', "\n".join(proj_conf.get("blacklist", []) + [f"-{k}" for k in proj_conf.get("keep", [])]))
		ttk.Button(proj_frame, text="Open Project Logs Folder", command=self.open_project_logs, takefocus=True).pack(pady=5, padx=10)

		glob_frame = ttk.LabelFrame(self.content_frame, text="Global Settings")
		glob_frame.grid(row=1, column=0, padx=10, pady=10, sticky='ew'); glob_frame.columnconfigure(0, weight=1)
		self.respect_var = tk.BooleanVar(value=self.controller.settings_model.get('respect_gitignore', True))
		ttk.Checkbutton(glob_frame, text="Respect .gitignore", variable=self.respect_var, takefocus=True).pack(pady=5, anchor='center', padx=10)
		self.reset_scroll_var = tk.BooleanVar(value=self.controller.settings_model.get('reset_scroll_on_reset', True))
		ttk.Checkbutton(glob_frame, text="Reset project tree scroll on Reset", variable=self.reset_scroll_var, takefocus=True).pack(pady=5, anchor='center', padx=10)
		self.autofocus_var = tk.BooleanVar(value=self.controller.settings_model.get('autofocus_on_select', True))
		ttk.Checkbutton(glob_frame, text="Auto-focus file in project tree on click in selected view", variable=self.autofocus_var, takefocus=True).pack(pady=5, anchor='center', padx=10)
		
		output_format_frame = ttk.Frame(glob_frame); output_format_frame.pack(pady=5, padx=10)
		ttk.Label(output_format_frame, text="Default Output File Format:").pack(side=tk.LEFT)
		self.output_format_var = tk.StringVar(value=self.controller.settings_model.get('output_file_format', '.md'))
		ttk.Combobox(output_format_frame, textvariable=self.output_format_var, values=['.md', '.txt'], state='readonly', width=5).pack(side=tk.LEFT, padx=5)

		path_display_frame = ttk.Frame(glob_frame); path_display_frame.pack(pady=5, padx=10)
		ttk.Label(path_display_frame, text="Selected Files Path Display Depth:").pack(side=tk.LEFT)
		self.path_depth_var = tk.StringVar(value=self.controller.settings_model.get('selected_files_path_depth', 'Full'))
		path_depth_options = ['Full', '0', '1', '2', '3', '4', '5']
		ttk.Combobox(path_display_frame, textvariable=self.path_depth_var, values=path_depth_options, state='readonly', width=5).pack(side=tk.LEFT, padx=5)

		highlight_frame = ttk.Frame(glob_frame); highlight_frame.pack(pady=5, padx=10)
		ttk.Label(highlight_frame, text="Frequency Highlight Color:").pack(side=tk.LEFT)
		self.highlight_color = self.controller.settings_model.get('highlight_base_color', '#ADD8E6')
		self.color_swatch = tk.Label(highlight_frame, text="    ", bg=self.highlight_color, relief='sunken', borderwidth=1)
		self.color_swatch.pack(side=tk.LEFT, padx=5)
		ttk.Button(highlight_frame, text="Choose...", command=self.choose_highlight_color).pack(side=tk.LEFT)

		ttk.Label(glob_frame, text="File Content Separator Template ({path}, {contents}, python):").pack(pady=(5,0), anchor='center', padx=10)
		self.separator_template_text = create_enhanced_text_widget(glob_frame, width=60, height=5, takefocus=True)
		self.separator_template_text.container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0,10))
		self.separator_template_text.insert('1.0', self.controller.settings_model.get('file_content_separator', '--- {path} ---\n{contents}\n--- {path} ---'))

		ttk.Label(glob_frame, text="Global .gitignore & Keep List:").pack(pady=(5,0), anchor='center', padx=10)
		self.global_extend_text = create_enhanced_text_widget(glob_frame, width=60, height=8, takefocus=True)
		self.global_extend_text.container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0,10))
		self.global_extend_text.insert('1.0', "\n".join(self.controller.settings_model.get("global_blacklist", []) + [f"-{k}" for k in self.controller.settings_model.get("global_keep", [])]))

		btn_container = ttk.Frame(self.content_frame); btn_container.grid(row=2, column=0, padx=10, pady=10, sticky='ew')
		btn_container.columnconfigure(0, weight=1)
		ttk.Button(btn_container, text="Save & Close", command=self.save_and_close, takefocus=True).pack()

		def bind_scroll_recursive(widget):
			handler = lambda event: handle_mousewheel(event, scrolled_frame.canvas)
			widget.bind('<MouseWheel>', handler, add='+')
			widget.bind('<Button-4>', handler, add='+')
			widget.bind('<Button-5>', handler, add='+')
			for child in widget.winfo_children():
				if not isinstance(child, (tk.Text, ttk.Entry)):
					bind_scroll_recursive(child)
		bind_scroll_recursive(self.content_frame)

	# Event Handlers & Public API
	# ------------------------------
	def choose_highlight_color(self):
		picker_toplevel = tk.Toplevel()
		picker_toplevel.title("Select Highlight Color")
		try:
			main_app_window = self
			while main_app_window.master: main_app_window = main_app_window.master
			picker_toplevel.transient(main_app_window)
		except AttributeError: pass
		temp_color = tk.StringVar(value=self.highlight_color)
		def show_chooser_and_update():
			color_data = colorchooser.askcolor(parent=picker_toplevel, initialcolor=temp_color.get())
			if color_data and color_data[1]:
				temp_color.set(color_data[1])
				color_preview.config(bg=color_data[1])
				picker_toplevel.lift(); picker_toplevel.focus_force()
		def save_and_close():
			self.highlight_color = temp_color.get()
			self.color_swatch.config(bg=self.highlight_color)
			picker_toplevel.destroy()
		frame = ttk.Frame(picker_toplevel, padding=10); frame.pack(fill='both', expand=True)
		ttk.Button(frame, text="Choose a Color...", command=show_chooser_and_update).pack(pady=(0, 10))
		preview_frame = ttk.Frame(frame); preview_frame.pack(pady=5)
		ttk.Label(preview_frame, text="Preview:").pack(side='left')
		color_preview = tk.Label(preview_frame, text="      ", bg=temp_color.get(), relief='sunken', borderwidth=2)
		color_preview.pack(side='left', padx=5)
		button_frame = ttk.Frame(frame); button_frame.pack(pady=(10, 0))
		save_button = ttk.Button(button_frame, text="Save", command=save_and_close); save_button.pack(side='left', padx=5)
		ttk.Button(button_frame, text="Cancel", command=picker_toplevel.destroy).pack(side='left', padx=5)
		from app.utils.ui_helpers import center_window
		center_window(picker_toplevel, self); save_button.focus_force()

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
			"autofocus_on_select": self.autofocus_var.get(),
			"global_blacklist": [l for l in glob_lines if not l.startswith('-')],
			"global_keep": [l[1:].strip() for l in glob_lines if l.startswith('-')],
			"output_file_format": self.output_format_var.get(),
			"file_content_separator": self.separator_template_text.get('1.0', tk.END).strip(),
			"highlight_base_color": self.highlight_color,
			"selected_files_path_depth": self.path_depth_var.get()
		}
		self.controller.update_global_settings(global_data)