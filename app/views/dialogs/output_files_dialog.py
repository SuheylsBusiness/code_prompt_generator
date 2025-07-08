# File: code_prompt_generator/app/views/dialogs/output_files_dialog.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import tkinter as tk
from tkinter import ttk, scrolledtext
import os, threading, queue
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
        self.create_widgets()
        self.on_close_with_save = apply_modal_geometry(self, parent, "OutputFilesDialog")
        self.load_files_async()
        self.process_dialog_queue()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # Widget Creation
    # ------------------------------
    def create_widgets(self):
        self.main_frame = ttk.Frame(self); self.main_frame.pack(fill=tk.BOTH, expand=True)
        self.main_frame.rowconfigure(1, weight=1); self.main_frame.columnconfigure(0, weight=1)
        self.create_search_widgets()
        pane = ttk.PanedWindow(self.main_frame, orient=tk.HORIZONTAL); pane.grid(row=1, column=0, sticky='nsew', padx=10, pady=(0,5))
        left_frame = ttk.Frame(pane); pane.add(left_frame, weight=3)
        cols = ("name", "time", "chars"); self.tree = ttk.Treeview(left_frame, columns=cols, show='headings', selectmode='browse')
        for col, text, width in [("name", "File Name", 250), ("time", "Generated", 120), ("chars", "Chars", 80)]:
            self.tree.heading(col, text=text); self.tree.column(col, width=width, stretch=(col == "name"), anchor='e' if col == "chars" else 'w')
        ysb = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.tree.yview); xsb = ttk.Scrollbar(left_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set); self.tree.grid(row=0, column=0, sticky='nsew')
        ysb.grid(row=0, column=1, sticky='ns'); xsb.grid(row=1, column=0, sticky='ew')
        left_frame.grid_rowconfigure(0, weight=1); left_frame.grid_columnconfigure(0, weight=1)
        right_frame = ttk.Frame(pane); pane.add(right_frame, weight=5)
        editor_buttons_frame = ttk.Frame(right_frame); editor_buttons_frame.pack(fill=tk.X, pady=(0, 5))
        self.save_button = ttk.Button(editor_buttons_frame, text='Save', command=self.save_current_file, state=tk.DISABLED); self.save_button.pack(side=tk.LEFT)
        ttk.Button(editor_buttons_frame, text='Copy', command=self.copy_text_to_clipboard).pack(side=tk.LEFT, padx=5)
        ttk.Button(editor_buttons_frame, text='Open in Notepad++', command=self.open_in_notepad).pack(side=tk.RIGHT, padx=5)
        self.editor_text = scrolledtext.ScrolledText(right_frame, wrap=tk.NONE, state='disabled', width=80, height=25); self.editor_text.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_file_select)
        self.create_pagination_controls()

    def create_search_widgets(self):
        search_frame = ttk.Frame(self.main_frame); search_frame.grid(row=0, column=0, sticky='ew', padx=10, pady=(10,5))
        ttk.Label(search_frame, text="Search Content:").pack(side=tk.LEFT, padx=(0, 5))
        self.search_var = tk.StringVar(); self.search_var.trace_add("write", self.on_search_term_changed)
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=40); self.search_entry.pack(side=tk.LEFT)
        self.search_cancel_btn = ttk.Button(search_frame, text="Cancel Search", command=self.cancel_search, state=tk.DISABLED)
        self.search_cancel_btn.pack(side=tk.LEFT, padx=5)
        self.progress_bar = ttk.Progressbar(search_frame, orient=tk.HORIZONTAL, mode='determinate', length=150)
        self.progress_bar.pack(side=tk.LEFT, padx=5)

    def create_pagination_controls(self):
        controls_frame = ttk.Frame(self.main_frame); controls_frame.grid(row=2, column=0, sticky='ew', padx=10, pady=5)
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
        for item in page_items: self.tree.insert("", tk.END, values=(item['name'], get_relative_time_str(item['mtime']), format_german_thousand_sep(item['chars'])), iid=item['path'])
        if self.tree.get_children(): self.tree.selection_set(self.tree.get_children()[0])
        self.update_pagination_controls()

    def update_pagination_controls(self):
        page_size = self.items_per_page.get(); total_items = len(self.filtered_files_meta)
        total_pages = (total_items + page_size - 1) // page_size or 1
        self.page_label.config(text=f"Page {self.current_page} of {total_pages}")
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
        if not term: self.filtered_files_meta = self.all_files_meta[:]; self.current_page = 1; self.display_page(); return
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

    def copy_text_to_clipboard(self): self.parent.update_clipboard(self.editor_text.get('1.0', tk.END).strip(), "Copied to clipboard"); self.on_close()
    def open_in_notepad(self):
        if not self.active_loading_filepath: return show_warning_centered(self, "Warning", "No file selected.")
        try:
            content_to_save = self.editor_text.get('1.0', 'end-1c')
            with open(self.active_loading_filepath, 'w', encoding='utf-8', newline='\n') as f:
                f.write(unify_line_endings(content_to_save))
            open_in_editor(self.active_loading_filepath)
        except Exception as e: show_error_centered(self, "Error", f"Failed to save and open file: {e}")
    def on_close(self): self.cancel_search(); self.on_close_with_save()

    # Internal Workers & Queue
    # ------------------------------
    def process_dialog_queue(self):
        try:
            while self.winfo_exists():
                task, data = self.dialog_queue.get_nowait()
                if task == 'files_loaded':
                    self.all_files_meta, self.filtered_files_meta = data, data[:]
                    self.display_page()
                elif task == 'search_progress': self.progress_bar['value'] = data
                elif task == 'search_done': self.filtered_files_meta = data; self.current_page = 1; self.display_page(); self.cancel_search()
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
        for f in os.listdir(OUTPUT_DIR):
            fp = os.path.join(OUTPUT_DIR, f)
            if os.path.isfile(fp):
                try:
                    files_meta.append({'name': f, 'mtime': os.path.getmtime(fp), 'chars': os.path.getsize(fp), 'path': fp})
                except OSError: continue
        files_meta.sort(key=lambda x: x['mtime'], reverse=True)
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

    def _search_worker(self, term, cancel_event):
        results = []; total = len(self.all_files_meta)
        for i, item in enumerate(self.all_files_meta):
            if cancel_event.is_set(): return
            try:
                content_chunk = ""
                with open(item['path'], 'r', encoding='utf-8', errors='ignore') as f:
                    content_chunk = f.read(1024 * 1024).lower() # Read first 1MB
                if term in item['name'].lower() or term in content_chunk:
                    results.append(item)
            except Exception: continue
            if self.winfo_exists(): self.dialog_queue.put(('search_progress', (i + 1) / total * 100))
        if not cancel_event.is_set() and self.winfo_exists(): self.dialog_queue.put(('search_done', results))