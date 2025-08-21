# File: code_prompt_generator/app/views/dialogs/history_selection_dialog.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import tkinter as tk
from tkinter import ttk
import platform
from datetime import datetime
from app.utils.system_utils import get_relative_time_str
from app.utils.ui_helpers import apply_modal_geometry, handle_mousewheel, format_german_thousand_sep, create_enhanced_text_widget
from app.config import HISTORY_SELECTION_KEY

# Dialog: HistorySelectionDialog
# ------------------------------
class HistorySelectionDialog(tk.Toplevel):
	# Initialization
	# ------------------------------
	_HEIGHT_CACHE = {}; _TEXT_CACHE = {}; _MAX_TEXT_LINES = 12
	def __init__(self, parent, controller):
		super().__init__(parent); self.parent = parent; self.controller = controller; self.title("History Selection")
		self.all_history_items = []; self.warning_labels = {}; self.current_page = 1; self.items_per_page = tk.IntVar(value=10)
		self._last_width = 0; self._mw_tag = f"{self.__class__.__name__}_{self.winfo_id()}"; self._text_widgets = []; self._resize_jobs = {}
		self.on_close_handler = apply_modal_geometry(self, parent, "HistorySelectionDialog")
		self.create_widgets(); self.after(0, self.load_history)
		self.protocol("WM_DELETE_WINDOW", self._close)
		self.bind("<Alt-F4>", lambda e: self._close()); self.bind("<Escape>", lambda e: self._close())
		if platform.system() == "Darwin": self.bind("<Command-w>", lambda e: self._close())
		self.bind_class(self._mw_tag, "<MouseWheel>", self._global_wheel); self.bind_class(self._mw_tag, "<Button-4>", self._global_wheel); self.bind_class(self._mw_tag, "<Button-5>", self._global_wheel)
		self._apply_wheel_tag(self)
		try: self.grab_release()
		except Exception: pass
		try: self.transient(None)
		except Exception: pass

	# Widget Creation
	# ------------------------------
	def create_widgets(self):
		self.main_frame = ttk.Frame(self); self.main_frame.pack(fill=tk.BOTH, expand=True)
		self.main_frame.rowconfigure(0, weight=1); self.main_frame.columnconfigure(0, weight=1)
		canvas_frame = ttk.Frame(self.main_frame); canvas_frame.grid(row=0, column=0, sticky='nsew', padx=10, pady=(10,0))
		canvas_frame.rowconfigure(0, weight=1); canvas_frame.columnconfigure(0, weight=1)
		self.canvas = tk.Canvas(canvas_frame, borderwidth=0)
		self.scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
		self.canvas.configure(yscrollcommand=self.scrollbar.set)
		self.canvas.grid(row=0, column=0, sticky='nsew'); self.scrollbar.grid(row=0, column=1, sticky='ns')
		self.content_frame = ttk.Frame(self.canvas)
		self.canvas.create_window((0, 0), window=self.content_frame, anchor='nw', tags="frame")
		self.content_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
		self.canvas.bind("<Configure>", self._on_canvas_configure)
		self.create_pagination_controls()

	def create_pagination_controls(self):
		controls_frame = ttk.Frame(self.main_frame); controls_frame.grid(row=1, column=0, sticky='ew', padx=10, pady=5)
		self.first_btn = ttk.Button(controls_frame, text="<< First", command=lambda: self.change_page('first')); self.first_btn.pack(side=tk.LEFT, padx=2)
		self.prev_btn = ttk.Button(controls_frame, text="< Prev", command=lambda: self.change_page('prev')); self.prev_btn.pack(side=tk.LEFT, padx=2)
		self.page_label = ttk.Label(controls_frame, text="Page 1 of 1"); self.page_label.pack(side=tk.LEFT, padx=5)
		self.next_btn = ttk.Button(controls_frame, text="Next >", command=lambda: self.change_page('next')); self.next_btn.pack(side=tk.LEFT, padx=2)
		self.last_btn = ttk.Button(controls_frame, text="Last >>", command=lambda: self.change_page('last')); self.last_btn.pack(side=tk.LEFT, padx=2)
		ttk.Label(controls_frame, text="Per Page:").pack(side=tk.LEFT, padx=(10, 2))
		self.page_size_combo = ttk.Combobox(controls_frame, textvariable=self.items_per_page, values=[10, 20, 50, 100], width=5, state='readonly')
		self.page_size_combo.pack(side=tk.LEFT); self.page_size_combo.bind("<<ComboboxSelected>>", self.on_page_size_change)

	# Event Handlers & Public API
	# ------------------------------
	def _on_canvas_configure(self, event):
		self.canvas.itemconfig('frame', width=event.width); self._last_width = int(event.width)
		for w in self._text_widgets:
			try: self._schedule_fit_text(w)
			except Exception: pass

	def _global_wheel(self, e):
		handle_mousewheel(e, self.canvas); return "break"

	def _apply_wheel_tag(self, widget):
		try:
			tags = widget.bindtags()
			if self._mw_tag not in tags: widget.bindtags((self._mw_tag,)+tags)
			for c in widget.winfo_children(): self._apply_wheel_tag(c)
		except Exception: pass

	def _schedule_fit_text(self, w):
		try:
			if not w or not w.winfo_exists(): return
			if w in self._resize_jobs:
				try: self.after_cancel(self._resize_jobs[w])
				except Exception: pass
			self._resize_jobs[w] = self.after(30, lambda ww=w: self._fit_text(ww))
		except Exception: pass

	def _cache_key(self, item_id): return (item_id, max(1, self._last_width or self.canvas.winfo_width() or 1))

	def _get_cached_height(self, item_id):
		try: return self.__class__._HEIGHT_CACHE.get(self._cache_key(item_id))
		except Exception: return None

	def _set_cached_height(self, item_id, n):
		try: self.__class__._HEIGHT_CACHE[self._cache_key(item_id)] = int(max(1, n))
		except Exception: pass

	def _invalidate_height_cache_for_id(self, item_id):
		try:
			keys = [k for k in self.__class__._HEIGHT_CACHE.keys() if k[0] == item_id]
			for k in keys: self.__class__._HEIGHT_CACHE.pop(k, None)
		except Exception: pass

	def _get_cached_text(self, item_id, files_list):
		key = item_id
		txt_new = "\n".join(files_list)
		old = self.__class__._TEXT_CACHE.get(key)
		if old != txt_new:
			self.__class__._TEXT_CACHE[key] = txt_new
			self._invalidate_height_cache_for_id(key)
		return self.__class__._TEXT_CACHE[key]

	def bind_mousewheel(self, widget):
		widget.bind("<MouseWheel>", self._global_wheel, add='+'); widget.bind("<Button-4>", self._global_wheel, add='+'); widget.bind("<Button-5>", self._global_wheel, add='+')

	def _fit_text(self, w):
		try:
			if not w or not w.winfo_exists(): return
			n = int(w.count("1.0", "end-1c", "displaylines")[0])
			self._set_cached_height(getattr(w, "_hist_id", None), n)
			w.config(height=max(1, min(n, self._MAX_TEXT_LINES)))
		except Exception: pass

	def _close(self):
		try: self.bind_class(self._mw_tag, "<MouseWheel>", None); self.bind_class(self._mw_tag, "<Button-4>", None); self.bind_class(self._mw_tag, "<Button-5>", None)
		except Exception: pass
		self.on_close_handler()

	def load_history(self):
		history_data = self.controller.settings_model.get(HISTORY_SELECTION_KEY, [])
		current_project = self.controller.project_model.current_project_name
		project_history = [item for item in history_data if item.get("project") == current_project]
		self.all_history_items = sorted(project_history, key=lambda x: x.get("timestamp", 0), reverse=True)
		self.current_page = 1; self.display_page()

	def display_page(self):
		for widget in self.content_frame.winfo_children(): widget.destroy()
		self.warning_labels.clear(); self._text_widgets = []
		page_size = self.items_per_page.get(); start_index = (self.current_page - 1) * page_size; end_index = start_index + page_size
		page_items = self.all_history_items[start_index:end_index]
		items_container = ttk.Frame(self.content_frame); items_container.pack(fill=tk.X)

		for s_obj in page_items:
			fr = ttk.LabelFrame(items_container, text=""); fr.pack(fill=tk.X, expand=True, pady=5, padx=5)
			proj = s_obj.get("project", "(Unknown)"); char_size = s_obj.get("char_size"); source_name = s_obj.get("source_name", "N/A"); files_list = s_obj.get("files", [])
			files_info = f" | Files: {len(files_list)}"; char_info = f" | Chars: {format_german_thousand_sep(char_size)}" if char_size is not None else ""; source_info = f" | Src: {source_name}"
			time_info = f"{datetime.fromtimestamp(s_obj['timestamp']).strftime('%d.%m.%Y %H:%M:%S')} ({get_relative_time_str(s_obj['timestamp'])})"
			lbl_txt = f"{proj}{source_info}{files_info}{char_info} | {time_info}"
			ttk.Label(fr, text=lbl_txt, style='Info.TLabel').pack(anchor='w', padx=5, pady=(0, 5))

			r_btn = ttk.Button(fr, text="Re-select", command=lambda data=s_obj: self.reselect_set(data)); r_btn.pack(fill=tk.X, pady=(0, 2), padx=5)
			warning_container = ttk.Frame(fr); warning_container.pack(fill=tk.X, padx=5); self.warning_labels[s_obj['id']] = warning_container

			if files_list:
				hist_id = s_obj.get('id')
				txt = create_enhanced_text_widget(fr, with_scrollbars=False, wrap='word', undo=False)
				txt.container.pack(fill=tk.X, pady=2, padx=5)
				txt.config(takefocus=0); txt.bind("<Key>", lambda e: "break")
				initial_h = max(1, min(len(files_list), self._MAX_TEXT_LINES))
				txt.config(height=initial_h)
				cached_h = self._get_cached_height(hist_id)
				if cached_h: txt.config(height=max(1, min(cached_h, self._MAX_TEXT_LINES)))
				content = self._get_cached_text(hist_id, files_list)
				txt.insert("end", content); txt.config(state='disabled')
				txt.container.bind("<Configure>", lambda e, w=txt: self._schedule_fit_text(w))
				txt._hist_id = hist_id
				self._text_widgets.append(txt)

		self._apply_wheel_tag(items_container)
		self.update_pagination_controls(); self.canvas.yview_moveto(0)
		self.after_idle(lambda: [self._schedule_fit_text(w) for w in self._text_widgets])

	def update_pagination_controls(self):
		page_size = self.items_per_page.get(); total_items = len(self.all_history_items)
		total_pages = (total_items + page_size - 1) // page_size or 1
		self.page_label.config(text=f"Page {self.current_page} of {total_pages}")
		self.first_btn.config(state=tk.NORMAL if self.current_page > 1 else tk.DISABLED)
		self.prev_btn.config(state=tk.NORMAL if self.current_page > 1 else tk.DISABLED)
		self.next_btn.config(state=tk.NORMAL if self.current_page < total_pages else tk.DISABLED)
		self.last_btn.config(state=tk.NORMAL if self.current_page < total_pages else tk.DISABLED)

	def change_page(self, action):
		page_size = self.items_per_page.get(); total_items = len(self.all_history_items)
		total_pages = (total_items + page_size - 1) // page_size or 1
		if action == 'first': self.current_page = 1
		elif action == 'prev' and self.current_page > 1: self.current_page -= 1
		elif action == 'next' and self.current_page < total_pages: self.current_page += 1
		elif action == 'last': self.current_page = total_pages
		self.display_page()

	def on_page_size_change(self, event=None): self.current_page = 1; self.display_page()
	
	def reselect_set(self, s_obj):
		history_id = s_obj['id']; warning_container = self.warning_labels.get(history_id)
		warning_is_visible = warning_container and len(warning_container.winfo_children()) > 0
		for h_id, container in self.warning_labels.items():
			if h_id != history_id:
				for widget in container.winfo_children(): widget.destroy()
		files_to_select = s_obj["files"]; all_project_files = {item['path'] for item in self.controller.project_model.all_items if item['type'] == 'file'}
		missing_files = [f for f in files_to_select if f not in all_project_files]; num_missing = len(missing_files)
		is_current_project = s_obj.get("project") == self.controller.project_model.current_project_name
		if num_missing > 0 and is_current_project and not warning_is_visible:
			plural = "s" if num_missing > 1 else ""; files_list = ", ".join(missing_files)
			text = f"{num_missing} file{plural} won't be selected because they no longer exist: {files_list}. Click again to proceed."
			warning_label = ttk.Label(warning_container, text=text, foreground="red", anchor="w", justify=tk.LEFT, wraplength=self.content_frame.winfo_width() - 20)
			warning_label.pack(pady=(0, 5)); return
		self.controller.reselect_history(s_obj["files"]); self.on_close_handler()
