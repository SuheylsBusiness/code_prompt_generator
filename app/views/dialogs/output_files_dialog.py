# File: code_prompt_generator/app/views/dialogs/output_files_dialog.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import tkinter as tk
from tkinter import ttk, scrolledtext
import os, threading, queue, json
from app.utils.system_utils import get_relative_time_str, unify_line_endings, open_in_editor
from app.utils.ui_helpers import apply_modal_geometry, format_german_thousand_sep, show_warning_centered, show_error_centered
from app.utils.file_io import safe_read_file
from app.config import OUTPUT_DIR

# Dialog: OutputFilesDialog
# ------------------------------
class OutputFilesDialog(tk.Toplevel):
	# Initialization
	# ------------------------------
	def __init__(self, parent, controller):
		super().__init__(parent); self.parent = parent; self.controller = controller; self.title("View Outputs")
		self.all_files_meta, self.filtered_files_meta = [], []
		self.current_page, self.active_loading_filepath = 1, None
		self.items_per_page = tk.IntVar(value=100)
		self.search_thread, self.search_debounce_job = None, None
		self.search_cancelled = threading.Event()
		self.dialog_queue = queue.Queue()
		self.sort_column, self.sort_reverse = 'time', True # Default sort by time desc
		self.source_filter_var = tk.StringVar(value="All")
		self.project_name_filter_var = tk.StringVar(value="All")
		self.filter_to_current_project_var = tk.BooleanVar(value=False)
		self.load_ui_state()
		self.create_widgets()
		self.on_close_with_save = apply_modal_geometry(self, parent, "OutputFilesDialog")
		self.load_files_async()
		self.process_dialog_queue()
		self.protocol("WM_DELETE_WINDOW", self.on_close)

	# Widget Creation
	# ------------------------------
	def create_widgets(self):
		self.main_frame = ttk.Frame(self); self.main_frame.pack(fill=tk.BOTH, expand=True)
		self.main_frame.rowconfigure(2, weight=1); self.main_frame.columnconfigure(0, weight=1)
		self.create_search_widgets()
		self.create_filter_widgets()
		pane = ttk.PanedWindow(self.main_frame, orient=tk.HORIZONTAL); pane.grid(row=2, column=0, columnspan=2, sticky='nsew', padx=10, pady=(0,5))
		left_frame = ttk.Frame(pane); pane.add(left_frame, weight=3)
		cols = ("name", "time", "chars", "source", "project"); self.tree = ttk.Treeview(left_frame, columns=cols, show='headings', selectmode='browse')
		
		col_defs = {"name": ("File Name", 250), "time": ("Generated", 120), "chars": ("Chars", 80), "source": ("Source", 150), "project": ("Project", 150)}
		for col, (text, width) in col_defs.items():
			self.tree.heading(col, text=text, command=lambda c=col: self.on_sort_column_click(c))
			self.tree.column(col, width=width, stretch=(col in ["name", "source", "project"]), anchor='e' if col == "chars" else 'w')
		
		ysb = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.tree.yview); xsb = ttk.Scrollbar(left_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
		self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set); self.tree.grid(row=0, column=0, sticky='nsew')
		ysb.grid(row=0, column=1, sticky='ns'); xsb.grid(row=1, column=0, sticky='ew')
		left_frame.grid_rowconfigure(0, weight=1); left_frame.grid_columnconfigure(0, weight=1)
		
		right_frame = ttk.Frame(pane); pane.add(right_frame, weight=5)
		editor_buttons_frame = ttk.Frame(right_frame); editor_buttons_frame.pack(fill=tk.X, pady=(0, 5))
		self.save_button = ttk.Button(editor_buttons_frame, text='Save', command=self.save_current_file, state=tk.DISABLED); self.save_button.pack(side=tk.LEFT)
		ttk.Button(editor_buttons_frame, text='Copy', command=self.copy_text_to_clipboard).pack(side=tk.LEFT, padx=5)
		self.reselect_button = ttk.Button(editor_buttons_frame, text="Select Files From This Prompt", command=self.reselect_files, state=tk.DISABLED)
		self.reselect_button.pack(side=tk.LEFT, padx=5)
		ttk.Button(editor_buttons_frame, text='Open in Default Editor', command=self.open_in_editor_app).pack(side=tk.RIGHT, padx=5)
		
		self.editor_text = scrolledtext.ScrolledText(right_frame, wrap=tk.NONE, state='disabled', width=80, height=25); self.editor_text.pack(fill=tk.BOTH, expand=True)
		self.tree.bind("<<TreeviewSelect>>", self.on_file_select)
		self.create_pagination_controls()
		self.update_sort_indicator()

	def create_search_widgets(self):
		search_frame = ttk.Frame(self.main_frame); search_frame.grid(row=0, column=0, columnspan=2, sticky='ew', padx=10, pady=(10,0))
		ttk.Label(search_frame, text="Search Content:").pack(side=tk.LEFT, padx=(0, 5))
		self.search_var = tk.StringVar(); self.search_var.trace_add("write", self.on_search_term_changed)
		self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=40); self.search_entry.pack(side=tk.LEFT)
		self.search_cancel_btn = ttk.Button(search_frame, text="Cancel Search", command=self.cancel_search, state=tk.DISABLED)
		self.search_cancel_btn.pack(side=tk.LEFT, padx=5)
		self.progress_bar = ttk.Progressbar(search_frame, orient=tk.HORIZONTAL, mode='determinate', length=150)
		self.progress_bar.pack(side=tk.LEFT, padx=5)

	def create_filter_widgets(self):
		filter_frame = ttk.Frame(self.main_frame); filter_frame.grid(row=1, column=0, columnspan=2, sticky='ew', padx=10, pady=(5,5))
		ttk.Label(filter_frame, text="Filter by Project:").pack(side=tk.LEFT)
		self.project_name_filter_combo = ttk.Combobox(filter_frame, textvariable=self.project_name_filter_var, state='readonly', width=20)
		self.project_name_filter_combo.pack(side=tk.LEFT, padx=5)
		self.project_name_filter_combo.bind("<<ComboboxSelected>>", self.on_filter_changed)
		ttk.Label(filter_frame, text="Source:").pack(side=tk.LEFT)
		self.source_filter_combo = ttk.Combobox(filter_frame, textvariable=self.source_filter_var, state='readonly', width=20)
		self.source_filter_combo.pack(side=tk.LEFT, padx=5)
		self.source_filter_combo.bind("<<ComboboxSelected>>", self.on_filter_changed)
		
		project_filter_cb = ttk.Checkbutton(filter_frame, text="Only show current project", variable=self.filter_to_current_project_var, command=self.on_filter_changed)
		project_filter_cb.pack(side=tk.LEFT, padx=5)
		if not self.controller.project_model.current_project_name:
			project_filter_cb.config(state=tk.DISABLED)

	def create_pagination_controls(self):
		controls_frame = ttk.Frame(self.main_frame); controls_frame.grid(row=3, column=0, columnspan=2, sticky='ew', padx=10, pady=5)
		self.first_btn = ttk.Button(controls_frame, text="<< First", command=lambda: self.change_page('first')); self.first_btn.pack(side=tk.LEFT, padx=2)
		self.prev_btn = ttk.Button(controls_frame, text="< Prev", command=lambda: self.change_page('prev')); self.prev_btn.pack(side=tk.LEFT, padx=2)
		self.page_label = ttk.Label(controls_frame, text="Page 1 of 1"); self.page_label.pack(side=tk.LEFT, padx=5)
		self.next_btn = ttk.Button(controls_frame, text="Next >", command=lambda: self.change_page('next')); self.next_btn.pack(side=tk.LEFT, padx=2)
		self.last_btn = ttk.Button(controls_frame, text="Last >>", command=lambda: self.change_page('last')); self.last_btn.pack(side=tk.LEFT, padx=2)
		ttk.Label(controls_frame, text="Per Page:").pack(side=tk.LEFT, padx=(10, 2))
		self.page_size_combo = ttk.Combobox(controls_frame, textvariable=self.items_per_page, values=[25, 50, 100, 200, 500], width=5, state='readonly')
		self.page_size_combo.pack(side=tk.LEFT); self.page_size_combo.bind("<<ComboboxSelected>>", self.on_page_size_change)

	# Event Handlers & Public API
	# ------------------------------
	def load_files_async(self):
		self.tree.insert("", "end", text="Loading output files...", iid="loading")
		threading.Thread(target=self._load_files_worker, daemon=True).start()

	def display_page(self):
		for i in self.tree.get_children(): self.tree.delete(i)
		page_size = self.items_per_page.get(); start_index = (self.current_page - 1) * page_size
		page_items = self.filtered_files_meta[start_index:start_index + page_size]
		for item in page_items:
			values = (item['name'], get_relative_time_str(item['mtime']), format_german_thousand_sep(item['chars']), item.get('source_name', 'N/A'), item.get('project_name', 'N/A'))
			self.tree.insert("", tk.END, values=values, iid=item['path'])
		if self.tree.get_children(): self.tree.selection_set(self.tree.get_children()[0])
		self.update_pagination_controls()

	def update_pagination_controls(self):
		page_size = self.items_per_page.get(); total_items = len(self.filtered_files_meta)
		total_pages = (total_items + page_size - 1) // page_size or 1
		self.page_label.config(text=f"Page {self.current_page} of {total_pages} ({total_items} items)")
		self.first_btn.config(state=tk.NORMAL if self.current_page > 1 else tk.DISABLED)
		self.prev_btn.config(state=tk.NORMAL if self.current_page > 1 else tk.DISABLED)
		self.next_btn.config(state=tk.NORMAL if self.current_page < total_pages else tk.DISABLED)
		self.last_btn.config(state=tk.NORMAL if self.current_page < total_pages else tk.DISABLED)

	def change_page(self, action):
		total_pages = (len(self.filtered_files_meta) + self.items_per_page.get() - 1) // self.items_per_page.get() or 1
		if action == 'first': self.current_page = 1
		elif action == 'prev': self.current_page = max(1, self.current_page - 1)
		elif action == 'next': self.current_page = min(total_pages, self.current_page + 1)
		elif action == 'last': self.current_page = total_pages
		self.display_page()

	def on_page_size_change(self, event=None): self.current_page = 1; self.display_page()

	def on_file_select(self, event):
		selection = self.tree.selection()
		if not selection or selection[0] == "loading": return
		filepath = selection[0]; self.active_loading_filepath = filepath
		
		file_meta = next((m for m in self.all_files_meta if m['path'] == filepath), None)
		if file_meta and not file_meta.get('is_quick_action', True) and file_meta.get('selection') and file_meta.get('project_name') == self.controller.project_model.current_project_name:
			self.reselect_button.config(state=tk.NORMAL)
		else:
			self.reselect_button.config(state=tk.DISABLED)

		self.editor_text.config(state='normal'); self.editor_text.delete('1.0', tk.END)
		self.editor_text.insert('1.0', f"--- Loading {os.path.basename(filepath)} ---"); self.editor_text.config(state='disabled')
		self.save_button.config(state=tk.DISABLED)
		threading.Thread(target=self._load_content_worker, args=(filepath,), daemon=True).start()

	def on_search_term_changed(self, *args):
		if self.search_debounce_job: self.after_cancel(self.search_debounce_job)
		self.search_debounce_job = self.after(500, self.start_search)

	def start_search(self):
		self.cancel_search(); self.search_cancelled.clear()
		term = self.search_var.get().strip().lower()
		# Search runs on top of current filters, so we just call apply_filters_and_sort
		if not term:
			self.apply_filters_and_sort()
			return
		self.search_cancel_btn.config(state=tk.NORMAL); self.progress_bar['value'] = 0
		self.search_thread = threading.Thread(target=self._search_worker, args=(term, self.search_cancelled), daemon=True); self.search_thread.start()

	def cancel_search(self):
		if self.search_thread and self.search_thread.is_alive(): self.search_cancelled.set(); self.search_thread.join(timeout=1)
		self.search_cancel_btn.config(state=tk.DISABLED); self.progress_bar['value'] = 0

	def save_current_file(self):
		if not self.active_loading_filepath: return show_warning_centered(self, "Warning", "No file selected.")
		self.save_button.config(state=tk.DISABLED)
		threading.Thread(target=self._save_file_worker, args=(self.active_loading_filepath, self.editor_text.get('1.0', tk.END)), daemon=True).start()
		self.on_close()

	def reselect_files(self):
		selection = self.tree.selection()
		if not selection: return
		filepath = selection[0]
		file_meta = next((m for m in self.all_files_meta if m['path'] == filepath), None)
		if file_meta and file_meta.get('selection') and file_meta.get('project_name') == self.controller.project_model.current_project_name:
			self.controller.reselect_files_from_output(file_meta['selection'])
			self.on_close()
	
	def copy_text_to_clipboard(self): self.parent.update_clipboard(self.editor_text.get('1.0', tk.END).strip(), "Copied to clipboard"); self.on_close()
	def open_in_editor_app(self):
		if not self.active_loading_filepath: return show_warning_centered(self, "Warning", "No file selected.")
		try:
			content_to_save = self.editor_text.get('1.0', 'end-1c')
			with open(self.active_loading_filepath, 'w', encoding='utf-8', newline='\n') as f:
				f.write(unify_line_endings(content_to_save))
			open_in_editor(self.active_loading_filepath)
			self.on_close()
		except Exception as e: show_error_centered(self, "Error", f"Failed to save and open file: {e}")

	def on_close(self):
		self.save_ui_state()
		self.cancel_search()
		self.on_close_with_save()

	def on_sort_column_click(self, col):
		if self.sort_column == col:
			if not self.sort_reverse: self.sort_reverse = True
			else: self.sort_column, self.sort_reverse = 'time', True # Third click resets
		else: self.sort_column, self.sort_reverse = col, False
		self.apply_filters_and_sort()
		self.update_sort_indicator()
		
	def update_sort_indicator(self):
		arrow = ' ▼' if self.sort_reverse else ' ▲'
		for col in self.tree['columns']:
			text = self.tree.heading(col, 'text').split(' ')[0]
			if col == self.sort_column: self.tree.heading(col, text=text + arrow)
			else: self.tree.heading(col, text=text)

	def on_filter_changed(self, event=None):
		self.apply_filters_and_sort()
		self.save_ui_state()

	# Internal Workers & Queue
	# ------------------------------
	def process_dialog_queue(self):
		try:
			while self.winfo_exists():
				task, data = self.dialog_queue.get_nowait()
				if task == 'files_loaded':
					self.all_files_meta = data
					self.populate_filter_dropdowns()
					self.apply_filters_and_sort()
				elif task == 'search_progress': self.progress_bar['value'] = data
				elif task == 'search_done':
					self.cancel_search()
					self.apply_filters_and_sort(search_results=data)
				elif task == 'update_editor':
					content, filepath = data
					if self.winfo_exists() and self.active_loading_filepath == filepath and self.editor_text.winfo_exists():
						self.editor_text.config(state='normal'); self.editor_text.delete('1.0', tk.END)
						self.editor_text.insert('1.0', content); self.save_button.config(state=tk.NORMAL)
						self.title(f"View Outputs - [{os.path.basename(filepath)}]")
		except queue.Empty: pass
		if self.winfo_exists(): self.after(50, self.process_dialog_queue)

	def _load_files_worker(self):
		files_meta = []
		if not os.path.isdir(OUTPUT_DIR):
			if self.winfo_exists(): self.dialog_queue.put(('files_loaded', files_meta))
			return
		
		metadata_path = os.path.join(OUTPUT_DIR, '_metadata.json')
		metadata = {}
		if os.path.exists(metadata_path):
			try:
				with open(metadata_path, 'r', encoding='utf-8') as f: metadata = json.load(f)
			except (json.JSONDecodeError, IOError): pass
			
		for f in os.listdir(OUTPUT_DIR):
			if f == '_metadata.json' or not f.endswith(('.md', '.txt')): continue
			fp = os.path.join(OUTPUT_DIR, f)
			if os.path.isfile(fp):
				try:
					meta = {'name': f, 'mtime': os.path.getmtime(fp), 'chars': os.path.getsize(fp), 'path': fp}
					meta.update(metadata.get(f, {}))
					files_meta.append(meta)
				except OSError: continue
				
		if self.winfo_exists(): self.dialog_queue.put(('files_loaded', files_meta))

	def _load_content_worker(self, filepath):
		try: content = safe_read_file(filepath)
		except Exception as e: content = f"Error reading file:\n\n{e}"
		if self.winfo_exists(): self.dialog_queue.put(('update_editor', (content, filepath)))

	def _save_file_worker(self, filepath, content):
		try:
			with open(filepath, 'w', encoding='utf-8', newline='\n') as f: f.write(content)
			if self.controller and self.controller.queue:
				self.controller.queue.put(('set_status_temporary', (f"Saved {os.path.basename(filepath)}", 2000)))
		except Exception as e:
			if self.controller and self.controller.queue:
				self.controller.queue.put(('show_generic_error', ("Save Error", f"Could not save file:\n{e}")))

	def apply_filters_and_sort(self, search_results=None):
		temp_list = search_results if search_results is not None else self.all_files_meta

		if self.filter_to_current_project_var.get() and self.controller.project_model.current_project_name:
			current_project = self.controller.project_model.current_project_name
			temp_list = [m for m in temp_list if m.get('project_name') == current_project]

		selected_project = self.project_name_filter_var.get()
		if selected_project != "All":
			temp_list = [m for m in temp_list if m.get('project_name') == selected_project]

		selected_source = self.source_filter_var.get()
		if selected_source != "All":
			temp_list = [m for m in temp_list if m.get('source_name') == selected_source]

		key_map = {'name': 'name', 'time': 'mtime', 'chars': 'chars', 'source': 'source_name', 'project': 'project_name'}
		sort_key = key_map.get(self.sort_column)

		if sort_key:
			def sort_func(item):
				val = item.get(sort_key, 0 if sort_key in ['mtime', 'chars'] else '')
				if isinstance(val, str): return val.lower()
				return val
			temp_list.sort(key=sort_func, reverse=self.sort_reverse)
			
		self.filtered_files_meta = temp_list
		self.current_page = 1
		self.display_page()

	def _search_worker(self, term, cancel_event):
		base_list = self.filtered_files_meta # Search on already filtered list
		results = []; total = len(base_list)
		for i, item in enumerate(base_list):
			if cancel_event.is_set(): return
			try:
				content_chunk = ""
				with open(item['path'], 'r', encoding='utf-8', errors='ignore') as f:
					content_chunk = f.read(256 * 1024).lower() # Read first 256KB for speed
				if term in item['name'].lower() or term in content_chunk:
					results.append(item)
			except Exception: continue
			if self.winfo_exists() and total > 0: self.dialog_queue.put(('search_progress', (i + 1) / total * 100))
		if not cancel_event.is_set() and self.winfo_exists(): self.dialog_queue.put(('search_done', results))

	def populate_filter_dropdowns(self):
		sources = sorted(list(set(m.get('source_name', 'N/A') for m in self.all_files_meta if m.get('source_name'))))
		projects = sorted(list(set(m.get('project_name', 'N/A') for m in self.all_files_meta if m.get('project_name'))))
		self.source_filter_combo['values'] = ['All'] + sources
		self.project_name_filter_combo['values'] = ['All'] + projects

	def save_ui_state(self):
		proj_name = self.controller.project_model.current_project_name
		if not proj_name: return
		ui_state = self.controller.project_model.get_project_ui_state(proj_name)
		ui_state['output_dialog_filters'] = {
			'source': self.source_filter_var.get(),
			'project_name': self.project_name_filter_var.get(),
			'filter_to_current': self.filter_to_current_project_var.get()
		}
		self.controller.project_model.set_project_ui_state(proj_name, ui_state)

	def load_ui_state(self):
		proj_name = self.controller.project_model.current_project_name
		if not proj_name: return
		ui_state = self.controller.project_model.get_project_ui_state(proj_name)
		if 'output_dialog_filters' in ui_state:
			filters = ui_state['output_dialog_filters']
			self.source_filter_var.set(filters.get('source', 'All'))
			self.project_name_filter_var.set(filters.get('project_name', 'All'))
			self.filter_to_current_project_var.set(filters.get('filter_to_current', False))