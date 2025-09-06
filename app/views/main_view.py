# File: app/views/main_view.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization.

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
# from app.views.widgets.cycling_auto_combobox import CyclingAutoCombobox
import os, time, platform, threading
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
		self.setup_highlight_styles()
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
		selection_bg = self.style.lookup('Treeview', 'background', ('selected', 'focus')) or '#0078D7'
		selection_fg = self.style.lookup('Treeview', 'foreground', ('selected', 'focus')) or 'white'
		self.style.map('Treeview', background=[('selected', selection_bg)], foreground=[('selected', selection_fg)])
		self.style.configure('Treeview', rowheight=25, fieldbackground='#F3F3F3', background='#F3F3F3')
		self.style.configure('Treeview.Heading', font=('Segoe UI', 10, 'bold'))
		self.style.configure('RemoveFile.TButton', anchor='center', padding=(2,1))
		self.style.configure('Toolbutton', padding=1)
		self.quick_action_font = tkfont.Font(family='Segoe UI', size=7)
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
		self.all_project_values = []
		self.project_display_name_map = {}
		self.selected_files_sort_mode = tk.StringVar(value='default')
		self._bulk_update_active = False
		self.last_clicked_item = None
		self.tree_sort_column = None
		self.tree_sort_reverse = False
		self.bold_font = tkfont.Font(font=self.style.lookup('TLabel', 'font'))
		self.bold_font.configure(weight='bold')
		self.is_currently_searching = False
		self.managed_expanded_folders = set()
		self.item_size_cache = {}
		self.MIN_LEFT_PANE_WIDTH = 300
		self.MIN_RIGHT_PANE_WIDTH = 250
		self.resize_debounce_job = None
		self._is_enforcing_width = False
		self.selected_files_scroll_pos = 0.0
		self._content_search_thread = None
		self._content_search_cancel = None
		self._content_search_results = set()
		self._search_token = 0
		self._last_search_query = ""
		self._last_search_contents_flag = False
		self.open_dialogs = {}

	# GUI Layout Creation
	# ------------------------------
	def create_layout(self):
		self.top_frame = ttk.Frame(self); self.top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)
		self.create_top_widgets(self.top_frame)

		self.control_frame = ttk.Frame(self); self.control_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=5)
		self.create_bottom_widgets(self.control_frame)

		main_area_frame = ttk.Frame(self)
		main_area_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(5,0))
		
		self.paned_window = ttk.PanedWindow(main_area_frame, orient=tk.HORIZONTAL)
		self.paned_window.pack(fill=tk.BOTH, expand=True)
		self.paned_window.bind('<Configure>', self._on_pane_configure)

		self.file_frame = ttk.LabelFrame(self.paned_window, text="Project Files", style='FilesFrame.TLabelframe')
		self.paned_window.add(self.file_frame, weight=3)
		self.create_file_widgets(self.file_frame)
		
		self.selected_files_frame = ttk.LabelFrame(self.paned_window, text="Selected Files View", style='SelectedFiles.TLabelframe')
		self.paned_window.add(self.selected_files_frame, weight=1)
		self.selected_files_frame.bind('<Configure>', self._trigger_label_wrap_update)
		self.create_selected_files_widgets(self.selected_files_frame)

	def create_top_widgets(self, container):
		pa = ttk.LabelFrame(container, text="Select Project", style='ProjectOps.TLabelframe')
		pa.pack(side=tk.LEFT, fill=tk.Y, padx=(0,5))
		self.project_var = tk.StringVar()
		self.project_dropdown = ttk.Combobox(pa, textvariable=self.project_var, width=20, takefocus=True, state='readonly')
		self.project_dropdown.pack(anchor='w', pady=(0,5))
		self.project_dropdown.bind("<<ComboboxSelected>>", self.controller.on_project_selected)
		of = ttk.Frame(pa); of.pack(anchor='w', pady=(5,0))
		ttk.Button(of, text="Add", command=self.controller.add_project, takefocus=True).pack(side=tk.LEFT)
		ttk.Button(of, text="Open", command=self.controller.open_project_folder, takefocus=True).pack(side=tk.LEFT, padx=5)
		ttk.Button(of, text="VSC", command=self.controller.open_project_folder_vscode, takefocus=True).pack(side=tk.LEFT, padx=5)
		ttk.Button(of, text="Remove", command=self.controller.remove_project, takefocus=True).pack(side=tk.LEFT, padx=5)

		tf = ttk.LabelFrame(container, text="Template", style='TemplateOps.TLabelframe'); tf.pack(side=tk.RIGHT, fill=tk.Y, padx=(5,0))
		template_frame_inner = ttk.Frame(tf); template_frame_inner.pack(anchor='w')
		self.template_var = tk.StringVar(); self.template_var.trace_add('write', lambda *a: self.controller.request_precomputation())
		self.template_dropdown = ttk.Combobox(template_frame_inner, textvariable=self.template_var, width=20, takefocus=True, state='readonly')
		self.template_dropdown.pack(anchor='w', pady=(0,5))
		self.template_dropdown.bind("<<ComboboxSelected>>", self.controller.on_template_selected)
		
		template_buttons_frame = ttk.Frame(tf); template_buttons_frame.pack(anchor='w', pady=5)
		self.manage_templates_btn = ttk.Button(template_buttons_frame, text="Manage", command=self.open_templates_dialog, takefocus=True); self.manage_templates_btn.pack(side=tk.LEFT)
		self.reset_template_btn = ttk.Button(template_buttons_frame, text="Default", command=self.reset_template_to_default, takefocus=True, state=tk.DISABLED); self.reset_template_btn.pack(side=tk.LEFT, padx=5)

		qf = ttk.LabelFrame(container, text="Quick Actions", style='TemplateOps.TLabelframe'); qf.pack(side=tk.RIGHT, fill=tk.BOTH, padx=5, expand=True)
		self.quick_actions_frame = ttk.Frame(qf)
		self.quick_actions_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
		self.quick_actions_frame.bind("<Configure>", self._update_button_wraplength)

	def create_file_widgets(self, container):
		sf = ttk.Frame(container); sf.pack(fill=tk.X, padx=5, pady=(5,2))
		ttk.Label(sf, text="Search:").pack(side=tk.LEFT, padx=(0,5))
		self.file_search_var = tk.StringVar(); self.file_search_var.trace_add("write", self.on_search_changed)
		ttk.Entry(sf, textvariable=self.file_search_var, width=25, takefocus=True).pack(side=tk.LEFT)
		ttk.Button(sf, text="✕", command=lambda: self.file_search_var.set(""), style='Toolbutton').pack(side=tk.LEFT, padx=(5,0))
		self.search_contents_var = tk.BooleanVar(value=False)
		ttk.Checkbutton(sf, text="Search file contents", variable=self.search_contents_var, command=self.on_search_changed).pack(side=tk.LEFT, padx=(10,0))

		tf = ttk.Frame(container); tf.pack(fill=tk.X, padx=5, pady=(5,2))
		self.select_all_button = ttk.Button(tf, text="Select All", command=self.controller.toggle_select_all, takefocus=True); self.select_all_button.pack(side=tk.LEFT)
		self.reset_button = ttk.Button(tf, text="Reset", command=self.controller.reset_selection, takefocus=True); self.reset_button.pack(side=tk.LEFT, padx=5)
		self.file_selected_label = ttk.Label(tf, text="Files: 0/0 | Total Chars: 0", width=60); self.file_selected_label.pack(side=tk.LEFT, padx=10)

		tree_frame = ttk.Frame(container); tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
		tree_frame.rowconfigure(0, weight=1); tree_frame.columnconfigure(0, weight=1)
		self.tree = ttk.Treeview(tree_frame, columns=('chars',), show='tree headings', selectmode='extended')
		self.tree.heading('#0', text='Name', command=lambda: self.on_sort_column_click('name'))
		self.tree.heading('chars', text='Chars', command=lambda: self.on_sort_column_click('chars'))
		self.tree.column('#0', stretch=True, width=300); self.tree.column('chars', stretch=False, width=80, anchor='e')
		vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
		hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
		self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
		self.tree.grid(row=0, column=0, sticky='nsew'); vsb.grid(row=0, column=1, sticky='ns'); hsb.grid(row=1, column=0, sticky='ew')
		
		self.tree.tag_configure('dir', font=self.bold_font)
		self.tree.tag_configure('oddrow', background='#FFFFFF')
		self.tree.tag_configure('evenrow', background='#F3F3F3')

		self.tree.bind('<<TreeviewSelect>>', self.on_tree_selection_changed)
		self.tree.bind('<Button-1>', self.on_tree_interaction)
		self.tree.bind('<Double-1>', self.on_tree_double_click)
		self.tree.bind('<Button-3>', self.on_tree_right_click)
		self.tree.bind('<Button-2>', self.on_tree_right_click)
		self.tree.bind('<Control-a>', self.select_all_tree_items)
		self.tree.bind('<Control-A>', self.select_all_tree_items)

	def create_selected_files_widgets(self, container):
		sort_frame = ttk.Frame(container); sort_frame.pack(fill=tk.X, padx=5, pady=0)
		ttk.Label(sort_frame, text="Sort by:").pack(side=tk.LEFT)
		ttk.Radiobutton(sort_frame, text="Default", variable=self.selected_files_sort_mode, value="default", command=self.on_sort_mode_changed).pack(side=tk.LEFT, padx=5)
		ttk.Radiobutton(sort_frame, text="Char Count", variable=self.selected_files_sort_mode, value="char_count", command=self.on_sort_mode_changed).pack(side=tk.LEFT)
		self.selected_files_scrolled_frame = ScrolledFrame(container, side=tk.TOP, expand=True, fill=tk.BOTH, padx=5, pady=5, add_horizontal_scrollbar=False); self.selected_files_canvas = self.selected_files_scrolled_frame.canvas; self.selected_files_inner = self.selected_files_scrolled_frame.inner_frame

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

	def set_status_temporary(self, msg, duration=2500):
		try:
			d = int(duration) if duration is not None else 2500
		except Exception:
			d = 2500
		d = max(1500, min(d, 6000))
		self.status_label.config(text=msg)
		self.after(d, lambda: self.status_label.config(text="Ready"))

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

	def display_items(self):
		query = self.file_search_var.get().strip().lower()
		is_searching = bool(query)
		search_contents = self.search_contents_var.get()

		if is_searching and not self.is_currently_searching:
			self._save_ui_state()
		self.is_currently_searching = is_searching

		if query != self._last_search_query or search_contents != self._last_search_contents_flag:
			if self._content_search_cancel: self._content_search_cancel.set()
			self._content_search_results = set()
			self._content_search_thread = None
			self._search_token += 1
			self._last_search_query = query
			self._last_search_contents_flag = search_contents
			if is_searching and search_contents: self._start_async_content_search(query, self._search_token)

		self.tree.delete(*self.tree.get_children())
		
		if query:
			filtered = []
			all_contents = self.controller.project_model.file_contents
			for it in self.controller.project_model.all_items:
				path_match = query in it["path"].lower()
				content_match = False
				if search_contents and it['type'] == 'file':
					if it['path'] in self._content_search_results: content_match = True
				if path_match or content_match:
					filtered.append(it)
		else:
			filtered = self.controller.project_model.all_items

		self.controller.project_model.set_filtered_items(filtered)
		
		parents = {"": ""}
		for item in filtered:
			path = item['path']
			parent_path = os.path.dirname(path.rstrip('/')).replace('\\', '/')
			parent_iid = parents.get(parent_path, "")
			
			if item["type"] == "dir":
				text = f"📁 {os.path.basename(path.rstrip('/'))}"
				is_open = is_searching or path in self.managed_expanded_folders
				iid = self.tree.insert(parent_iid, 'end', iid=path, text=text, open=is_open, tags=('dir',))
				parents[path.rstrip('/')] = iid
			else:
				text = f"📄 {os.path.basename(path)}"
				char_count = self.controller.project_model.file_char_counts.get(path, 0)
				char_count_str = format_german_thousand_sep(char_count)
				iid = self.tree.insert(parent_iid, 'end', iid=path, text=text, values=(char_count_str,), tags=('file',))
		
		self.reapply_row_tags()
		self.sync_treeview_selection_to_model()
			
		self.reset_button_clicked = False; self.is_silent_refresh = False

	def _start_async_content_search(self, query, token):
		if not query: return
		if self._content_search_cancel: self._content_search_cancel.set()
		cancel = threading.Event(); self._content_search_cancel = cancel

		def worker():
			results = set()
			try:
				# Use ProjectModel's optimized content search (Req 4)
				file_paths = [it['path'] for it in self.controller.project_model.all_items if it['type'] == 'file']
				results = self.controller.project_model.search_file_contents(query, file_paths, cancel)

			except Exception as e:
				logger.error(f"Content search failed: {e}", exc_info=True)
			finally:
				if not cancel.is_set() and token == self._search_token:
					self._content_search_results = results
					if self.winfo_exists(): self.after_idle(self.display_items)
		
		self._content_search_thread = threading.Thread(target=worker, daemon=True); self._content_search_thread.start()
	
	def reapply_row_tags(self):
		max_val = self.controller.settings_model.get('highlight_max_value', 200)
		try: max_val = int(max_val)
		except Exception: max_val = 200
		if max_val < 1: max_val = 1
		proj_name = self.controller.project_model.current_project_name
		selection_counts = {}
		if proj_name and self.controller.project_model.exists(proj_name):
			selection_counts = self.controller.project_model.get_project_data(proj_name, "selection_counts", {})
		dir_freq = {}
		for p, c in selection_counts.items():
			parts = p.replace('\\','/').split('/')
			for i in range(1, len(parts)):
				prefix = '/'.join(parts[:i]) + '/'
				if c > dir_freq.get(prefix, 0): dir_freq[prefix] = c
		def apply_tags_recursive(parent_iid, index):
			for child_iid in self.tree.get_children(parent_iid):
				current_tags = list(self.tree.item(child_iid, 'tags'))
				base_tags = [t for t in current_tags if t not in ('oddrow', 'evenrow') and not t.startswith('highlight_') and not t.startswith('hl_')]
				count = 0
				if self.tree.tag_has('file', child_iid):
					count = selection_counts.get(child_iid, 0)
				else:
					key = child_iid if child_iid.endswith('/') else child_iid + '/'
					count = dir_freq.get(key, 0)
				idx = min(max(count, 0), max_val)
				parity = 'odd' if index % 2 else 'even'
				highlight_tag = f"hl_{parity}_{idx}"
				new_tags = base_tags + [highlight_tag]
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
		self.managed_expanded_folders.clear()
		self.controller.project_model.set_items([]);
		self.tree.delete(*self.tree.get_children())
		for w in self.selected_files_inner.winfo_children(): w.destroy()
		self.controller.handle_file_selection_change()

	def clear_ui_for_loading(self):
		self.is_currently_searching = False
		self.managed_expanded_folders.clear()
		self.tree.delete(*self.tree.get_children())
		for w in self.selected_files_inner.winfo_children(): w.destroy()
		self.update_selection_count_label(0, "0")
		self.refresh_selected_files_list([])
		self.update_select_all_button()

	def show_loading_placeholder(self):
		self.tree.insert("", "end", text="Loading project files...", iid="loading_placeholder")

	def update_project_list(self, projects_data):
		self.project_display_name_map.clear()
		display_names = []
		for n, lu, uc in projects_data:
			display_name = f"{n} ({get_relative_time_str(lu)})" if lu > 0 else n
			display_names.append(display_name)
			self.project_display_name_map[display_name] = n

		self.all_project_values = display_names
		
		if self.project_dropdown.focus_get() == self.project_dropdown:
			return

		current_project_name = self.controller.project_model.current_project_name
		display_name_to_set = ""
		if current_project_name:
			display_name_to_set = self.get_display_name_for_project(current_project_name)
		
		self.project_dropdown['values'] = self.all_project_values
		
		setattr(self.project_dropdown, '_programmatic_update', True)
		try:
			if display_name_to_set and display_name_to_set in self.all_project_values:
				self.project_var.set(display_name_to_set)
			elif self.all_project_values:
				self.project_var.set(self.all_project_values[0])
			else:
				self.project_var.set("")
		finally:
			self.after(10, lambda: setattr(self.project_dropdown, '_programmatic_update', False))
			
		if self.all_project_values:
			self.project_dropdown.configure(width=max(max((len(d) for d in self.all_project_values), default=20), 20))

	def get_display_name_for_project(self, name):
		for disp, orig in self.project_display_name_map.items():
			if orig == name:
				return disp
		return name

	def update_template_dropdowns(self, force_refresh):
		display_templates = self.controller.settings_model.get_display_templates()
		if not force_refresh and list(self.template_dropdown['values']) == display_templates: return
		self.template_dropdown['values'] = display_templates
		if display_templates: self.template_dropdown.config(height=min(len(display_templates), 15), width=max(max((len(x) for x in display_templates), default=0)+2, 20))
		for widget in self.quick_actions_frame.winfo_children(): widget.destroy()
		qc_template_items = self.controller.settings_model.get_quick_copy_templates()
		editor_tools = ["Truncate Between '---'", "Replace \"**\"", "Gemini Whitespace Fix", "Remove Duplicates", "Sort Alphabetically", "Sort by Length", "Escape Text", "Unescape Text"]
		custom_scripts = {"header_formatter": "Format Source Headers"}
		actions_to_create = []
		if qc_template_items: actions_to_create.extend([{'name': name.replace("[CB]: ", ""), 'id': name} for name in qc_template_items])
		actions_to_create.extend([{'name': name, 'id': name} for name in editor_tools])
		actions_to_create.extend([{'name': display, 'id': script_id} for script_id, display in custom_scripts.items()])
		history = self.controller.settings_model.get('quick_action_history', {}); max_button_val = 20
		row, col, max_cols = 0, 0, 3
		for action in actions_to_create:
			count = history.get(action['id'], {}).get('count', 0)
			style_idx = min(count, max_button_val)
			style_name = f"QA_hl_{style_idx}.TButton"
			btn = ttk.Button(self.quick_actions_frame, text=action['name'], command=lambda a=action['id']: self.controller._execute_quick_action(a), style=style_name)
			btn.original_text = action['name']
			btn.grid(row=row, column=col, sticky='ew', padx=2, pady=1)
			col += 1
			if col >= max_cols: col, row = 0, row + 1
		for c in range(max_cols): self.quick_actions_frame.columnconfigure(c, weight=1)
		self.after(10, self._update_button_wraplength)
		default_to_set = self.controller.settings_model.get("default_template_name")
		if default_to_set and default_to_set in display_templates: self.template_var.set(default_to_set)
		elif display_templates: self.template_var.set(display_templates[0])
		else: self.template_var.set("")

	def refresh_selected_files_list(self, selected):
		try:
			prev_pos = self.selected_files_canvas.yview()[0]
		except Exception:
			prev_pos = getattr(self, 'selected_files_scroll_pos', 0.0)

		for w in self.selected_files_inner.winfo_children(): w.destroy()
		if self.selected_files_sort_mode.get() == 'char_count':
			selected = sorted(selected, key=lambda f: self.controller.project_model.file_char_counts.get(f, 0), reverse=True)

		self.update_idletasks()
		for f in selected:
			rf = ttk.Frame(self.selected_files_inner); rf.pack(fill=tk.X, expand=True, pady=(0, 2))
			self.selected_files_scrolled_frame.bind_mousewheel_to_widget(rf)
			xb = ttk.Button(rf, text="x", width=1, style='RemoveFile.TButton', command=lambda ff=f: self.unselect_tree_item(ff))
			xb.pack(side=tk.LEFT, padx=(2, 5), anchor='n'); self.selected_files_scrolled_frame.bind_mousewheel_to_widget(xb)

			txt = tk.Text(rf, wrap='word', height=1, borderwidth=0, highlightthickness=0, bg='#F3F3F3')

			depth_mode = self.controller.settings_model.get('selected_files_path_depth', 'Full')
			path_to_display = f
			if depth_mode.isdigit():
				depth = int(depth_mode)
				parts = f.replace('\\', '/').split('/')
				if len(parts) > depth:
					path_to_display = '/'.join(parts[-(depth + 1):])
			
			dir_part = os.path.dirname(path_to_display).replace('\\','/')
			base = os.path.basename(path_to_display)

			prefix = (dir_part + '/' if dir_part else '')
			txt.tag_configure('b', font=self.bold_font)
			txt.insert('1.0', prefix); txt.insert('end', base, 'b')
			txt.insert('end', f" [{format_german_thousand_sep(self.controller.project_model.file_char_counts.get(f, 0))}]")
			txt.config(state='disabled', cursor='hand2')
			txt.pack(side=tk.LEFT, fill=tk.X, expand=True)
			txt.bind("<Button-1>", lambda e, ff=f: self.on_selected_file_clicked(ff))
			self.selected_files_scrolled_frame.bind_mousewheel_to_widget(txt)

		self.selected_files_inner.update_idletasks()
		try:
			for child in self.selected_files_inner.winfo_children():
				for widget in child.winfo_children():
					if isinstance(widget, tk.Text):
						lines = int(widget.count("1.0", "end-1c", "displaylines")[0])
						widget.config(height=max(1, lines))
		except Exception: pass

		self.selected_files_canvas.yview_moveto(prev_pos)
		self.selected_files_scroll_pos = prev_pos

	def update_select_all_button(self):
		filtered_files = {item['path'] for item in self.controller.project_model.get_filtered_items() if item['type'] == 'file'}
		if filtered_files:
			is_all_selected = filtered_files.issubset(self.controller.project_model.get_selected_files_set())
			self.select_all_button.config(text="Unselect All" if is_all_selected else "Select All")
		else:
			self.select_all_button.config(text="Select All")

	def update_file_char_counts(self):
		for path, count in list(self.controller.project_model.file_char_counts.items()):
			if self.tree.exists(path):
				self.tree.set(path, 'chars', format_german_thousand_sep(count))
		if self.tree_sort_column == 'chars':
			self._apply_tree_sort_logic()
		else:
			self.reapply_row_tags()

	# Event Handlers & User Interaction
	# ------------------------------
	def _trigger_label_wrap_update(self, event=None):
		if self.resize_debounce_job:
			self.after_cancel(self.resize_debounce_job)
		self.resize_debounce_job = self.after(50, self._update_label_wraps)

	def _on_pane_configure(self, event=None):
		if self._is_enforcing_width: return
		self._is_enforcing_width = True
		try:
			sash_pos = self.paned_window.sashpos(0)
			if sash_pos < self.MIN_LEFT_PANE_WIDTH:
				self.paned_window.sashpos(0, self.MIN_LEFT_PANE_WIDTH)
			
			total_width = self.paned_window.winfo_width()
			if total_width - sash_pos < self.MIN_RIGHT_PANE_WIDTH:
				self.paned_window.sashpos(0, total_width - self.MIN_RIGHT_PANE_WIDTH)
		finally:
			self._is_enforcing_width = False

	def _update_label_wraps(self):
		self.resize_debounce_job = None
		if not self.selected_files_inner.winfo_exists(): return
		self.selected_files_inner.update_idletasks()
		for child in self.selected_files_inner.winfo_children():
			if not child.winfo_exists():
				continue
			for widget in child.winfo_children():
				if isinstance(widget, tk.Text):
					try:
						lines = int(widget.count("1.0", "end-1c", "displaylines")[0])
						widget.config(height=max(1, lines))
					except Exception: pass
	
	def _wrap_text_for_button(self, text, max_width):
		return text

	def _update_button_wraplength(self, event=None):
		if not self.quick_actions_frame.winfo_exists(): return
		for btn in self.quick_actions_frame.winfo_children():
			if isinstance(btn, ttk.Button) and hasattr(btn, 'original_text'):
				if btn.cget('text') != btn.original_text: btn.config(text=btn.original_text)

	def on_tree_interaction(self, event):
		iid = self.tree.identify_row(event.y)
		if not iid: return

		if self.tree.identify_element(event.x, event.y) == 'Treeitem.indicator':
			if self.tree.item(iid, 'open'):
				self.managed_expanded_folders.discard(iid)
			else:
				self.managed_expanded_folders.add(iid)
			self.after_idle(self._save_ui_state)
			self.after_idle(self.reapply_row_tags)
		
		if event.state & 0x0001:
			self.handle_shift_select(iid)
		else:
			self.last_clicked_item = iid

	def on_tree_double_click(self, event):
		iid = self.tree.identify_row(event.y)
		if not iid: return
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
		tree_selection_paths = {iid for iid in selected_iids if self.tree.tag_has('file', iid)}

		if selected_iids and not tree_selection_paths:
			prev_set = self.controller.project_model.get_selected_files_set()
			if prev_set:
				self._bulk_update_active = True
				try: self.tree.selection_set([p for p in prev_set if self.tree.exists(p)])
				finally: self._bulk_update_active = False
			return

		if self.is_currently_searching:
			visible_files = {item['path'] for item in self.controller.project_model.get_filtered_items() if item['type'] == 'file'}
			model_selection = self.controller.project_model.get_selected_files_set()
			preserved_selection = model_selection - visible_files
			new_selection = preserved_selection | tree_selection_paths
			self.controller.project_model.set_selection(new_selection)
		else:
			self.controller.project_model.set_selection(tree_selection_paths)

		self.controller.handle_file_selection_change()

	def on_search_changed(self, *args):
		if self.search_debounce_job: self.after_cancel(self.search_debounce_job)
		def debounced_search():
			self.display_items()
			if self.file_search_var.get(): self.scroll_tree_to(0.0)
		self.search_debounce_job = self.after_idle(debounced_search)

	def flush_search_debounce(self):
		if self.search_debounce_job:
			self.after_cancel(self.search_debounce_job)
			self.search_debounce_job = None
			self.display_items()

	def on_selected_file_clicked(self, f_path):
		self.update_clipboard(f_path, "Copied path to clipboard")
		if not self.controller.settings_model.get('autofocus_on_select', True): return

		if self.tree.exists(f_path):
			parent = self.tree.parent(f_path)
			while parent:
				if not self.tree.item(parent, "open"):
					self.tree.item(parent, open=True)
					self.managed_expanded_folders.add(parent)
				parent = self.tree.parent(parent)
			self.tree.see(f_path)
			self.tree.focus(f_path)

	def on_sort_mode_changed(self): self.refresh_selected_files_list(self.controller.project_model.get_selected_files())

	# Dialog Openers & Menus
	# ------------------------------
	def _open_single_instance_dialog(self, key, button, DialogClass, requires_project=True, wait=False, on_close_callback=None, args=()):
		if self.open_dialogs.get(key) and self.open_dialogs[key].winfo_exists():
			self.open_dialogs[key].focus_force()
			self.open_dialogs[key].lift()
			return
		if requires_project and not self.controller.project_model.current_project_name:
			self.controller.on_no_project_selected()
			return
		button.config(state=tk.DISABLED)
		dialog = DialogClass(self, self.controller, *args)
		self.open_dialogs[key] = dialog
		def on_destroy(event):
			if event.widget == dialog:
				button.config(state=tk.NORMAL)
				if self.open_dialogs.get(key) == dialog: del self.open_dialogs[key]
		dialog.bind("<Destroy>", on_destroy)
		if wait: self.wait_window(dialog)
		if on_close_callback: on_close_callback()

	def open_settings_dialog(self): self._open_single_instance_dialog('settings', self.settings_button, SettingsDialog)
	def open_templates_dialog(self): self._open_single_instance_dialog('templates', self.manage_templates_btn, TemplatesDialog, wait=True, on_close_callback=lambda: self.controller.load_templates(force_refresh=True))
	def open_history_selection(self): self._open_single_instance_dialog('history', self.history_button, HistorySelectionDialog)
	def open_output_files(self): self._open_single_instance_dialog('outputs', self.view_outputs_button, OutputFilesDialog, requires_project=False)
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
			menu.add_command(label="Expand All Subfolders", command=lambda: self._toggle_all_children(iid, True))
			menu.add_command(label="Collapse All Subfolders", command=lambda: self._toggle_all_children(iid, False))
			menu.add_separator()
			menu.add_command(label="Select All in Folder", command=lambda: self.controller.on_context_menu_action("select_folder", iid))
			menu.add_command(label="Unselect All in Folder", command=lambda: self.controller.on_context_menu_action("unselect_folder", iid))
			menu.add_separator()
			menu.add_command(label="Open in Explorer/Finder", command=lambda: self.controller.on_context_menu_action("open_folder_explorer", iid))
			menu.add_command(label="Open in VS Code", command=lambda: self.controller.on_context_menu_action("open_folder_vscode", iid))
		
		if is_file:
			if menu.index('end') is not None:
				menu.add_separator()
			menu.add_command(label="Open File", command=lambda: self.controller.on_context_menu_action("open_file", iid))
		
		if menu.index('end') is not None:
			menu.add_separator()
		menu.add_command(label="Add to Blacklist", command=lambda: self.controller.on_context_menu_action("add_to_blacklist", iid))
		
		menu.add_command(label="Copy Path", command=lambda: self.controller.on_context_menu_action("copy_path", iid))
		menu.post(event.x_root, event.y_root)

	def update_default_template_button(self): self.reset_template_btn.config(state=tk.NORMAL if self.controller.settings_model.get("default_template_name") else tk.DISABLED)
	def reset_template_to_default(self):
		default_name = self.controller.settings_model.get("default_template_name")
		if default_name and default_name in self.template_dropdown['values']: self.template_var.set(default_name)

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
		except ValueError:
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
		descendant_dirs = {item['path'] for item in self.controller.project_model.all_items
							if item['type'] == 'dir' and item['path'].startswith(parent_iid)}
		descendant_dirs.add(parent_iid)

		if open_state:
			self.managed_expanded_folders.update(descendant_dirs)
		else:
			self.managed_expanded_folders.difference_update(descendant_dirs)

		for iid in descendant_dirs:
			if self.tree.exists(iid):
				self.tree.item(iid, open=open_state)
		
		self._save_ui_state()
		self.after_idle(self.reapply_row_tags)

	def get_ui_state(self):
		return {
			"expanded_folders": list(self.managed_expanded_folders),
			"sort_column": self.tree_sort_column,
			"sort_reverse": self.tree_sort_reverse
		}

	def apply_ui_state(self, state):
		if not state:
			self.managed_expanded_folders.clear()
			self.tree_sort_column = None
			self.tree_sort_reverse = False
			return
		self.tree_sort_column = state.get('sort_column', None)
		self.tree_sort_reverse = state.get('sort_reverse', False)
		self.managed_expanded_folders = set(state.get('expanded_folders', []))
		if self.tree_sort_column:
			self._apply_tree_sort_logic()
		else:
			self.tree.heading('#0', text='Name')
			self.tree.heading('chars', text='Chars')

	def on_sort_column_click(self, col):
		if self.tree_sort_column != col:
			self.tree_sort_column = col
			self.tree_sort_reverse = False
		elif not self.tree_sort_reverse:
			self.tree_sort_reverse = True
		else:
			self.tree_sort_column = None
			self.tree_sort_reverse = False

		self._save_ui_state()

		if self.tree_sort_column is None:
			self.tree.heading('#0', text='Name')
			self.tree.heading('chars', text='Chars')
			self.display_items()
		else:
			self._apply_tree_sort_logic()

	# Highlighting
	# ------------------------------
	def _blend_color(self, bg_hex, fg_hex, t):
		bg = self.winfo_rgb(bg_hex); fg = self.winfo_rgb(fg_hex)
		r = int(((bg[0]*(1-t)) + (fg[0]*t)) / 257)
		g = int(((bg[1]*(1-t)) + (fg[1]*t)) / 257)
		b = int(((bg[2]*(1-t)) + (fg[2]*t)) / 257)
		return f"#{r:02x}{g:02x}{b:02x}"

	def _tinted_step_color(self, base_hex, bg_hex, idx, max_val):
		try: mv = int(max_val)
		except Exception: mv = 200
		if mv < 1: mv = 1
		t = max(0, min(idx, mv)) / mv
		t = t ** 0.5
		return self._blend_color(bg_hex, base_hex, t)

	def setup_highlight_styles(self):
		base_color = self.controller.settings_model.get('highlight_base_color', '#ADD8E6')
		max_val = self.controller.settings_model.get('highlight_max_value', 200)
		try: max_val = int(max_val)
		except Exception: max_val = 200
		if max_val < 1: max_val = 1
		odd_bg = '#FFFFFF'; even_bg = '#F3F3F3'
		for i in range(max_val + 1):
			self.tree.tag_configure(f"hl_odd_{i}", background=self._tinted_step_color(base_color, odd_bg, i, max_val))
			self.tree.tag_configure(f"hl_even_{i}", background=self._tinted_step_color(base_color, even_bg, i, max_val))
		max_button_val = 20
		button_bg = self.style.lookup('TButton', 'background')
		active_button_bg = self.style.lookup('TButton', 'background', ('active',))
		for i in range(max_button_val + 1):
			color = self._tinted_step_color(base_color, button_bg, i, max_button_val)
			active_color = self._tinted_step_color(base_color, active_button_bg, i, max_button_val)
			style_name = f"QA_hl_{i}.TButton"
			self.style.configure(style_name, font=('Segoe UI', 9), padding=(3, 1), background=color, lightcolor=color, darkcolor=color, bordercolor=color)
			self.style.map(style_name,
				background=[('active', active_color), ('pressed', active_color)],
				lightcolor=[('active', active_color), ('pressed', active_color)],
				darkcolor=[('active', active_color), ('pressed', active_color)],
				bordercolor=[('active', color), ('pressed', color)])

	def update_file_highlighting(self):
		self.reapply_row_tags()

	# UI State – immediate persistence
	# ------------------------------
	def _save_ui_state(self):
		if self.is_currently_searching: return
		cp = self.controller.project_model.current_project_name
		if cp:
			self.controller.project_model.set_project_ui_state(cp, self.get_ui_state())

	def _apply_tree_sort_logic(self):
		col = self.tree_sort_column
		arrow = ' ▼' if self.tree_sort_reverse else ' ▲'
		self.tree.heading('#0', text='Name' + (arrow if col == 'name' else ''))
		self.tree.heading('chars', text='Chars' + (arrow if col == 'chars' else ''))

		def get_item_size(item_id):
			if item_id in self.item_size_cache: return self.item_size_cache[item_id]
			size = 0
			if self.tree.tag_has('file', item_id):
				size = self.controller.project_model.file_char_counts.get(item_id, 0)
			elif self.tree.tag_has('dir', item_id):
				for child_id in self.tree.get_children(item_id):
					size += get_item_size(child_id)
			self.item_size_cache[item_id] = size
			return size

		def get_sort_key(item_id):
			if col == 'name':
				is_dir = self.tree.tag_has('dir', item_id)
				name = self.tree.item(item_id, 'text').lower()
				if name.startswith(('📁 ', '📄 ')): name = name[2:]
				return (not is_dir, name)
			if col == 'chars': return get_item_size(item_id)
			return self.tree.set(item_id, col).lower()

		def sort_children(parent):
			children = list(self.tree.get_children(parent))
			if not children: return
			decorated = [(get_sort_key(child_id), child_id) for child_id in children]
			decorated.sort(key=lambda x: x[0], reverse=self.tree_sort_reverse)
			for i, (key, child_id) in enumerate(decorated):
				self.tree.move(child_id, parent, i)
				if self.tree.tag_has('dir', child_id):
					sort_children(child_id)

		sort_children('')
		self.reapply_row_tags()