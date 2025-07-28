# File: code_prompt_generator/app/controllers/main_controller.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import os, time, threading, queue, hashlib, platform, subprocess, codecs, re, concurrent.futures, shutil
from tkinter import filedialog, TclError
import traceback
from app.config import get_logger, set_project_file_handler, CACHE_DIR, PROJECTS_DIR, INSTANCE_ID, PERIODIC_SAVE_INTERVAL_SECONDS, PROCESS_POOL_THRESHOLD_KB, FILE_WATCHER_INTERVAL_MS
from app.utils.ui_helpers import show_error_centered, show_warning_centered, show_yesno_centered, show_yesnocancel_centered, format_german_thousand_sep
from app.utils.system_utils import open_in_editor, unify_line_endings, open_in_vscode
from app.utils.escape_utils import safe_escape, safe_unescape
from datetime import datetime
from filelock import Timeout
try:
	from watchdog.observers import Observer
	from watchdog.events import FileSystemEventHandler
except ImportError:
	Observer = None
	FileSystemEventHandler = object

logger = get_logger(__name__)

# Top-level worker for ProcessPoolExecutor to enable pickling
# ------------------------------
def process_pool_worker(args):
	selected_files, template_content, clipboard_content, dir_tree, project_prefix, model_config = args
	from app.models.project_model import ProjectModel
	return ProjectModel.simulate_generation_static(selected_files, template_content, clipboard_content, dir_tree, project_prefix, model_config)

