# File: code_prompt_generator/app/views/main_view.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
import os, time, platform
from app.config import get_logger
from app.utils.path_utils import resource_path
from app.utils.system_utils import get_relative_time_str
from app.utils.ui_helpers import format_german_thousand_sep, show_warning_centered, handle_mousewheel
from app.views.widgets.scrolled_frame import ScrolledFrame
from app.views.dialogs.settings_dialog import SettingsDialog
from app.views.dialogs.templates_dialog import TemplatesDialog
from app.views.dialogs.history_selection_dialog import HistorySelectionDialog
from app.views.dialogs.output_files_dialog import OutputFilesDialog
from app.views.dialogs.text_editor_dialog import TextEditorDialog

logger = get_logger(__name__)

# Main Application View
# ------------------------------
class MainView(tk.Tk):
	# Initialization & State
	# ------------------------------
	def __init__(self, controller):
		super().__init__()
		self.controller = controller
		self.title(f"Code Prompt Generator - PID: {os.getpid()}")
		self.initialize_styles()
		self.initialize_state()
		self.create_layout()
		self.protocol("WM_DELETE_WINDOW", self.controller.on_closing)

	def initialize_styles(self):
		self.style = ttk.Style(self)
		try: self.style.theme_use('vista')
		except tk.TclError:
			try: self.style.theme_use(self.style.theme_names()[0])
			except Exception as e: logger.warning("Failed to set a theme: %s", e)
		self.style.configure('.', font=('Segoe UI', 10), background='#F3F3F3')
		for s in ['TFrame', 'TLabel', 'TCheckbutton', 'Modern.TCheckbutton', 'TRadiobutton']: self.style.configure(s, background='#F3F3F3')
		for s in ['ProjectOps.TLabelframe', 'TemplateOps.TLabelframe', 'FilesFrame.TLabelframe', 'SelectedFiles.TLabelframe']: self.style.configure(s, background='#F3F3F3', padding=10, foreground='#444444')
		self.style.configure('TButton', foreground='black', background='#F0F0F0', padding=6, font=('Segoe UI',10,'normal'))
		self.style.map('TButton', foreground=[('disabled','#7A7A7A'),('active','black')], background=[('active','#E0E0E0'),('disabled','#F0F0F0')])
		self.style.configure('Treeview', rowheight=25, fieldbackground='#F3F3F3', background='#F3F3F3')
		self.style.configure('Treeview.Heading', font=('Segoe UI', 10, 'bold'))
		self.style.configure('RemoveFile.TButton', anchor='center', padding=(2,1))
		self.style.configure('Toolbutton', padding=1)
		self.icon_path = resource_path('app_icon.ico')
		if os.path.exists(self.icon_path):
			try: self.iconbitmap(self.icon_path)
			except tk.TclError: logger.warning("Could not set .ico file.")

	def initialize_state(self):
		self.reset_button_clicked = False
		self.is_silent_refresh = False
		self.scroll_restore_job = None
		self.search_debounce_job = None
		self.selection_update_job = None
		self.skip_search_scroll = False
		self._project_listbox = None
		self.selected_files_sort_mode = tk.StringVar(value='default')
		self._bulk_update_active = False
		self.last_clicked_item = None
		self.tree_sort_column = None
		self.tree_sort_reverse = False
		self.bold_font = tkfont.Font(font=self.style.lookup('TLabel', 'font'))
		self.bold_font.configure(weight='bold')
		self.is_currently_searching = False


	# GUI Layout Creation
	# ------------------------------
	def create_layout(self):
		self.top_frame = ttk.Frame(self); self.top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)
		self.create_top_widgets(self.top_frame)
		main_area_frame = ttk.Frame(self)
		main_area_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(5,0))
		self.file_frame = ttk.LabelFrame(main_area_frame, text="Project Files", style='FilesFrame.TLabelframe')
		self.file_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
		self.create_file_widgets(self.file_frame)
		self.selected_files_frame = ttk.LabelFrame(main_area_frame, text="Selected Files View", style='SelectedFiles.TLabelframe')
		self.selected_files_frame.pack(side=tk.RIGHT, fill=tk.Y, expand=False)
		self.create_selected_files_widgets(self.selected_files_frame)
		self.control_frame = ttk.Frame(self); self.control_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=5)
		self.create_bottom_widgets(self.control_frame)

	def create_top_widgets(self, container):
		pa = ttk.LabelFrame(container, text="Project Operations", style='ProjectOps.TLabelframe')
		pa.pack(side=tk.LEFT, fill=tk.Y, padx=(0,5))
		ttk.Label(pa, text="Select Project:").pack(anchor='w', pady=(0,2))
		self.project_var = tk.StringVar()
		self.project_dropdown = ttk.Combobox(pa, textvariable=self.project_var, state='readonly', width=20, takefocus=True)
		self.project_dropdown.pack(anchor='w', pady=(0,5))
		self.project_dropdown.bind("<KeyPress>", self.controller.on_project_dropdown_search)
		self.project_dropdown.configure(postcommand=self.bind_project_listbox)
		self.project_dropdown.bind("<<ComboboxSelected>>", self.controller.on_project_selected)
		of = ttk.Frame(pa); of.pack(anchor='w', pady=(5,0))
		ttk.Button(of, text="Add Project", command=self.controller.add_project, takefocus=True).pack(side=tk.LEFT)
		ttk.Button(of, text="Open Folder", command=self.controller.open_project_folder, takefocus=True).pack(side=tk.LEFT, padx=5)
		ttk.Button(of, text="Remove Project", command=self.controller.remove_project, takefocus=True).pack(side=tk.LEFT, padx=5)

		tf = ttk.LabelFrame(container, text="Template", style='TemplateOps.TLabelframe'); tf.pack(side=tk.RIGHT, fill=tk.Y, padx=(5,0))
		template_frame_inner = ttk.Frame(tf); template_frame_inner.pack(anchor='w')
		ttk.Label(template_frame_inner, text="Select Template:").pack(anchor='w', pady=(0,2))
		self.template_var = tk.StringVar(); self.template_var.trace_add('write', lambda *a: self.controller.request_precomputation())
		self.template_dropdown = ttk.Combobox(template_frame_inner, textvariable=self.template_var, state='readonly', width=20, takefocus=True); self.template_dropdown.pack(anchor='w', pady=(0,5)); self.template_dropdown.bind("<<ComboboxSelected>>", self.controller.on_template_selected)
		template_buttons_frame = ttk.Frame(tf); template_buttons_frame.pack(anchor='w', pady=5)
		self.manage_templates_btn = ttk.Button(template_buttons_frame, text="Manage Templates", command=self.open_templates_dialog, takefocus=True); self.manage_templates_btn.pack(side=tk.LEFT)
		self.reset_template_btn = ttk.Button(template_buttons_frame, text="Reset to Default", command=self.reset_template_to_default, takefocus=True, state=tk.DISABLED); self.reset_template_btn.pack(side=tk.LEFT, padx=5)

		qf = ttk.LabelFrame(container, text="Quick Action", style='TemplateOps.TLabelframe'); qf.pack(side=tk.RIGHT, fill=tk.BOTH, padx=5, expand=True)
		self.quick_copy_var = tk.StringVar()
		self.quick_copy_dropdown = ttk.Combobox(qf, textvariable=self.quick_copy_var, state='readonly', width=20, takefocus=True); self.quick_copy_dropdown.pack(anchor='w', pady=(0,5), fill=tk.X)
		self.quick_copy_dropdown.bind("<<ComboboxSelected>>", self.controller.on_quick_copy_selected)
		quick_buttons_frame = ttk.Frame(qf); quick_buttons_frame.pack(anchor='w', pady=(5,0), fill=tk.X, expand=True)
		self.most_frequent_button = ttk.Button(quick_buttons_frame, text="Most Frequent:\n(N/A)", command=self.controller.execute_most_frequent_quick_action)
		self.most_frequent_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
		self.most_recent_button = ttk.Button(quick_buttons_frame, text="Most Recent:\n(N/A)", command=self.controller.execute_most_recent_quick_action)
		self.most_recent_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 0))

	def create_file_widgets(self, container):
		sf = ttk.Frame(container); sf.pack(fill=tk.X, padx=5, pady=(5,2))
		ttk.Label(sf, text="Search:").pack(side=tk.LEFT, padx=(0,5))
		self.file_search_var = tk.StringVar(); self.file_search_var.trace_add("write", self.on_search_changed)
		ttk.Entry(sf, textvariable=self.file_search_var, width=25, takefocus=True).pack(side=tk.LEFT)
		ttk.Button(sf, text="✕", command=lambda: self.file_search_var.set(""), style='Toolbutton').pack(side=tk.LEFT, padx=(5,0))

		tf = ttk.Frame(container); tf.pack(fill=tk.X, padx=5, pady=(5,2))
		self.select_all_button = ttk.Button(tf, text="Select All", command=self.controller.toggle_select_all, takefocus=True); self.select_all_button.pack(side=tk.LEFT)
		self.reset_button = ttk.Button(tf, text="Reset", command=self.controller.reset_selection, takefocus=True); self.reset_button.pack(side=tk.LEFT, padx=5)
		self.file_selected_label = ttk.Label(tf, text="Files: 0/0 | Total Chars: 0", width=60); self.file_selected_label.pack(side=tk.LEFT, padx=10)

		tree_frame = ttk.Frame(container); tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
		tree_frame.rowconfigure(0, weight=1); tree_frame.columnconfigure(0, weight=1)
		self.tree = ttk.Treeview(tree_frame, columns=('chars',), show='tree headings', selectmode='extended')
		self.tree.heading('#0', text='Name', command=lambda: self.on_sort_column_click('name', False))
		self.tree.heading('chars', text='Chars', command=lambda: self.on_sort_column_click('chars', True))
		self.tree.column('#0', stretch=True, width=300); self.tree.column('chars', stretch=False, width=80, anchor='e')
		vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
		hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
		self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
		self.tree.grid(row=0, column=0, sticky='nsew'); vsb.grid(row=0, column=1, sticky='ns'); hsb.grid(row=1, column=0, sticky='ew')
		
		self.tree.tag_configure('dir', font=self.bold_font)
		self.tree.tag_configure('oddrow', background='#FFFFFF')
		self.tree.tag_configure('evenrow', background='#F3F3F3')

		self.tree.bind('<<TreeviewSelect>>', self.on_tree_selection_changed)
		self.tree.bind('<Button-1>', self.on_tree_click)
		self.tree.bind('<Double-1>', self.on_tree_double_click)
		self.tree.bind('<Button-3>', self.on_tree_right_click) # Windows/Linux
		self.tree.bind('<Button-2>', self.on_tree_right_click) # macOS
		self.tree.bind('<Control-a>', self.select_all_tree_items)
		self.tree.bind('<Control-A>', self.select_all_tree_items)

	def create_selected_files_widgets(self, container):
		sort_frame = ttk.Frame(container); sort_frame.pack(fill=tk.X, padx=5, pady=0)
		ttk.Label(sort_frame, text="Sort by:").pack(side=tk.LEFT)
		ttk.Radiobutton(sort_frame, text="Default", variable=self.selected_files_sort_mode, value="default", command=self.on_sort_mode_changed).pack(side=tk.LEFT, padx=5)
		ttk.Radiobutton(sort_frame, text="Char Count", variable=self.selected_files_sort_mode, value="char_count", command=self.on_sort_mode_changed).pack(side=tk.LEFT)
		self.selected_files_scrolled_frame = ScrolledFrame(container, side=tk.TOP, expand=True, fill=tk.BOTH, padx=5, pady=5, add_horizontal_scrollbar=True); self.selected_files_canvas = self.selected_files_scrolled_frame.canvas; self.selected_files_inner = self.selected_files_scrolled_frame.inner_frame
		container.pack_propagate(False)
		container.config(width=300)

	def create_bottom_widgets(self, container):
		gen_frame = ttk.Frame(container); gen_frame.pack(side=tk.LEFT, padx=5)
		self.generate_button = ttk.Button(gen_frame, text="Generate", width=12, command=self.controller.generate_output, takefocus=True); self.generate_button.pack(side=tk.LEFT)
		ttk.Label(gen_frame, text="MD:").pack(side=tk.LEFT, padx=(10, 0)); self.generate_menu_button_md = ttk.Button(gen_frame, text="▼", width=2, command=self.show_quick_generate_menu); self.generate_menu_button_md.pack(side=tk.LEFT)
		ttk.Label(gen_frame, text="CB:").pack(side=tk.LEFT, padx=(10, 0)); self.generate_menu_button_cb = ttk.Button(gen_frame, text="▼", width=2, command=self.show_quick_generate_menu_cb); self.generate_menu_button_cb.pack(side=tk.LEFT)

		self.refresh_button = ttk.Button(container, text="Refresh Files", width=12, command=lambda: self.controller.refresh_files(is_manual=True), takefocus=True); self.refresh_button.pack(side=tk.LEFT, padx=5)
		self.status_label = ttk.Label(container, text="Ready"); self.status_label.pack(side=tk.RIGHT, padx=10)
		self.view_outputs_button = ttk.Button(container, text="View Outputs", command=self.open_output_files, takefocus=True); self.view_outputs_button.pack(side=tk.RIGHT)
		self.history_button = ttk.Button(container, text="History Selection", command=self.open_history_selection, takefocus=True); self.history_button.pack(side=tk.RIGHT, padx=5)
		ttk.Separator(container, orient='vertical').pack(side=tk.RIGHT, fill='y', padx=5)
		self.text_editor_button = ttk.Button(container, text="Open Text Editor", command=self.open_text_editor, takefocus=True); self.text_editor_button.pack(side=tk.RIGHT)
		self.settings_button = ttk.Button(container, text="Settings", command=self.open_settings_dialog, takefocus=True); self.settings_button.pack(side=tk.RIGHT, padx=5)

	# UI Update Methods
	# ------------------------------
	def restore_window_geometry(self):
		geom = self.controller.settings_model.get('window_geometry')
		self.geometry(geom if geom else "1200x800")

	def set_status_temporary(self, msg, duration=2000):
		self.status_label.config(text=msg)
		self.after(duration, lambda: self.status_label.config(text="Ready"))

	def set_status_loading(self): self.status_label.config(text="Loading...")
	def set_generation_state(self, is_generating, to_clipboard=False):
		state = tk.DISABLED if is_generating else tk.NORMAL
		self.generate_button.config(state=state)
		self.generate_menu_button_md.config(state=state)
		self.generate_menu_button_cb.config(state=state)
		if is_generating: self.status_label.config(text=f"Generating{' for clipboard' if to_clipboard else ''}...")
		else: self.status_label.config(text="Ready")

	def update_selection_count_label(self, file_count, total_chars_text):
		total_files = len([i for i in self.controller.project_model.all_items if i["type"] == "file"])
		self.file_selected_label.config(text=f"Files: {file_count}/{total_files} | Total Chars: {total_chars_text}")

	def display_items(self, scroll_to_top=False):
		if self.reset_button_clicked and not self.controller.settings_model.get('reset_scroll_on_reset', True): scroll_to_top = False
		
		query = self.file_search_var.get().strip().lower()
		is_searching = bool(query)

		if is_searching and not self.is_currently_searching:
			current_ui_state = self.get_ui_state()
			if self.controller.project_model.current_project_name:
				self.controller.project_model.set_project_ui_state(self.controller.project_model.current_project_name, current_ui_state)
		self.is_currently_searching = is_searching

		self.tree.delete(*self.tree.get_children())
		filtered = [it for it in self.controller.project_model.all_items if query in it["path"].lower()] if query else self.controller.project_model.all_items
		self.controller.project_model.set_filtered_items(filtered)
		
		parents = {"": ""}
		for item in filtered:
			path = item['path']
			parent_path = os.path.dirname(path.rstrip('/')).replace('\\', '/')
			parent_iid = parents.get(parent_path, "")
			
			if item["type"] == "dir":
				text = f"📁 {os.path.basename(path.rstrip('/'))}"
				iid = self.tree.insert(parent_iid, 'end', iid=path, text=text, open=is_searching, tags=('dir',))
				parents[path.rstrip('/')] = iid
			else:
				text = f"📄 {os.path.basename(path)}"
				char_count = self.controller.project_model.file_char_counts.get(path, 0)
				char_count_str = format_german_thousand_sep(char_count)
				iid = self.tree.insert(parent_iid, 'end', iid=path, text=text, values=(char_count_str,), tags=('file',))
		
		self.reapply_row_tags()
		self.sync_treeview_selection_to_model()
		
		if not is_searching:
			ui_state = self.controller.project_model.get_project_ui_state(self.controller.project_model.current_project_name)
			self.apply_ui_state(ui_state)
		
		if scroll_to_top or (self.reset_button_clicked and self.controller.settings_model.get('reset_scroll_on_reset', True)):
			self.scroll_tree_to(0.0)
		else:
			self.scroll_tree_to(self.controller.project_model.project_tree_scroll_pos)
			
		self.reset_button_clicked = False; self.is_silent_refresh = False

	def reapply_row_tags(self):
		def apply_tags_recursive(parent_iid, index):
			for child_iid in self.tree.get_children(parent_iid):
				current_tags = list(self.tree.item(child_iid, 'tags'))
				new_tags = [t for t in current_tags if t not in ('oddrow', 'evenrow')]
				new_tags.append('oddrow' if index % 2 else 'evenrow')
				self.tree.item(child_iid, tags=tuple(new_tags))
				index += 1
				if self.tree.item(child_iid, 'open'):
					index = apply_tags_recursive(child_iid, index)
			return index
		apply_tags_recursive('', 0)
		
	def scroll_tree_to(self, pos):
		if self.scroll_restore_job: self.after_cancel(self.scroll_restore_job)
		self.scroll_restore_job = self.after(50, lambda p=pos: (self.tree.yview_moveto(p), setattr(self, "scroll_restore_job", None)))

	def get_scroll_position(self):
		try: return self.tree.yview()[0]
		except Exception: return 0.0

	def clear_project_view(self):
		self.is_currently_searching = False
		self.controller.project_model.set_items([]);
		self.tree.delete(*self.tree.get_children())
		for w in self.selected_files_inner.winfo_children(): w.destroy()
		self.controller.handle_file_selection_change()

	def clear_ui_for_loading(self):
		self.is_currently_searching = False
		self.tree.delete(*self.tree.get_children())
		for w in self.selected_files_inner.winfo_children(): w.destroy()
		self.update_selection_count_label(0, "0")
		self.refresh_selected_files_list([])
		self.update_select_all_button()

	def show_loading_placeholder(self):
		self.tree.insert("", "end", text="Loading project files...", iid="loading_placeholder")

	def update_project_list(self, projects_data):
		cur_disp = self.project_var.get()
		cur_name = cur_disp.split(" (")[0] if " (" in cur_disp else cur_disp
		sorted_display_values = [f"{n} ({get_relative_time_str(lu)})" if lu > 0 else n for n, lu, uc in projects_data]
		self.project_dropdown["values"] = sorted_display_values
		match = next((d for d in sorted_display_values if d == cur_name or d.startswith(f"{cur_name} (")), None)
		if match: self.project_dropdown.set(match)
		elif sorted_display_values: self.project_dropdown.set(sorted_display_values[0])
		else: self.project_var.set("")
		if sorted_display_values: self.project_dropdown.configure(width=max(max((len(d) for d in sorted_display_values), default=20), 20))

	def get_display_name_for_project(self, name):
		projects_data = self.controller.project_model.get_sorted_projects_for_display()
		for proj_name, last_usage, _ in projects_data:
			if proj_name == name:
				return f"{proj_name} ({get_relative_time_str(last_usage)})" if last_usage > 0 else proj_name
		return name

	def update_template_dropdowns(self, force_refresh):
		display_templates = self.controller.settings_model.get_display_templates()
		if not force_refresh and list(self.template_dropdown['values']) == display_templates: return
		self.template_dropdown['values'] = display_templates
		if display_templates: self.template_dropdown.config(height=min(len(display_templates), 15), width=max(max((len(x) for x in display_templates), default=0)+2, 20))

		qc_menu_items = self.controller.settings_model.get_quick_copy_templates()
		editor_tools = ["Replace \"**\"", "Gemini Whitespace Fix", "Remove Duplicates", "Sort Alphabetically", "Sort by Length", "Escape Text", "Unescape Text"]
		qc_menu = []
		if qc_menu_items: qc_menu.extend(["-- Template Content --"] + qc_menu_items)
		qc_menu.extend(["-- Text Editor Tools --", "Truncate Between '---'"] + editor_tools)
		
		self.quick_copy_dropdown.config(values=qc_menu, height=min(len(qc_menu), 15))
		if qc_menu: self.quick_copy_dropdown.config(width=max(max((len(x) for x in qc_menu), default=0)+2, 20))
		self.quick_copy_var.set("")

		default_to_set = self.controller.settings_model.get("default_template_name")
		if default_to_set and default_to_set in display_templates: self.template_var.set(default_to_set)
		elif display_templates: self.template_var.set(display_templates[0])
		else: self.template_var.set("")

	def refresh_selected_files_list(self, selected):
		for w in self.selected_files_inner.winfo_children(): w.destroy()
		if self.selected_files_sort_mode.get() == 'char_count':
			selected = sorted(selected, key=lambda f: self.controller.project_model.file_char_counts.get(f, 0), reverse=True)

		longest_lbl_text = ""
		for i, f in enumerate(selected):
			lbl_text = f"{f} [{format_german_thousand_sep(self.controller.project_model.file_char_counts.get(f, 0))}]"
			if len(lbl_text) > len(longest_lbl_text): longest_lbl_text = lbl_text
			rf = ttk.Frame(self.selected_files_inner); rf.pack(fill=tk.X, anchor='w')
			self.selected_files_scrolled_frame.bind_mousewheel_to_widget(rf)
			xb = ttk.Button(rf, text="x", width=1, style='RemoveFile.TButton', command=lambda ff=f: self.unselect_tree_item(ff))
			xb.pack(side=tk.LEFT, padx=(0,5)); self.selected_files_scrolled_frame.bind_mousewheel_to_widget(xb)
			lbl = ttk.Label(rf, text=lbl_text, cursor="hand2"); lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
			lbl.bind("<Button-1>", lambda e, ff=f: self.on_selected_file_clicked(ff)); self.selected_files_scrolled_frame.bind_mousewheel_to_widget(lbl)

		if longest_lbl_text:
			try:
				fnt = tkfont.Font(font=ttk.Style().lookup('TLabel', 'font'))
				desired_w = fnt.measure(longest_lbl_text) + 100
			except tk.TclError: desired_w = 300
		else: desired_w = 300
		desired_w = max(300, min(desired_w, int(self.winfo_screenwidth()*0.75)))

		for w in (self.selected_files_frame, self.selected_files_scrolled_frame, self.selected_files_scrolled_frame.canvas):
			try: w.config(width=desired_w)
			except Exception: pass
		try:
			self.update_idletasks()
			total_w = self.winfo_width() or self.winfo_screenwidth()
			remaining = max(200, total_w - desired_w - 20)
			self.file_frame.pack_propagate(False)
			self.file_frame.config(width=remaining)
		except Exception: pass
		self.selected_files_canvas.yview_moveto(0)

	def update_select_all_button(self):
		filtered_files = {item['path'] for item in self.controller.project_model.get_filtered_items() if item['type'] == 'file'}
		if filtered_files:
			is_all_selected = filtered_files.issubset(self.controller.project_model.get_selected_files_set())
			self.select_all_button.config(text="Unselect All" if is_all_selected else "Select All")
		else:
			self.select_all_button.config(text="Select All")

	def update_file_char_counts(self):
		for path, count in self.controller.project_model.file_char_counts.items():
			if self.tree.exists(path):
				self.tree.set(path, 'chars', format_german_thousand_sep(count))

	def update_quick_action_buttons(self):
		if not self.most_frequent_button.winfo_exists(): return
		frequent_action = self.controller.get_most_frequent_action()
		recent_action = self.controller.get_most_recent_action()
		self.most_frequent_button.config(text=f"Most Frequent:\n{frequent_action or '(N/A)'}")
		self.most_recent_button.config(text=f"Most Recent:\n{recent_action or '(N/A)'}")

	# Event Handlers & User Interaction
	# ------------------------------
	def on_tree_click(self, event):
		iid = self.tree.identify_row(event.y)
		if not iid: return
		if event.state & 0x0001: # Shift key is pressed
			self.handle_shift_select(iid)
		else:
			self.last_clicked_item = iid

	def on_tree_double_click(self, event):
		iid = self.tree.identify_row(event.y)
		if not iid: return
		# Skip selection toggling for directories – just let them expand/collapse
		if self.tree.tag_has('dir', iid): return
		if iid in self.tree.selection():
			self.tree.selection_remove(iid)
		else:
			self.tree.selection_add(iid)

	def on_tree_right_click(self, event):
		iid = self.tree.identify_row(event.y)
		if iid:
			self.show_tree_context_menu(event, iid)

	def on_tree_selection_changed(self, event=None):
		if self._bulk_update_active: return
		if self.selection_update_job: self.after_cancel(self.selection_update_job)
		self.selection_update_job = self.after_idle(self._process_tree_selection)

	def _process_tree_selection(self):
		selected_iids = self.tree.selection()
		selected_paths = {iid for iid in selected_iids if self.tree.tag_has('file', iid)}
		if selected_iids and not selected_paths:
			prev_set = self.controller.project_model.get_selected_files_set()
			if prev_set:
				self._bulk_update_active = True
				try:
					self.tree.selection_set([p for p in prev_set if self.tree.exists(p)])
				finally:
					self._bulk_update_active = False
				return
		self.controller.project_model.set_selection(selected_paths)
		self.controller.handle_file_selection_change()

	def on_search_changed(self, *args):
		if self.search_debounce_job: self.after_cancel(self.search_debounce_job)
		scroll_to_top = not self.skip_search_scroll; self.skip_search_scroll = False
		self.search_debounce_job = self.after_idle(lambda: self.display_items(scroll_to_top=scroll_to_top))

	def flush_search_debounce(self):
		if self.search_debounce_job:
			self.after_cancel(self.search_debounce_job)
			self.search_debounce_job = None
			self.display_items(scroll_to_top=False)

	def on_selected_file_clicked(self, f_path): self.update_clipboard(f_path, "Copied path to clipboard")
	def on_sort_mode_changed(self): self.refresh_selected_files_list(self.controller.project_model.get_selected_files())

	def find_and_select_project(self, buffer, event):
		values = list(self.project_dropdown["values"])
		match_val = next((v for v in values if v.split(" (")[0].lower().startswith(buffer)), None)
		if not match_val: return
		idx = values.index(match_val)
		
		lb = getattr(self, "_project_listbox", None)
		if lb and lb.winfo_exists():
			lb.selection_clear(0, tk.END); lb.selection_set(idx); lb.activate(idx); lb.see(idx)
			self.project_dropdown.set(match_val)
			self.project_dropdown.icursor(tk.END)
			if event.widget is lb: return "break"
		
		self.project_var.set(match_val)
		self.project_dropdown.event_generate("<<ComboboxSelected>>")

	# Dialog Openers & Menus
	# ------------------------------
	def open_settings_dialog(self):
		if self.controller.project_model.current_project_name: SettingsDialog(self, self.controller)
		else: self.controller.on_no_project_selected()
		
	def open_templates_dialog(self):
		if self.controller.project_model.current_project_name:
			dialog = TemplatesDialog(self, self.controller)
			self.wait_window(dialog)
			self.controller.load_templates(force_refresh=True)
		else:
			self.controller.on_no_project_selected()

	def open_history_selection(self):
		if self.controller.project_model.current_project_name: HistorySelectionDialog(self, self.controller)
		else: self.controller.on_no_project_selected()
		
	def open_output_files(self): OutputFilesDialog(self, self.controller)
	def open_text_editor(self): TextEditorDialog(self, self.controller, initial_text="")

	def show_quick_generate_menu(self): self._show_quick_menu(self.generate_menu_button_md, self.controller.generate_output)
	def show_quick_generate_menu_cb(self): self._show_quick_menu(self.generate_menu_button_cb, self.controller.generate_output_to_clipboard)

	def _show_quick_menu(self, button, command_func):
		quick_templates = self.controller.settings_model.get_display_templates()
		if not quick_templates: return
		menu = tk.Menu(self, tearoff=0)
		for tpl in quick_templates: menu.add_command(label=tpl, command=lambda t=tpl: command_func(template_override=t))
		menu.post(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())

	def show_tree_context_menu(self, event, iid):
		menu = tk.Menu(self, tearoff=0)
		is_dir = self.tree.tag_has('dir', iid)
		is_file = self.tree.tag_has('file', iid)

		if is_dir:
			menu.add_command(label="Expand Folder", command=lambda: self._toggle_all_children(iid, True))
			menu.add_command(label="Collapse Folder", command=lambda: self._toggle_all_children(iid, False))
			menu.add_separator()
			menu.add_command(label="Select All in Folder", command=lambda: self.controller.on_context_menu_action("select_folder", iid))
			menu.add_command(label="Unselect All in Folder", command=lambda: self.controller.on_context_menu_action("unselect_folder", iid))
			menu.add_separator()
			menu.add_command(label="Add to Blacklist", command=lambda: self.controller.on_context_menu_action("add_to_blacklist", iid))
			menu.add_separator()
			menu.add_command(label="Open in Explorer/Finder", command=lambda: self.controller.on_context_menu_action("open_folder_explorer", iid))
			menu.add_command(label="Open in VS Code", command=lambda: self.controller.on_context_menu_action("open_folder_vscode", iid))
			menu.add_separator()
		if is_file:
			menu.add_command(label="Open File", command=lambda: self.controller.on_context_menu_action("open_file", iid))
		
		menu.add_command(label="Copy Path", command=lambda: self.controller.on_context_menu_action("copy_path", iid))
		menu.post(event.x_root, event.y_root)

	def update_default_template_button(self): self.reset_template_btn.config(state=tk.NORMAL if self.controller.settings_model.get("default_template_name") else tk.DISABLED)
	def reset_template_to_default(self):
		default_name = self.controller.settings_model.get("default_template_name")
		if default_name and default_name in self.template_dropdown['values']: self.template_var.set(default_name)

	def bind_project_listbox(self):
		try:
			popdown_path = self.tk.call("ttk::combobox::PopdownWindow", self.project_dropdown)
			popdown_widget = self.nametowidget(popdown_path)
			def _find_listbox(widget):
				if isinstance(widget, tk.Listbox): return widget
				for child in widget.winfo_children():
					if (result := _find_listbox(child)) is not None: return result
				return None
			if (listbox := _find_listbox(popdown_widget)) is not None:
				self._project_listbox = listbox
				listbox.bind("<KeyPress>", self.controller.on_project_dropdown_search, add="+")
		except Exception as e: logger.debug("bind_project_listbox: %s", e, exc_info=False)

	# Queue Processing & Item Loading
	# ------------------------------
	def load_items_result(self, data, is_new_project):
		limit_exceeded, = data
		if limit_exceeded: show_warning_centered(self, "File Limit Exceeded", f"Only the first {self.controller.project_model.max_files} files are loaded.")
		
		self.display_items()

	def update_clipboard(self, text, status_msg=""):
		self.clipboard_clear(); self.clipboard_append(text)
		if status_msg: self.set_status_temporary(status_msg)

	# Bulk & Tree Update / Sorting
	# ------------------------------
	def select_all_tree_items(self, event=None):
		self.flush_search_debounce()
		filtered_files = {item['path'] for item in self.controller.project_model.get_filtered_items() if item['type'] == 'file'}
		if not filtered_files: return "break"
		self._bulk_update_active = True
		try:
			items_in_tree = [f for f in filtered_files if self.tree.exists(f)]
			self.tree.selection_set(items_in_tree)
		finally:
			self._bulk_update_active = False
		self.on_tree_selection_changed()
		return "break"

	def sync_treeview_selection_to_model(self):
		self._bulk_update_active = True
		try:
			current_selection = set(self.tree.selection())
			model_selection = self.controller.project_model.get_selected_files_set()
			to_select = [s for s in model_selection if s not in current_selection and self.tree.exists(s)]
			to_deselect = [s for s in current_selection if s not in model_selection and self.tree.exists(s)]
			if to_select: self.tree.selection_add(*to_select)
			if to_deselect: self.tree.selection_remove(*to_deselect)
		finally:
			self._bulk_update_active = False

	def unselect_tree_item(self, item_path):
		if self.tree.exists(item_path):
			self.tree.selection_remove(item_path)

	def toggle_select_all_tree_items(self):
		filtered_files = {item['path'] for item in self.controller.project_model.get_filtered_items() if item['type'] == 'file'}
		current_selection = set(self.tree.selection())
		
		is_all_selected = filtered_files.issubset(current_selection)

		self._bulk_update_active = True
		try:
			if not is_all_selected:
				self.tree.selection_add(*[f for f in filtered_files if self.tree.exists(f)])
			else:
				self.tree.selection_remove(*[f for f in filtered_files if self.tree.exists(f)])
		finally:
			self._bulk_update_active = False
		self.on_tree_selection_changed()

	def handle_shift_select(self, iid):
		if not self.last_clicked_item or not self.tree.exists(self.last_clicked_item):
			self.last_clicked_item = iid
			return

		all_visible_items = []
		def traverse(parent):
			for child in self.tree.get_children(parent):
				all_visible_items.append(child)
				if self.tree.item(child, 'open'): traverse(child)
		traverse('')
		
		try:
			start_idx = all_visible_items.index(self.last_clicked_item)
			end_idx = all_visible_items.index(iid)
			if start_idx > end_idx: start_idx, end_idx = end_idx, start_idx
			items_to_select = all_visible_items[start_idx:end_idx+1]
			self.tree.selection_set(items_to_select)
		except ValueError: # Item not found, e.g. due to search filter change
			self.last_clicked_item = iid

	def select_folder_items(self, folder_path, select=True):
		files_in_folder = self.controller.project_model.get_files_in_folder(folder_path)
		items_in_tree = [f for f in files_in_folder if self.tree.exists(f)]
		if not items_in_tree: return
		
		self._bulk_update_active = True
		try:
			if select: self.tree.selection_add(*items_in_tree)
			else: self.tree.selection_remove(*items_in_tree)
		finally:
			self._bulk_update_active = False
		self.on_tree_selection_changed()

	def _toggle_all_children(self, parent_iid, open_state):
		# Set the state for the parent folder itself
		if parent_iid:
			self.tree.item(parent_iid, open=open_state)
		# Recurse through children
		for child_iid in self.tree.get_children(parent_iid):
			if self.tree.tag_has('dir', child_iid):
				self.tree.item(child_iid, open=open_state)
				self._toggle_all_children(child_iid, open_state)

	def get_ui_state(self):
		expanded_folders = []
		def find_expanded(parent_iid):
			for child_iid in self.tree.get_children(parent_iid):
				if self.tree.tag_has('dir', child_iid) and self.tree.item(child_iid, 'open'):
					expanded_folders.append(child_iid)
					find_expanded(child_iid)
		find_expanded('')
		return {
			"expanded_folders": expanded_folders,
			"sort_column": self.tree_sort_column,
			"sort_reverse": self.tree_sort_reverse
		}

	def apply_ui_state(self, state):
		if not state: return

		self.tree_sort_column = state.get('sort_column', None)
		self.tree_sort_reverse = state.get('sort_reverse', False)

		if self.tree_sort_column: self._apply_tree_sort_logic()
		else: self.tree.heading('#0', text='Name'); self.tree.heading('chars', text='Chars')

		expanded_folders = state.get('expanded_folders', [])
		for folder_path in expanded_folders:
			if self.tree.exists(folder_path):
				try: self.tree.item(folder_path, open=True)
				except tk.TclError: pass # Ignore errors for items that aren't expandable

	def on_sort_column_click(self, col, is_numeric):
		if self.tree_sort_column == col:
			if self.tree_sort_reverse: self.tree_sort_column = None
			else: self.tree_sort_reverse = True
		else:
			self.tree_sort_column = col
			self.tree_sort_reverse = False

		if self.tree_sort_column is None:
			self.tree.heading('#0', text='Name')
			self.tree.heading('chars', text='Chars')
			self.display_items()
		else:
			self._apply_tree_sort_logic()

	def _apply_tree_sort_logic(self):
		col = self.tree_sort_column
		is_numeric = (col == 'chars')
		arrow = ' ▼' if self.tree_sort_reverse else ' ▲'
		self.tree.heading('#0', text='Name' + (arrow if col == 'name' else ''))
		self.tree.heading('chars', text='Chars' + (arrow if col == 'chars' else ''))

		item_size_cache = {} # Cache sizes for performance
		def get_item_size(item_id):
			if item_id in item_size_cache: return item_size_cache[item_id]
			size = 0
			if self.tree.tag_has('file', item_id):
				val_str = self.tree.set(item_id, 'chars').replace('.', '').replace(',', '')
				size = int(val_str) if val_str.isdigit() else 0
			elif self.tree.tag_has('dir', item_id):
				for child_id in self.tree.get_children(item_id):
					size += get_item_size(child_id)
			item_size_cache[item_id] = size
			return size

		def get_sort_key(item_id):
			if col == 'name':
				is_dir = self.tree.tag_has('dir', item_id)
				name = self.tree.item(item_id, 'text').lower()
				return (not is_dir, name) # Group directories first
			if is_numeric: return get_item_size(item_id)
			return self.tree.set(item_id, col).lower()

		# Recursive sort
		def sort_children(parent):
			children = list(self.tree.get_children(parent))
			decorated = [(get_sort_key(child_id), child_id) for child_id in children]
			decorated.sort(key=lambda x: x[0], reverse=self.tree_sort_reverse)
			for i, (key, child_id) in enumerate(decorated):
				self.tree.move(child_id, parent, i)
				if self.tree.tag_has('dir', child_id):
					sort_children(child_id)

		sort_children('')
		self.reapply_row_tags()