# Main Controller
# ------------------------------
class MainController:
	# Initialization & State
	# ------------------------------
	def __init__(self, project_model, settings_model):
		self.project_model = project_model
		self.settings_model = settings_model
		self.view = None
		self.queue = queue.Queue()
		self.char_count_token = 0
		self.precompute_request = threading.Event()
		self.precompute_thread = None
		self.precomputed_prompt_cache = {}
		self.precomputed_file_path = os.path.join(CACHE_DIR, f"cpg_precompute_{INSTANCE_ID}.tmp")
		self.precomputed_file_key = None
		self.precompute_file_lock = threading.Lock()
		self.is_precomputing = threading.Lock()
		self.precompute_args = (None, "", "")
		self.precompute_args_lock = threading.Lock()
		self._stop_event = threading.Event()
		self.periodic_save_thread = None
		self._config_observer = None
		self._config_poll_thread = None
		self.char_count_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
		self.background_task_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
		self.quick_action_semaphore = threading.BoundedSemaphore(4)
		self.generation_process_pool = concurrent.futures.ProcessPoolExecutor(max_workers=1)
		self.save_lock = threading.Lock()
		self.FENCED_CODE_SPLIT_RE = re.compile(r'(`{1,3}[^`]*`{1,3})')
		self.DELIMITER_RE = re.compile(r'^\s*---\s*$')
		self.initialize_state()

	def set_view(self, view):
		self.view = view
		self.load_initial_state()
		self.start_background_watchers()
		self.view.update_quick_action_buttons()

	def initialize_state(self):
		pass

	def load_initial_state(self):
		self._set_project_file_handler(None)
		self.update_projects_list()
		last_project = self.settings_model.get('last_selected_project')
		if last_project and self.project_model.exists(last_project):
			self.view.project_var.set(self.view.get_display_name_for_project(last_project))
			self.load_project(last_project)
		else:
			self.view.clear_project_view()
		self.view.restore_window_geometry()
		self.process_queue()

	def start_background_watchers(self):
		self.start_config_watcher()
		self.start_precompute_worker()
		self.start_periodic_save_worker()
		self.project_model.start_file_watcher(self.queue)

	def stop_threads(self):
		logger.info("Issuing shutdown command to all controller threads.")
		self._stop_event.set()
		self.precompute_request.set()

		if hasattr(self, '_config_handler') and hasattr(self._config_handler, 'cancel_timer'):
			self._config_handler.cancel_timer()
		if self._config_observer and Observer:
			try: self._config_observer.stop()
			except Exception: pass

		if self.char_count_executor:
			self.char_count_executor.shutdown(wait=False, cancel_futures=True)
		if self.background_task_pool:
			self.background_task_pool.shutdown(wait=False, cancel_futures=True)
		if self.generation_process_pool:
			self.generation_process_pool.shutdown(wait=False, cancel_futures=True)

	# Application Lifecycle & Context
	# ------------------------------
	def on_closing(self):
		logger.info("Application closing. Performing final state capture and save.")
		
		# 1. Save state and data first, while the UI still exists.
		try:
			if self.view and self.view.winfo_exists():
				self.settings_model.set('window_geometry', self.view.geometry())
				self._save_current_project_state()
				
				with self.save_lock:
					projects_saved = self.project_model.save()
					settings_saved = self.settings_model.save()
				if not settings_saved or not projects_saved:
					logger.warning("Final save failed during shutdown. A file might be locked.")
		except Exception as e:
			logger.error(f"Could not capture state or save data on close: {e}")

		# 2. Initiate non-blocking shutdown of all background threads.
		self.project_model.stop_threads()
		self.stop_threads()

		# 3. Clean up temp file.
		if hasattr(self, 'precomputed_file_path') and self.precomputed_file_path and os.path.exists(self.precomputed_file_path):
			try: os.remove(self.precomputed_file_path)
			except OSError: pass
		
		# 4. Destroy the UI, which allows mainloop to exit.
		if self.view and self.view.winfo_exists():
			self.view.destroy()

	def start_config_watcher(self):
		if not Observer or (self._config_observer and self._config_observer.is_alive()):
			if not Observer: self._start_config_polling()
			return
		if not os.path.isdir(CACHE_DIR) and not os.path.isdir(PROJECTS_DIR): return

		class _ConfigChangeHandler(FileSystemEventHandler):
			def __init__(self, queue, settings_model, project_model):
				self.queue = queue; self.settings_model = settings_model; self.project_model = project_model
				self._reload_timer = None; self._reload_lock = threading.Lock()

			def cancel_timer(self):
				with self._reload_lock:
					if self._reload_timer: self._reload_timer.cancel()

			def _debounce_reload_projects(self):
				with self._reload_lock:
					self.cancel_timer()
					self._reload_timer = threading.Timer(0.5, lambda: self.queue.put(("reload_projects", None)))
					self._reload_timer.daemon = True # avoid exit hang
					self._reload_timer.start()

			def on_modified(self, event):
				if event.is_directory: return
				if event.src_path == self.settings_model.settings_file:
					if self.settings_model.check_for_external_changes(check_content=True): self.queue.put(("reload_settings", None))
				elif event.src_path.endswith('project.json'):
					if self.project_model.check_project_for_external_changes(event.src_path):
						self.queue.put(("reload_projects", None))

			def on_created(self, event):
				if event.is_directory or event.src_path.endswith('project.json'): self._debounce_reload_projects()

			def on_deleted(self, event):
				if event.is_directory or event.src_path.endswith('project.json'): self._debounce_reload_projects()

			def on_moved(self, event):
				if event.is_directory or event.dest_path.endswith('project.json'): self._debounce_reload_projects()

		self._config_handler = _ConfigChangeHandler(self.queue, self.settings_model, self.project_model)
		self._config_observer = Observer()
		if os.path.isdir(CACHE_DIR): self._config_observer.schedule(self._config_handler, CACHE_DIR, recursive=False)
		if os.path.isdir(PROJECTS_DIR): self._config_observer.schedule(self._config_handler, PROJECTS_DIR, recursive=True)
		
		self._config_observer.daemon = True
		self._config_observer.start()
		logger.info("Configuration and project directory watcher started via watchdog.")

		if not Observer:
			self._start_config_polling()

	def _start_config_polling(self):
		if self._config_poll_thread and self._config_poll_thread.is_alive(): return
		def _poll():
			project_folders = set(os.listdir(PROJECTS_DIR)) if os.path.isdir(PROJECTS_DIR) else set()
			project_mtimes = {}

			def get_project_mtimes():
				mtimes = {}
				if os.path.isdir(PROJECTS_DIR):
					for folder in os.listdir(PROJECTS_DIR):
						proj_file = os.path.join(PROJECTS_DIR, folder, 'project.json')
						if os.path.isfile(proj_file):
							try: mtimes[proj_file] = os.path.getmtime(proj_file)
							except OSError: pass
				return mtimes

			project_mtimes = get_project_mtimes()

			interval = max(3, FILE_WATCHER_INTERVAL_MS // 1000)
			while not self._stop_event.wait(interval):
				try:
					if self.settings_model.check_for_external_changes(check_content=True):
						self.queue.put(("reload_settings", None))
					
					if os.path.isdir(PROJECTS_DIR):
						current_folders = set(os.listdir(PROJECTS_DIR))
						current_mtimes = get_project_mtimes()
						if current_folders != project_folders or current_mtimes != project_mtimes:
							project_folders = current_folders
							project_mtimes = current_mtimes
							self.queue.put(("reload_projects", None))
				except Exception as e: logger.exception("Config polling failed: %s", e)

		self._config_poll_thread = threading.Thread(target=_poll, daemon=True)
		self._config_poll_thread.start()
		logger.info("Configuration file polling started (watchdog unavailable).")

	# Project & Template Management
	# ------------------------------
	def open_project_folder_vscode(self):
		proj_name = self.project_model.current_project_name
		if not proj_name: return show_warning_centered(self.view, "No Project Selected", "Please select a project first.")
		proj_path = self.project_model.get_project_path(proj_name)
		if proj_path and os.path.isdir(proj_path):
			if not open_in_vscode(proj_path):
				show_warning_centered(self.view, "VS Code Not Found", "Could not open in VS Code. Ensure the 'code' command is in your PATH.")
		else:
			show_error_centered(self.view, "Error", "Project path is invalid or does not exist.")

	def add_project(self):
		dp = filedialog.askdirectory(title="Select Project Directory")
		if not dp: return
		name = os.path.basename(dp)
		if not name.strip(): return show_warning_centered(self.view, "Invalid Name", "Project name cannot be empty.")
		if self.project_model.exists(name): return show_error_centered(self.view, "Error", f"Project '{name}' already exists.")
		self.project_model.add_project(name, dp)
		self.update_projects_list()
		self.view.project_var.set(self.view.get_display_name_for_project(name))
		self.load_project(name, is_new_project=True)

	def remove_project(self):
		disp = self.view.project_var.get()
		name = self.view.project_display_name_map.get(disp)
		if not name: return show_warning_centered(self.view, "No Project Selected", "Please select a project to remove.")
		if not self.project_model.exists(name): return show_warning_centered(self.view, "Invalid Selection", "Project not found.")
		
		warning_message = f"Are you sure you want to remove '{name}'?\n\nThis will permanently delete the project's configuration folder and all its backups from the disk. This action cannot be undone."
		if show_yesno_centered(self.view, "Permanently Remove Project?", warning_message):
			self.project_model.remove_project(name)
			if self.settings_model.get('last_selected_project') == name:
				self.settings_model.delete('last_selected_project')
				self.settings_model.save()
			
			if self.project_model.current_project_name == name: self.project_model.set_current_project(None)

			self.update_projects_list()
			all_projs = self.view.project_dropdown['values']
			if all_projs:
				new_proj_disp = all_projs[0]
				new_proj_name = self.view.project_display_name_map.get(new_proj_disp)
				self.view.project_var.set(new_proj_disp)
				if new_proj_name: self.load_project(new_proj_name)
			else:
				self.view.project_var.set("")
				self.view.clear_project_view()

	def open_project_folder(self):
		proj_name = self.project_model.current_project_name
		if not proj_name: return show_warning_centered(self.view, "No Project Selected", "Please select a project first.")
		proj_path = self.project_model.get_project_path(proj_name)
		if proj_path and os.path.isdir(proj_path): open_in_editor(proj_path)
		else: show_error_centered(self.view, "Error", "Project path is invalid or does not exist.")

	def load_project(self, name, is_new_project=False):
		current_project = self.project_model.current_project_name
		if current_project and self.project_model.exists(current_project):
			self._save_current_project_state()
			self.project_model.save(project_name=current_project)
		
		self.view.clear_ui_for_loading()
		self.view.show_loading_placeholder()
		
		self.project_model.set_current_project(name)
		self.project_model.update_project_usage()
		self.project_model.start_file_watcher(self.queue)
		with self.precompute_file_lock: self.precomputed_prompt_cache.clear()
		self.precomputed_file_key = None
		
		last_files = [] if is_new_project else self.project_model.get_project_data(name, "last_files", [])
		self.project_model.set_selection(last_files)

		self.settings_model.set('last_selected_project', name)
		
		self._set_project_file_handler(name)
		self.run_autoblacklist_in_background(name)
		self.load_templates(force_refresh=True)
		self.load_items_in_background(is_new_project=is_new_project)

	def load_templates(self, force_refresh=False):
		self.view.update_template_dropdowns(force_refresh)
		self.view.update_default_template_button()
		self.on_template_selected()

	def update_projects_list(self):
		projects = self.project_model.get_sorted_projects_for_display()
		self.view.update_project_list(projects)

	def update_project_settings(self, proj_name, proj_data):
		if self.view and self.view.winfo_exists():
			self.project_model.set_project_ui_state(proj_name, self.view.get_ui_state())
		self.project_model.update_project(proj_name, proj_data)
		self.project_model.save(project_name=proj_name)

	def update_global_settings(self, settings_data):
		self.settings_model.set('respect_gitignore', settings_data['respect_gitignore'])
		self.settings_model.set('reset_scroll_on_reset', settings_data['reset_scroll_on_reset'])
		self.settings_model.set("global_blacklist", settings_data['global_blacklist'])
		self.settings_model.set("global_keep", settings_data['global_keep'])
		self.settings_model.save()

	def handle_raw_template_update(self, new_data):
		self.settings_model.set("global_templates", new_data)
		self.settings_model.save()
		with self.precompute_file_lock: self.precomputed_prompt_cache.clear()
		self.load_templates(force_refresh=True)
		if self.view:
			self.view.quick_copy_var.set("")

	# File & Item Management
	# ------------------------------
	def refresh_files(self, is_manual=False):
		if not self.project_model.current_project_name: return
		
		if self.view and self.view.winfo_exists():
			self.project_model.set_project_ui_state(self.project_model.current_project_name, self.view.get_ui_state())
		self.project_model.directory_tree_cache = None
		self.view.item_size_cache.clear()
		scroll_pos = self.view.get_scroll_position()
		self.project_model.set_project_scroll_pos(self.project_model.current_project_name, scroll_pos)
		self.project_model.project_tree_scroll_pos = scroll_pos

		self.load_items_in_background(is_silent=not is_manual)

	# Selection & State Tracking
	# ------------------------------
	def toggle_select_all(self):
		self.view.flush_search_debounce()
		self.view.toggle_select_all_tree_items()

	def reset_selection(self):
		to_uncheck = self.project_model.get_selected_files()
		search_was_active = self.view.file_search_var.get() != ""
		if not to_uncheck and not search_was_active: return

		self.view.reset_button_clicked = True

		self.project_model.set_selection(set())
		self.view.sync_treeview_selection_to_model()
		self.handle_file_selection_change()

		if search_was_active:
			self.view.file_search_var.set("")
		else:
			if self.settings_model.get('reset_scroll_on_reset', True):
				self.view.scroll_tree_to(0.0)
			self.view.reset_button_clicked = False

	def reselect_history(self, files_to_select):
		self.reset_selection()
		all_project_files = {item['path'] for item in self.project_model.all_items if item['type'] == 'file'}
		valid_files = [f for f in files_to_select if f in all_project_files]
		skipped_count = len(files_to_select) - len(valid_files)

		if not valid_files:
			return

		self.project_model.set_selection(set(valid_files))
		self.view.sync_treeview_selection_to_model()
		self.handle_file_selection_change()

		if skipped_count > 0:
			self.view.set_status_temporary(f"Reselected {len(valid_files)} files. Skipped {skipped_count} unavailable files.", 4000)

	def reselect_files_from_output(self, files_to_select):
		self.reset_selection()
		all_project_files = {item['path'] for item in self.project_model.all_items if item['type'] == 'file'}
		valid_files = [f for f in files_to_select if f in all_project_files]
		skipped_count = len(files_to_select) - len(valid_files)

		if not valid_files:
			return

		self.project_model.set_selection(set(valid_files))
		self.view.sync_treeview_selection_to_model()
		self.handle_file_selection_change()
		
		status_msg = f"Reselected {len(valid_files)} files."
		if skipped_count > 0:
			status_msg += f" Skipped {skipped_count} unavailable files."
		self.view.set_status_temporary(status_msg, 4000)


	# Generation & Output Logic
	# ------------------------------
	def generate_output(self, template_override=None): self._initiate_generation(template_override, to_clipboard=False)
	def generate_output_to_clipboard(self, template_override=None): self._initiate_generation(template_override, to_clipboard=True)

	def _initiate_generation(self, template_override, to_clipboard):
		proj_name = self.project_model.current_project_name
		if not proj_name: return show_warning_centered(self.view, "No Project Selected", "Please select a project first.")
		
		self._save_current_project_state()
		self.project_model.save(project_name=proj_name)
		template_name = template_override if template_override is not None else self.view.template_var.get()
		template_content = self.settings_model.get_template_content(template_name)
		selected_files = self.project_model.get_selected_files()
		
		if not selected_files and "{{CLIPBOARD}}" not in template_content: return show_warning_centered(self.view, "Warning", "No files selected.")
		if len(selected_files) > self.project_model.max_files: return show_warning_centered(self.view, "Warning", f"Selected {len(selected_files)} files. Max is {self.project_model.max_files}.")
		if not self.project_model.is_project_path_valid(): return show_error_centered(self.view, "Error", "Project directory does not exist.")
		
		try: clipboard_content = self.view.clipboard_get()
		except Exception: clipboard_content = ""

		key = self.get_precompute_key(selected_files, template_name, clipboard_content)

		with self.precompute_file_lock:
			if not to_clipboard and self.precomputed_file_key == key and os.path.exists(self.precomputed_file_path):
				cached_data = self.precomputed_prompt_cache.get(key)
				if cached_data:
					_, total_chars, oversized, truncated = cached_data
					self.finalize_precomputed_generation(self.precomputed_file_path, selected_files, total_chars, oversized, truncated, template_name)
					return

			if key in self.precomputed_prompt_cache:
				prompt, total_chars, oversized, truncated = self.precomputed_prompt_cache[key]
				if to_clipboard:
					self.finalize_clipboard_generation(prompt, selected_files, total_chars, oversized, truncated, template_name)
				else:
					self.finalize_generation(prompt, selected_files, total_chars, oversized, truncated, template_name)
				return

		self.view.set_generation_state(True, to_clipboard)
		self.project_model.set_last_used_files(proj_name, selected_files)
		if template_override is None: self.project_model.set_last_used_template(template_name)
		
		total_size = sum(self.project_model.file_char_counts.get(f, 0) for f in selected_files)
		use_process_pool = total_size > (PROCESS_POOL_THRESHOLD_KB * 1024)

		if use_process_pool:
			self.background_task_pool.submit(self.generate_output_worker_process, selected_files, template_name, clipboard_content, to_clipboard)
		else:
			worker = self.generate_output_to_clipboard_worker if to_clipboard else self.generate_output_worker
			self.background_task_pool.submit(worker, selected_files, template_name, clipboard_content)

	def get_precompute_key(self, selected_files, template_name, clipboard_content=""):
		h = hashlib.md5()
		proj_name = self.project_model.current_project_name
		if proj_name:
			h.update(proj_name.encode())
			proj_path = self.project_model.get_project_path(proj_name)
			if proj_path: h.update(proj_path.encode())
		for fp in sorted(selected_files):
			h.update(fp.encode())
			full_path = os.path.join(self.project_model.get_project_path(proj_name), fp)
			try: mtime = os.stat(full_path).st_mtime_ns
			except OSError: mtime = 0
			h.update(str(mtime).encode())
		template_content = self.settings_model.get_template_content(template_name)
		if "{{CLIPBOARD}}" in template_content:
			h.update(clipboard_content.encode())
		h.update(template_name.encode())
		h.update(template_content.encode())
		return h.hexdigest()

	def save_and_open_notepadpp(self, content):
		ts = datetime.now().strftime("%d.%m.%Y_%H.%M.%S")
		proj_name = self.project_model.current_project_name or "temp"
		safe_proj_name = ''.join(c for c in proj_name if c.isalnum() or c in ' _').rstrip() or "temp"
		filename = f"{safe_proj_name}_text_{ts}.txt"
		filepath = os.path.join(self.project_model.output_dir, filename)
		try:
			with open(filepath, 'w', encoding='utf-8') as f: f.write(unify_line_endings(content).rstrip('\n'))
			open_in_editor(filepath)
			self.view.set_status_temporary("Opened in editor")
		except Exception as e: logger.error("Failed to open in editor: %s", e, exc_info=True); show_error_centered(self.view, "Error", "Failed to open in editor.")

	def save_and_open_from_precomputed(self, precomputed_path, selection, source_name):
		ts = datetime.now().strftime("%d.%m.%Y_%H.%M.%S")
		proj_name = self.project_model.current_project_name or "temp"
		safe_proj_name = ''.join(c for c in proj_name if c.isalnum() or c in ' _').rstrip() or "temp"
		filename = f"{safe_proj_name}_text_{ts}.txt"
		filepath = os.path.join(self.project_model.output_dir, filename)
		try:
			shutil.move(precomputed_path, filepath)
			self.precomputed_file_key = None
			self.project_model._update_outputs_metadata(os.path.basename(filepath), {"source_name": source_name, "selection": selection, "is_quick_action": False, "project_name": proj_name})
			open_in_editor(filepath)
			self.view.set_status_temporary("Opened in editor")
		except Exception as e:
			logger.error(f"Failed to move precomputed file: {e}. Falling back.")
			try:
				with open(precomputed_path if os.path.exists(precomputed_path) else filepath, 'r', encoding='utf-8') as f: content = f.read()
				with open(filepath, 'w', encoding='utf-8') as f: f.write(unify_line_endings(content).rstrip('\n'))
				self.project_model._update_outputs_metadata(os.path.basename(filepath), {"source_name": source_name, "selection": selection, "is_quick_action": False, "project_name": proj_name})
				open_in_editor(filepath)
				self.view.set_status_temporary("Opened in editor")
			except Exception as fallback_e:
				logger.error(f"Fallback for precomputed file failed: {fallback_e}", exc_info=True)
				show_error_centered(self.view, "Error", "Failed to open in editor.")

	# Background Processing & Threading
	# ------------------------------
	def load_items_in_background(self, is_new_project=False, is_silent=False):
		if self.project_model.is_loading(): return
		self.view.set_status_loading()
		self.view.is_silent_refresh = is_silent
		if is_new_project: self.project_model.project_tree_scroll_pos = 0.0
		self.project_model.load_items_async(is_new_project, self.queue)

	def run_autoblacklist_in_background(self, proj_name):
		if self.project_model.is_autoblacklisting(): return
		self.project_model.run_autoblacklist_async(proj_name, self.queue)

	def start_precompute_worker(self):
		self.precompute_thread = threading.Thread(target=self._precompute_worker, daemon=True)
		self.precompute_thread.start()

	def start_periodic_save_worker(self):
		self.periodic_save_thread = threading.Thread(target=self._periodic_save_worker, daemon=True)
		self.periodic_save_thread.start()

	def _periodic_save_worker(self):
		while not self._stop_event.wait(PERIODIC_SAVE_INTERVAL_SECONDS):
			try:
				with self.save_lock:
					if self._stop_event.is_set(): break
					if self.project_model.have_projects_changed():
						logger.info("Periodic save for project data")
						self.project_model.save()
					if self.settings_model.have_settings_changed():
						logger.info("Periodic save for settings.json")
						self.settings_model.save()
			except Timeout:
				msg = "Periodic save failed: could not get a file lock. Your changes may not be saved. Please try saving manually or restarting the app."
				logger.error(msg)
				if not self._stop_event.is_set(): self.queue.put(('show_generic_error', ("Periodic Save Failed", msg)))
			except Exception as e:
				if not self._stop_event.is_set(): logger.error(f"Error during periodic save: {e}", exc_info=False)

	def _precompute_worker(self):
		while not self._stop_event.is_set():
			self.precompute_request.wait(timeout=1.0)
			if self._stop_event.is_set(): break
			if not self.precompute_request.is_set(): continue

			with self.is_precomputing:
				self.precompute_request.clear()
				if not self.project_model.current_project_name: continue
				
				with self.precompute_args_lock:
					selected_files, template_name, clipboard_content = self.precompute_args
				
				if template_name is None: continue

				self.project_model.update_file_contents(selected_files)
				prompt, total_chars, oversized, truncated = self.project_model.simulate_final_prompt(selected_files, template_name, clipboard_content)
				key = self.get_precompute_key(selected_files, template_name, clipboard_content)

				with self.precompute_file_lock:
					if len(self.precomputed_prompt_cache) > 20: self.precomputed_prompt_cache.clear()
					self.precomputed_prompt_cache[key] = (prompt, total_chars, oversized, truncated)
					try:
						with open(self.precomputed_file_path, 'w', encoding='utf-8') as f: f.write(unify_line_endings(prompt).rstrip('\n'))
						self.precomputed_file_key = key
					except Exception as e:
						logger.error(f"Failed to write precompute file: {e}")
						self.precomputed_file_key = None

	def char_count_worker(self, selected_files, template_name, clipboard_content, request_token):
		try:
			if self.char_count_token != request_token: return
			if not self.project_model.current_project_name: return
			self.project_model.update_file_contents(selected_files)
			if self.char_count_token != request_token: return
			prompt, _, _, _ = self.project_model.simulate_final_prompt(selected_files, template_name, clipboard_content)
			prompt_chars = len(prompt)
			if self.char_count_token == request_token: self.queue.put(('char_count_done', (len(selected_files), prompt_chars)))
		except Exception as e:
			logger.error("Character count worker failed: %s", e, exc_info=True)
			if self.char_count_token == request_token: self.queue.put(('char_count_done', (len(selected_files), -1)))

	def generate_output_worker(self, selected_files, template_name, clipboard_content):
		try:
			self.project_model.update_file_contents(selected_files)
			prompt, total_chars, oversized, truncated = self.project_model.simulate_final_prompt(selected_files, template_name, clipboard_content)
			self.queue.put(('save_and_open', (prompt, selected_files, total_chars, oversized, truncated, template_name)))
		except Exception as e:
			logger.error("Error generating output: %s", e, exc_info=True)
			self.queue.put(('error', "Error generating output."))

	def generate_output_to_clipboard_worker(self, selected_files, template_name, clipboard_content):
		try:
			self.project_model.update_file_contents(selected_files)
			prompt, total_chars, oversized, truncated = self.project_model.simulate_final_prompt(selected_files, template_name, clipboard_content)
			self.queue.put(('copy_and_save_silently', (prompt, selected_files, total_chars, oversized, truncated, template_name)))
		except Exception as e:
			logger.error("Error generating for clipboard: %s", e, exc_info=True)
			self.queue.put(('error', "Error generating for clipboard."))

	def generate_output_worker_process(self, selected_files, template_name, clipboard_content, to_clipboard):
		try:
			self.project_model.update_file_contents(selected_files) # Ensure contents are fresh before passing
			dir_tree = self.project_model.generate_directory_tree_custom()
			template_content = self.settings_model.get_template_content(template_name)
			project_prefix = self.project_model.get_project_data(self.project_model.current_project_name, "prefix", "")
			model_config = self.project_model.get_config_for_simulation()
			
			args = (selected_files, template_content, clipboard_content, dir_tree, project_prefix, model_config)
			future = self.generation_process_pool.submit(process_pool_worker, args)
			prompt, total_chars, oversized, truncated = future.result(timeout=60)

			if to_clipboard:
				self.queue.put(('copy_and_save_silently', (prompt, selected_files, total_chars, oversized, truncated, template_name)))
			else:
				self.queue.put(('save_and_open', (prompt, selected_files, total_chars, oversized, truncated, template_name)))
		except Exception as e:
			logger.error("Error in process pool generation: %s", e, exc_info=True)
			self.queue.put(('error', "Error in process pool generation."))

	def _quick_action_worker(self, val, clip_in):
		project_name = self.project_model.current_project_name or "ClipboardAction"
		selected_files = self.project_model.get_selected_files()
		op_map = {
			"Truncate Between '---'": self.process_truncate_format,
			"Replace \"**\"": lambda t: (self._extended_text_cleaning(t), "Cleaned text and copied"),
			"Gemini Whitespace Fix": lambda t: (t.replace('\u00A0', ' '), "Fixed whitespace and copied"),
			"Remove Duplicates": lambda t: ('\n'.join(dict.fromkeys(t.rstrip('\n').split('\n'))), "Removed duplicates and copied"),
			"Sort Alphabetically": lambda t: ('\n'.join(sorted(t.rstrip('\n').split('\n'))), "Sorted alphabetically and copied"),
			"Sort by Length": lambda t: ('\n'.join(sorted(t.rstrip('\n').split('\n'), key=len)), "Sorted by length and copied"),
			"Escape Text": lambda t: (safe_escape(t.rstrip('\n')), "Escaped text and copied"),
			"Unescape Text": lambda t: (safe_unescape(t.rstrip('\n')), "Unescaped text and copied")
		}
		try:
			if val in op_map:
				new_clip, msg = op_map[val](clip_in)
				new_clip = new_clip.strip()
				self.project_model.save_output_silently(new_clip, project_name, selected_files, val, is_quick_action=True)
				self.queue.put(('quick_action_done', (new_clip, msg)))
			elif self.settings_model.is_template(val) and "{{CLIPBOARD}}" in self.settings_model.get_template_content(val):
				content = self.settings_model.get_template_content(val).replace("{{CLIPBOARD}}", clip_in).strip()
				self.project_model.save_output_silently(content, project_name, selected_files, val, is_quick_action=True)
				self.queue.put(('quick_action_done', (content, "Copied to clipboard")))
		except Exception as e:
			logger.error("Quick action '%s' failed: %s", val, e)
			self.queue.put(('set_status_temporary', ("Operation failed!", 3000)))

	# Event Handlers
	# ------------------------------
	def on_project_selected(self, _=None):
		if getattr(self.view.project_dropdown, '_programmatic_update', False):
			return
		# When a selection is made from the dropdown, the text in the entry is now final.
		# Simply load the project. The user can type over the text to start a new search.
		disp = self.view.project_var.get()
		if not disp or disp not in self.view.all_project_values:
			# If the text is not a valid project, do nothing.
			self.view.project_dropdown['values'] = self.view.all_project_values
			return

		name = self.view.project_display_name_map.get(disp)
		if name and name != self.project_model.current_project_name:
			self.load_project(name)

	def on_template_selected(self, _=None):
		if self.project_model.current_project_name:
			self.project_model.set_last_used_template(self.view.template_var.get())
		self.request_precomputation()

	def update_file_selection(self, selected_paths_set):
		self.project_model.update_selection_from_set(selected_paths_set)

	def handle_file_selection_change(self, *a):
		selected_files = self.project_model.get_selected_files()
		
		try: clipboard_content = self.view.clipboard_get()
		except Exception: clipboard_content = ""
		template_name = self.view.template_var.get()
		key = self.get_precompute_key(selected_files, template_name, clipboard_content)
		
		with self.precompute_file_lock:
			if key in self.precomputed_prompt_cache:
				prompt, _, _, _ = self.precomputed_prompt_cache[key]
				self.view.update_selection_count_label(len(selected_files), format_german_thousand_sep(len(prompt)))
			else:
				self.view.update_selection_count_label(len(selected_files), "Calculating...")
				self.char_count_token += 1
				self.char_count_executor.submit(self.char_count_worker, selected_files, template_name, clipboard_content, self.char_count_token)
		
		self.view.refresh_selected_files_list(selected_files)
		self.view.update_select_all_button()
		self.request_precomputation()

	def on_no_project_selected(self):
		show_warning_centered(self.view, "No Project Selected", "Please select a project first.")

	def on_quick_copy_selected(self, _=None):
		val = self.view.quick_copy_var.get()
		self.view.quick_copy_dropdown.set("")
		if not val or val.startswith("-- "): return
		
		mapped_val = self.view.quick_action_name_map.get(val, val)

		self.settings_model.record_quick_action_usage(mapped_val)
		self.settings_model.save()
		self._execute_quick_action(mapped_val)
		self.view.update_quick_action_buttons()

	def _execute_quick_action(self, val):
		if not val or val.startswith("-- "): return
		try: clip_in = self.view.clipboard_get()
		except Exception: clip_in = ""
		if self.quick_action_semaphore.acquire(blocking=False):
			future = self.background_task_pool.submit(self._quick_action_worker, val, clip_in)
			future.add_done_callback(lambda f: self.quick_action_semaphore.release())
		else:
			self.queue.put(('set_status_temporary', ('Busy – please wait', 1500)))

	def get_most_frequent_action(self):
		history = self.settings_model.get('quick_action_history', {})
		if not history: return None
		return max(history, key=lambda k: history[k].get('count', 0))

	def get_most_recent_action(self):
		history = self.settings_model.get('quick_action_history', {})
		if not history: return None
		return max(history, key=lambda k: history[k].get('timestamp', 0))

	def execute_most_frequent_quick_action(self):
		action_name = self.get_most_frequent_action()
		if not action_name: return show_warning_centered(self.view, "No Data", "No quick action frequency data available.")
		self.settings_model.record_quick_action_usage(action_name)
		self.settings_model.save()
		self._execute_quick_action(action_name)
		self.view.update_quick_action_buttons()

	def execute_most_recent_quick_action(self):
		action_name = self.get_most_recent_action()
		if not action_name: return show_warning_centered(self.view, "No Data", "No recent quick action data available.")
		self.settings_model.record_quick_action_usage(action_name)
		self.settings_model.save()
		self._execute_quick_action(action_name)
		self.view.update_quick_action_buttons()

	def add_to_blacklist(self, folder_path):
		proj_name = self.project_model.current_project_name
		if not proj_name: return
		if self.view and self.view.winfo_exists():
			self.project_model.set_project_ui_state(proj_name, self.view.get_ui_state())
		# The path from the treeview includes a trailing slash for directories
		clean_path = folder_path.rstrip('/')
		self.project_model.add_to_blacklist(proj_name, [clean_path])
		self.refresh_files(is_manual=True)

	def on_context_menu_action(self, action, path):
		if action == "add_to_blacklist":
			self.add_to_blacklist(path)
			return

		proj_path = self.project_model.get_project_path(self.project_model.current_project_name)
		if not proj_path: return
		full_path = os.path.join(proj_path, path)
		if not os.path.exists(full_path) and action not in ["select_folder", "unselect_folder"]:
			return
		
		if action == "select_folder": self.view.select_folder_items(path, select=True)
		elif action == "unselect_folder": self.view.select_folder_items(path, select=False)
		elif action == "copy_path": self.view.update_clipboard(path, "Path copied to clipboard")
		elif action == "open_file": open_in_editor(full_path)
		elif action == "open_folder_explorer": open_in_editor(full_path)
		elif action == "open_folder_vscode":
			if not open_in_vscode(full_path):
				show_warning_centered(self.view, "VS Code Not Found", "Could not open in VS Code. Ensure the 'code' command is in your system's PATH.")

	# Queue Processing & UI Updates
	# ------------------------------
	def process_queue(self):
		try:
			while True:
				task, data = self.queue.get_nowait()
				if task == 'save_and_open': self.finalize_generation(*data)
				elif task == 'copy_and_save_silently': self.finalize_clipboard_generation(*data)
				elif task == 'silent_refresh': self.refresh_files(is_manual=False)
				elif task == 'error':
					self.view.set_generation_state(False)
					show_error_centered(self.view, "Error", data)
				elif task == 'load_items_done':
					status, result, is_new_project = data
					self.view.item_size_cache.clear()
					if status == "error":
						show_error_centered(self, "Invalid Path", "Project directory does not exist.")
						self.project_model.all_items = []
						self.project_model.filtered_items = []
					else:
						found_items, limit_exceeded = result
						existing_files = {item['path'] for item in found_items if item['type'] == 'file'}
						current_selection = self.project_model.get_selected_files_set()
						removed_files = current_selection - existing_files

						if removed_files:
							self.project_model.set_selection(current_selection - removed_files)
							logger.info(f"Silently unselected {len(removed_files)} files that no longer exist: {sorted(list(removed_files))}")
							if not self.view.is_silent_refresh:
								self.view.set_status_temporary(f"Project files updated; {len(removed_files)} missing file(s) unselected.")

						self.project_model.set_items(found_items)
						self.project_model.set_filtered_items(found_items)
						self.project_model._initialize_file_data(found_items)
						threading.Thread(target=self.project_model._load_all_file_contents_and_sizes_worker, args=(self.queue,), daemon=True).start()

						proj_name = self.project_model.current_project_name
						scroll_pos = 0.0
						if proj_name and not is_new_project:
							ui_state = self.project_model.get_project_ui_state(proj_name)
							scroll_pos = self.project_model.get_project_data(proj_name, "scroll_pos", 0.0)
							if ui_state and hasattr(self.view, 'apply_ui_state'):
								self.view.apply_ui_state(ui_state)
						
						self.view.load_items_result((limit_exceeded,), is_new_project)

						if proj_name:
							if hasattr(self.view, 'sync_treeview_selection_to_model'):
								self.view.sync_treeview_selection_to_model()
							self.view.scroll_tree_to(scroll_pos)
							self.handle_file_selection_change()

					self.view.status_label.config(text="Ready")
				elif task == 'auto_bl': self.on_auto_blacklist_done(data[0], data[1])
				elif task == 'char_count_done':
					file_count, prompt_chars = data
					self.view.update_selection_count_label(
						file_count,
						format_german_thousand_sep(prompt_chars) if prompt_chars >= 0 else "Error"
					)
				elif task == 'file_contents_loaded':
					proj_name = data
					if proj_name == self.project_model.current_project_name:
						self.view.update_file_char_counts()
						self.view.refresh_selected_files_list(self.project_model.get_selected_files())
						self.request_precomputation()
				elif task == 'set_status_temporary': self.view.set_status_temporary(data[0], data[1])
				elif task == 'show_generic_error': show_error_centered(self.view, data[0], data[1])
				elif task == 'quick_action_done':
					new_clip, msg = data
					self.view.update_clipboard(new_clip)
					self.view.set_status_temporary(msg)
				elif task == 'reload_projects':
					self.handle_external_project_change()
				elif task == 'reload_settings':
					logger.info("External change in settings.json, reloading.")
					try:
						self.settings_model.load()
					except IOError as e:
						logger.critical(f"A background reload of settings.json failed fatally. The app may be in an inconsistent state. Please restart. Error: {e}")
						continue
					self.load_templates(force_refresh=True)
					self.view.update_quick_action_buttons()
		except queue.Empty: pass
		if self.view and self.view.winfo_exists(): self.view.after(50, self.process_queue)

	def finalize_generation(self, output, selection, char_count, oversized, truncated, source_name):
		self.project_model.update_project_usage()
		self.project_model.save_and_open_output(output, selection, source_name, is_quick_action=False)
		self.view.set_generation_state(False)
		self.settings_model.add_history_selection(selection, self.project_model.current_project_name, char_count, source_name, is_quick_action=False)
		self._check_and_warn_for_omissions(oversized, truncated)

	def finalize_precomputed_generation(self, precomputed_path, selection, char_count, oversized, truncated, source_name):
		self.project_model.update_project_usage()
		self.save_and_open_from_precomputed(precomputed_path, selection, source_name)
		self.view.set_generation_state(False)
		self.settings_model.add_history_selection(selection, self.project_model.current_project_name, char_count, source_name, is_quick_action=False)
		self._check_and_warn_for_omissions(oversized, truncated)

	def finalize_clipboard_generation(self, output, selection, char_count, oversized, truncated, source_name):
		self.view.update_clipboard(output)
		self.view.set_status_temporary("Copied to clipboard.")
		self.project_model.save_output_silently(output, self.project_model.current_project_name, selection, source_name, is_quick_action=False)
		self.view.set_generation_state(False)
		self.settings_model.add_history_selection(selection, self.project_model.current_project_name, char_count, source_name, is_quick_action=False)
		self._check_and_warn_for_omissions(oversized, truncated)

	def on_auto_blacklist_done(self, proj_name, dirs):
		self.project_model.add_to_blacklist(proj_name, dirs)
		if self.project_model.current_project_name == proj_name:
			show_warning_centered(self.view, "Auto-Blacklisted", f"Directories with >50 files were blacklisted and added to project settings:\n\n{', '.join(dirs)}")

	# Internal Helpers
	# ------------------------------
	def _set_project_file_handler(self, project_name): set_project_file_handler(project_name)

	def _save_current_project_state(self):
		if not self.view or not self.view.winfo_exists(): return
		proj_name = self.project_model.current_project_name
		if not proj_name or not self.project_model.exists(proj_name): return
		try:
			selected_paths = self.project_model.get_selected_files_set()
			self.project_model.set_last_used_files(proj_name, list(selected_paths))
			scroll_pos = self.view.get_scroll_position()
			self.project_model.set_project_scroll_pos(proj_name, scroll_pos)
			ui_state = self.view.get_ui_state()
			self.project_model.set_project_ui_state(proj_name, ui_state)
		except (AttributeError, TclError) as e:
			logger.warning(f"Could not capture project state for '{proj_name}': {e}")
	def request_precomputation(self):
		if not self.view or not self.view.winfo_exists(): return
		template_name = self.view.template_var.get()
		try:
			clipboard_content = self.view.clipboard_get()
		except Exception:
			clipboard_content = ""
		
		selected_files = self.project_model.get_selected_files()
		precompute_context = (selected_files, template_name, clipboard_content)

		with self.precompute_args_lock:
			self.precompute_args = precompute_context
		self.precompute_request.set()

	def _extended_text_cleaning(self, text):
		lines = text.split('\n')
		output_lines, in_fenced_code = [], False
		for line in lines:
			s = line.rstrip('\r')
			if s.startswith('> '): s = s[2:]
			elif s.strip() == '>': s = ''
			if s.startswith('```'):
				in_fenced_code = not in_fenced_code; output_lines.append(s); continue
			if in_fenced_code or s.startswith(' '):
				output_lines.append(s); continue
			parts = self.FENCED_CODE_SPLIT_RE.split(s)
			processed_line = "".join([part if i % 2 == 1 else part.replace('**', '') for i, part in enumerate(parts)])
			output_lines.append(processed_line)
		return '\n'.join(output_lines)

	def process_truncate_format(self, text):
		text = unify_line_endings(text)
		text = self._extended_text_cleaning(text)
		lines = text.split('\n')
		delim_idx = []
		in_fenced_code = False
		for i, line in enumerate(lines):
			if line.strip().startswith('```'): in_fenced_code = not in_fenced_code
			if not in_fenced_code and self.DELIMITER_RE.match(line): delim_idx.append(i)

		between = False
		if len(delim_idx) >= 2:
			between = True
			lines = lines[delim_idx[0] + 1:delim_idx[-1]]
		while lines and not lines[0].strip(): lines.pop(0)
		while lines and not lines[-1].strip(): lines.pop()
		final_text = '\n'.join(lines)
		char_cnt = len(final_text)
		notification = f"✅ Copied {char_cnt} chars (between delimiters)" if between else f"ℹ️ {'Only one' if len(delim_idx) == 1 else 'No'} '---' found – copied whole document ({char_cnt} chars)."
		return final_text, notification

	def _check_and_warn_for_omissions(self, oversized, truncated):
		warnings = []
		if oversized:
			warnings.append(f"The following files were SKIPPED as they exceed the max file size ({self.project_model.max_file_size/1000:g} kB):\n- " + "\n- ".join(oversized))
		if truncated:
			warnings.append(f"The following files were TRUNCATED as the prompt exceeds the max content size ({self.project_model.max_content_size/1000000:g} MB):\n- " + "\n- ".join(truncated))
		if warnings:
			show_warning_centered(self.view, "Prompt Content Omissions", "\n\n".join(warnings))

	def handle_external_project_change(self):
		logger.info("External change in projects directory detected, reloading.")
		current_project = self.project_model.current_project_name
		self.project_model.load()
		self.update_projects_list()

		if current_project and not self.project_model.exists(current_project):
			logger.warning(f"Active project '{current_project}' was removed externally. Unloading.")
			all_projs = self.view.project_dropdown['values']
			if all_projs:
				new_proj_disp = all_projs[0]
				new_proj_name = self.view.project_display_name_map.get(new_proj_disp)
				self.view.project_var.set(new_proj_disp)
				if new_proj_name: self.load_project(new_proj_name)
			else:
				self.view.project_var.set("")
				self.view.clear_project_view()
		elif current_project:
			self.view.project_var.set(self.view.get_display_name_for_project(current_project))