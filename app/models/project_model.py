# File: code_prompt_generator/app/models/project_model.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import shutil
import os, time, threading, copy, tkinter as tk, concurrent.futures, itertools, json, hashlib, re
import traceback
try:
	from watchdog.observers import Observer
	from watchdog.events import FileSystemEventHandler
except ImportError:
	Observer = None
	FileSystemEventHandler = object
from app.config import get_logger, PROJECTS_DIR, OUTPUT_DIR, MAX_FILES, MAX_CONTENT_SIZE, MAX_FILE_SIZE, FILE_WATCHER_INTERVAL_MS, LAST_OWN_WRITE_TIMES, LAST_OWN_WRITE_TIMES_LOCK
from app.utils.file_io import load_json_safely, atomic_write_with_backup, safe_read_file
from app.utils.path_utils import parse_gitignore, path_should_be_ignored
from app.utils.system_utils import open_in_editor, unify_line_endings
from app.utils.migration_utils import get_safe_project_foldername
from datetime import datetime
from filelock import Timeout, FileLock

logger = get_logger(__name__)

# Project Model
# ------------------------------
class ProjectModel:
	# Initialization & State
	# ------------------------------
	def __init__(self, settings_model):
		self.settings_model = settings_model
		self.projects_dir = PROJECTS_DIR
		self.output_dir = OUTPUT_DIR
		self.outputs_metadata_file = os.path.join(self.output_dir, '_metadata.json')
		self.outputs_metadata_lock_file = self.outputs_metadata_file + '.lock'
		self.max_files, self.max_content_size, self.max_file_size = MAX_FILES, MAX_CONTENT_SIZE, MAX_FILE_SIZE
		self.projects = {} # { project_name: { data ... } }
		self.project_name_to_path = {} # { project_name: "path/to/project.json" }
		self.projects_lock = threading.RLock()
		self.baseline_projects = {}
		self.current_project_name = None
		self.all_items, self.filtered_items = [], []
		self.selected_paths, self.selected_paths_lock = set(), threading.Lock()
		self.file_mtimes, self.file_contents, self.file_char_counts = {}, {}, {}
		self.project_tree_scroll_pos = 0.0
		self.directory_tree_cache = None
		self._loading_thread, self._autoblacklist_thread, self._poll_thread = None, None, None
		self._observer, self._bulk_update_active = None, False
		self._items_lock, self._file_content_lock = threading.Lock(), threading.Lock()
		self._file_watcher_queue = None
		self._stop_event = threading.Event()
		self.MAX_IO_WORKERS = min(8, (os.cpu_count() or 1))
		self._thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.MAX_IO_WORKERS)
		self.FILE_TOO_LARGE_SENTINEL = "<FILE TOO LARGE – SKIPPED>"
		self.project_file_mtimes = {}
		self.load()

	def is_loaded(self): return self.projects is not None
	def is_loading(self): return self._loading_thread and self._loading_thread.is_alive()
	def is_autoblacklisting(self): return self._autoblacklist_thread and self._autoblacklist_thread.is_alive()
	def is_bulk_updating(self): return self._bulk_update_active

	def start_file_watcher(self, queue=None):
		self._file_watcher_queue = queue
		proj_path = self.get_project_path(self.current_project_name)
		if not proj_path or not os.path.isdir(proj_path): return
		
		if Observer:
			self._start_watchdog_watcher(proj_path)
		else:
			self._start_polling_watcher(proj_path)

	def _start_watchdog_watcher(self, proj_path):
		if self._observer and self._observer.is_alive(): return
		model = self
		class _Handler(FileSystemEventHandler):
			def __init__(self):
				self._debounce_timer = None
				self._debounce_lock = threading.Lock()

			def _debounce_refresh(self):
				with self._debounce_lock:
					if self._debounce_timer: self._debounce_timer.cancel()
					self._debounce_timer = threading.Timer(1.0, self._do_refresh)
					self._debounce_timer.daemon = True # avoid exit hang
					self._debounce_timer.start()

			def _do_refresh(self):
				if model._file_watcher_queue: model._file_watcher_queue.put(('silent_refresh', None))

			def on_any_event(self, event):
				if model.current_project_name is None: return

				current_bl = model.get_project_data(model.current_project_name, "blacklist", [])
				global_bl = model.settings_model.get("global_blacklist", [])
				blacklist_patterns = current_bl + global_bl

				try:
					rel_path = os.path.relpath(event.src_path, proj_path).replace("\\", "/")
					if any(p in rel_path for p in blacklist_patterns): return
				except ValueError: return

				if event.is_directory or event.event_type in ('created', 'deleted', 'moved'):
					self._debounce_refresh()
				elif event.event_type == 'modified' and model._file_watcher_queue:
					if model.update_file_contents([rel_path]):
						model._file_watcher_queue.put(('file_contents_loaded', model.current_project_name))
		
		self._observer = Observer()
		self._observer.schedule(_Handler(), proj_path, recursive=True)
		self._observer.daemon = True
		self._observer.start()
		logger.info("Project file watcher started via watchdog.")

	def _start_polling_watcher(self, proj_path):
		logger.warning("Watchdog not installed. Falling back to polling for project file changes.")
		if self._poll_thread and self._poll_thread.is_alive(): return
		
		def _poll_worker():
			last_scan_files = set()
			try: last_scan_files = {p for p in os.listdir(proj_path)}
			except OSError: pass
			interval = max(5, FILE_WATCHER_INTERVAL_MS // 1000)
			
			while not self._stop_event.wait(interval):
				if not self.current_project_name or self.get_project_path(self.current_project_name) != proj_path: break
				try:
					current_files = {p for p in os.listdir(proj_path)}
					if current_files != last_scan_files:
						logger.info("Polling detected change in project directory.")
						if self._file_watcher_queue: self._file_watcher_queue.put(('silent_refresh', None))
						last_scan_files = current_files
				except OSError as e:
					logger.error(f"Polling watcher failed for {proj_path}: {e}")
					break # Stop polling if directory is gone
		
		self._poll_thread = threading.Thread(target=_poll_worker, daemon=True)
		self._poll_thread.start()

	def stop_threads(self):
		logger.info("Stopping model background threads.")
		self._stop_event.set()
		if self._observer and Observer:
			try:
				self._observer.stop()
				self._observer.join(timeout=0.2)
			except Exception: pass
		self._observer = None
		if self._poll_thread and self._poll_thread.is_alive():
			self._poll_thread.join(timeout=0.2)
		self._poll_thread = None
		if self._thread_pool:
			self.stop_threads_and_pools()

	def stop_threads_and_pools(self):
		self._stop_event.set()
		if self._observer and Observer and self._observer.is_alive():
			try: self._observer.stop(); self._observer.join(timeout=0.2)
			except Exception: pass
		self._observer = None
		if self._thread_pool: self._thread_pool.shutdown(wait=False, cancel_futures=True)


	# Data Persistence
	# ------------------------------
	def load(self):
		"""Loads all projects from the PROJECTS_DIR."""
		with self.projects_lock:
			self.projects.clear()
			self.project_name_to_path.clear()
			self.project_file_mtimes.clear()
			if not os.path.isdir(self.projects_dir): return
			for folder_name in os.listdir(self.projects_dir):
				project_folder = os.path.join(self.projects_dir, folder_name)
				project_file = os.path.join(project_folder, 'project.json')
				project_lock = os.path.join(project_folder, 'project.json.lock')
				if os.path.isfile(project_file):
					data = load_json_safely(project_file, project_lock, is_fatal=False)
					if data and 'name' in data and 'path' in data:
						project_name = data['name']
						self.projects[project_name] = data
						self.project_name_to_path[project_name] = project_file
						try:
							self.project_file_mtimes[project_file] = os.path.getmtime(project_file)
						except OSError:
							self.project_file_mtimes[project_file] = 0
					else:
						logger.warning(f"Skipping invalid or corrupt project file: {project_file}")
			self.baseline_projects = copy.deepcopy(self.projects)

	def save(self, project_name=None):
		"""Saves one or all projects to their individual files."""
		with self.projects_lock:
			projects_to_save = [project_name] if project_name and project_name in self.projects else self.projects.keys()
			for name in projects_to_save:
				if self.projects.get(name) == self.baseline_projects.get(name):
					continue
				project_data = self.projects.get(name)
				project_path = self.project_name_to_path.get(name)
				if not project_data or not project_path: continue
				lock_path = project_path + ".lock"
				if atomic_write_with_backup(project_data, project_path, lock_path, file_key=project_path):
					self.baseline_projects[name] = copy.deepcopy(project_data)
		return True

	def reload_project(self, project_name):
		"""Reloads a single project's data from its file."""
		with self.projects_lock:
			if project_name not in self.project_name_to_path:
				logger.warning(f"Attempted to reload non-existent project: {project_name}")
				return False

			project_file = self.project_name_to_path[project_name]
			project_lock = project_file + ".lock"
			logger.info(f"Externally triggered reload for {project_name}")
			
			data = load_json_safely(project_file, project_lock)
			if data and data.get('name') == project_name:
				self.projects[project_name] = data
				self.baseline_projects[project_name] = copy.deepcopy(data)
				try:
					self.project_file_mtimes[project_file] = os.path.getmtime(project_file)
				except OSError:
					self.project_file_mtimes[project_file] = 0
				return True
		return False

	def check_project_for_external_changes(self, file_path):
		if not os.path.exists(file_path): return True
		try:
			current_mtime = os.path.getmtime(file_path)
		except OSError:
			return True

		with LAST_OWN_WRITE_TIMES_LOCK:
			last_own_write = LAST_OWN_WRITE_TIMES.get(file_path, 0)

		if abs(current_mtime - last_own_write) < 0.1:
			return False
		
		last_known_mtime = self.project_file_mtimes.get(file_path, 0)
		if current_mtime > last_known_mtime:
			self.project_file_mtimes[file_path] = current_mtime
			return True
			
		return False

	def have_projects_changed(self):
		with self.projects_lock: return self.projects != self.baseline_projects

	# Project Management
	# ------------------------------
	def exists(self, name):
		with self.projects_lock: return name in self.projects
	
	def add_project(self, name, path):
		with self.projects_lock:
			folder_name = get_safe_project_foldername(name)
			project_folder_path = os.path.join(self.projects_dir, folder_name)
			project_file_path = os.path.join(project_folder_path, 'project.json')
			os.makedirs(project_folder_path, exist_ok=True)
			
			new_project_data = {
				"name": name, "path": path, "last_files": [], "last_template": "", "scroll_pos": 0.0,
				"blacklist": [], "keep": [], "prefix": "", "click_counts": {},
				"last_usage": time.time(), "usage_count": 1, "ui_state": {}
			}
			self.projects[name] = new_project_data
			self.project_name_to_path[name] = project_file_path
		self.save(project_name=name)

	def remove_project(self, name):
		with self.projects_lock:
			if name in self.projects:
				project_path = self.project_name_to_path.pop(name, None)
				del self.projects[name]
				
				if project_path:
					project_folder = os.path.dirname(project_path)
					try: shutil.rmtree(project_folder)
					except OSError as e: logger.error(f"Failed to delete project folder {project_folder}: {e}")

	def get_project_path(self, name):
		with self.projects_lock: return self.projects.get(name, {}).get("path")
	
	def get_project_data(self, name, key=None, default=None):
		with self.projects_lock:
			if key: return self.projects.get(name, {}).get(key, default)
			return copy.deepcopy(self.projects.get(name, {}))
	def is_project_path_valid(self): return self.current_project_name and os.path.isdir(self.get_project_path(self.current_project_name))
	def set_current_project(self, name):
		with self.projects_lock, self.selected_paths_lock, self._items_lock, self._file_content_lock:
			if self.current_project_name != name:
				self.stop_threads_and_pools()
				self._stop_event.clear()
				self._thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.MAX_IO_WORKERS)
				self.file_contents.clear(); self.file_mtimes.clear(); self.file_char_counts.clear()
				self.directory_tree_cache = None
				self.all_items.clear(); self.filtered_items.clear()
			self.current_project_name = name
			if name and name in self.projects: self.project_tree_scroll_pos = self.projects[name].get("scroll_pos", 0.0)
			else: self.project_tree_scroll_pos = 0.0
	def set_project_scroll_pos(self, name, pos):
		with self.projects_lock:
			if name in self.projects and self.projects[name].get('scroll_pos') != pos: self.projects[name]['scroll_pos'] = pos
	def get_project_ui_state(self, name):
		with self.projects_lock: return self.projects.get(name, {}).get("ui_state", {})
	def set_project_ui_state(self, name, state):
		with self.projects_lock:
			if name in self.projects and self.projects[name].get('ui_state') != state: self.projects[name]['ui_state'] = state
	def update_project_usage(self):
		with self.projects_lock:
			if self.current_project_name and self.current_project_name in self.projects:
				proj = self.projects[self.current_project_name]
				proj["last_usage"] = time.time()
				proj["usage_count"] = proj.get("usage_count", 0) + 1
		self.save(project_name=self.current_project_name)
	def update_project(self, name, data):
		with self.projects_lock:
			if name in self.projects: self.projects[name].update(data)

	def get_sorted_projects_for_display(self):
		with self.projects_lock:
			return sorted([(k, p.get("last_usage", 0), p.get("usage_count", 0)) for k, p in self.projects.items()], key=lambda x: (-x[1], -x[2], x[0].lower()))

	def load_items_async(self, is_new_project, queue):
		self.directory_tree_cache = None
		self._loading_thread = threading.Thread(target=self._load_items_worker, args=(is_new_project, queue), daemon=True)
		self._loading_thread.start()

	def _load_items_worker(self, is_new_project, queue):
		if not self.current_project_name: return
		with self.projects_lock: proj = self.projects[self.current_project_name]; proj_path = proj["path"]
		if not os.path.isdir(proj_path): return queue.put(('load_items_done', ("error", None, is_new_project)))
		
		respect_git = self.settings_model.get('respect_gitignore', True)
		git_patterns = parse_gitignore(os.path.join(proj_path, '.gitignore')) if respect_git and os.path.isfile(os.path.join(proj_path, '.gitignore')) else []
		with self.projects_lock: proj_bl = proj.get("blacklist", []); proj_kp = proj.get("keep", [])
		glob_bl = self.settings_model.get("global_blacklist", []); glob_kp = self.settings_model.get("global_keep", [])
		comb_bl_lower = [b.strip().lower().replace("\\", "/") for b in list(set(proj_bl + glob_bl))]
		comb_kp_lower = [p.strip().lower().replace("\\", "/") for p in list(set(proj_kp + glob_kp))]

		found_items, file_count, limit_exceeded = [], 0, False
		
		q = [(proj_path, "")] # Use a queue for iterative scanning
		processed_dirs = set()
		while q:
			if file_count >= self.max_files: limit_exceeded = True; break
			current_path, rel_prefix = q.pop(0)
			if current_path in processed_dirs: continue
			processed_dirs.add(current_path)

			try: entries = sorted(os.scandir(current_path), key=lambda e: e.name)
			except OSError: continue

			for entry in entries:
				if file_count >= self.max_files: limit_exceeded = True; break
				try:
					entry_rel_path = os.path.relpath(entry.path, proj_path).replace("\\", "/")
				except ValueError: continue
				
				is_dir = entry.is_dir(follow_symlinks=False)
				path_to_check = f"{entry_rel_path}/" if is_dir else entry_rel_path

				if path_should_be_ignored(path_to_check, respect_git, git_patterns, comb_kp_lower, comb_bl_lower):
					continue
				
				if is_dir:
					found_items.append({"type": "dir", "path": path_to_check, "level": path_to_check.count('/') -1})
					q.append((entry.path, entry_rel_path))
				else: # is_file
					found_items.append({"type": "file", "path": entry_rel_path, "level": entry_rel_path.count('/')})
					file_count += 1
		
		queue.put(('load_items_done', ("ok", (found_items, limit_exceeded), is_new_project)))

	def _initialize_file_data(self, items):
		if not self.current_project_name: return
		with self._file_content_lock:
			self.file_char_counts.clear(); self.file_contents.clear(); self.file_mtimes.clear()
			files_to_load = [item["path"] for item in items if item["type"] == "file"]
			for rp in files_to_load:
				self.file_char_counts[rp] = 0
				self.file_contents[rp] = None # Placeholder

	def _load_all_file_contents_and_sizes_worker(self, queue):
		proj_path = self.get_project_path(self.current_project_name)
		if not proj_path: return
		with self._items_lock: all_files = [item["path"] for item in self.all_items if item["type"] == "file"]
		if not all_files:
			if queue: queue.put(('file_contents_loaded', self.current_project_name))
			return

		def load_size_and_mtime(relative_path):
			full_path = os.path.join(proj_path, relative_path)
			try:
				st = os.stat(full_path)
				content = safe_read_file(full_path) # Always read for accurate char count
				char_count = len(content) if content is not None else 0
				return (relative_path, char_count, st.st_mtime_ns)
			except (FileNotFoundError, OSError): return (relative_path, 0, 0)
		
		try:
			results = list(self._thread_pool.map(load_size_and_mtime, all_files))
		except RuntimeError:
			logger.warning("Thread pool is shut down; cannot load file contents.")
			return
		with self._file_content_lock:
			for rp, size, mtime in results:
				self.file_char_counts[rp] = size
				self.file_mtimes[rp] = mtime
		if queue: queue.put(('file_contents_loaded', self.current_project_name))

	def set_items(self, items):
		with self._items_lock: self.all_items = items; self.filtered_items = items
	def set_filtered_items(self, items):
		with self._items_lock: self.filtered_items = items
	def get_filtered_items(self):
		with self._items_lock: return self.filtered_items

	def get_files_in_folder(self, folder_path):
		with self._items_lock:
			return [item['path'] for item in self.all_items if item['type'] == 'file' and item['path'].startswith(folder_path)]

	def update_file_contents(self, selected_files):
		if self._stop_event.is_set(): return False
		proj_path = self.get_project_path(self.current_project_name)
		if not proj_path or not selected_files: return False

		dirty = []
		files_to_check_mtime = []
		with self._file_content_lock:
			mtimes_copy = self.file_mtimes.copy()
			for rp in selected_files:
				if self.file_contents.get(rp) is None:
					dirty.append(rp)
				else:
					files_to_check_mtime.append(rp)

		for rp in files_to_check_mtime:
			full_path = os.path.join(proj_path, rp)
			if not os.path.isfile(full_path):
				if rp in mtimes_copy: dirty.append(rp)
				continue
			try:
				current_mtime = os.stat(full_path).st_mtime_ns
				if mtimes_copy.get(rp) != current_mtime:
					dirty.append(rp)
			except OSError:
				if rp in mtimes_copy: dirty.append(rp)

		dirty = list(dict.fromkeys(dirty)) # Deduplicate
		if not dirty: return False
		self.directory_tree_cache = None

		def load_single(relative_path):
			full_path = os.path.join(proj_path, relative_path)
			try:
				st = os.stat(full_path)
				content = safe_read_file(full_path) if st.st_size <= self.max_file_size else self.FILE_TOO_LARGE_SENTINEL
				if content not in [None, self.FILE_TOO_LARGE_SENTINEL]: content = unify_line_endings(content)
				char_count = len(content) if content is not None and content != self.FILE_TOO_LARGE_SENTINEL else st.st_size
				return (relative_path, content, st.st_mtime_ns, char_count)
			except FileNotFoundError: return (relative_path, None, None, 0)
			except OSError: return (relative_path, None, 0, 0)

		if self._stop_event.is_set(): return False
		try:
			results = list(self._thread_pool.map(load_single, dirty))
		except RuntimeError:
			logger.warning("Thread pool is shut down; cannot update file contents.")
			return False

		with self._file_content_lock:
			for rp, content, mtime, char_count in results:
				if mtime is None:
					self.file_contents.pop(rp, None); self.file_char_counts.pop(rp, None); self.file_mtimes.pop(rp, None)
				else:
					self.file_contents[rp] = content; self.file_char_counts[rp] = char_count; self.file_mtimes[rp] = mtime
		return True

	def set_selection(self, selection_set):
		with self.selected_paths_lock:
			self.selected_paths = set(selection_set)

	def update_selection_from_set(self, new_set):
		with self.selected_paths_lock:
			self.selected_paths = new_set

	def get_selected_files(self):
		with self.selected_paths_lock:
			return sorted(list(self.selected_paths))

	def get_selected_files_set(self):
		with self.selected_paths_lock:
			return self.selected_paths.copy()

	def set_last_used_files(self, project_name, selection):
		with self.projects_lock:
			if project_name and project_name in self.projects: self.projects[project_name]['last_files'] = selection
	def set_last_used_template(self, template_name):
		with self.projects_lock:
			if self.current_project_name and self.current_project_name in self.projects: self.projects[self.current_project_name]['last_template'] = template_name
	def increment_click_count(self, file_path):
		with self.projects_lock:
			if self.current_project_name and self.current_project_name in self.projects:
				proj = self.projects[self.current_project_name]
				counts = proj.get("click_counts", {})
				counts[file_path] = min(counts.get(file_path, 0) + 1, 100)
				proj['click_counts'] = counts

	def run_autoblacklist_async(self, proj_name, queue):
		self._autoblacklist_thread = threading.Thread(target=self._auto_blacklist_worker, args=(proj_name, queue), daemon=True)
		self._autoblacklist_thread.start()

	def _auto_blacklist_worker(self, proj_name, queue):
		new_additions = self._check_and_auto_blacklist(proj_name)
		if new_additions: queue.put(('auto_bl', (proj_name, new_additions)))

	def _check_and_auto_blacklist(self, proj_name, threshold=50):
		proj_path = self.get_project_path(proj_name)
		if not os.path.isdir(proj_path): return []
		with self.projects_lock: proj = self.projects[proj_name]
		current_bl = proj.get("blacklist", []) + self.settings_model.get("global_blacklist", [])
		keep_patterns = proj.get("keep", []) + self.settings_model.get("global_keep", [])
		keep_patterns_lower = [p.lower() for p in keep_patterns]
		git_patterns = parse_gitignore(os.path.join(proj_path, '.gitignore')) if self.settings_model.get('respect_gitignore', True) else []
		new_blacklisted = []
		for root, dirs, files in os.walk(proj_path):
			rel_root = os.path.relpath(root, proj_path).replace("\\", "/").strip("/")
			if any(bl.lower() in rel_root.lower() for bl in current_bl if rel_root): continue
			unignored_files = [f for f in files if not path_should_be_ignored(f"{rel_root}/{f}".strip("/"), self.settings_model.get('respect_gitignore',True), git_patterns, keep_patterns_lower, current_bl)]
			if len(unignored_files) > threshold and rel_root and rel_root.lower() not in [b.lower() for b in current_bl]: new_blacklisted.append(rel_root)
		return new_blacklisted

	def add_to_blacklist(self, proj_name, dirs):
		with self.projects_lock:
			if proj_name in self.projects:
				proj = self.projects[proj_name]
				proj["blacklist"] = list(dict.fromkeys(proj.get("blacklist", []) + dirs))
		self.save(project_name=proj_name)

	@staticmethod
	def _replace_placeholder_line(text, placeholder, replacement):
		pat = re.compile(r'^[ \t]*' + re.escape(placeholder) + r'[ \t]*(?:\r?\n|$)', re.MULTILINE)
		def sub(m): s = m.group(0); return (replacement.rstrip('\n') + ('\n' if replacement and s.endswith('\n') else '')) if replacement else ''
		new, n = pat.subn(sub, text, count=1)
		return new if n > 0 else (text.replace(placeholder, replacement, 1) if placeholder in text else text)

	def simulate_final_prompt(self, selection, template_name, clipboard_content="", dir_tree=None):
		prompt, total_selection_chars, oversized, truncated = self.simulate_generation(selection, template_name, clipboard_content, dir_tree)
		return prompt.rstrip('\n') + '\n', total_selection_chars, oversized, truncated

	def simulate_generation(self, selection, template_name, clipboard_content, dir_tree=None):
		with self.projects_lock:
			if not self.current_project_name or self.current_project_name not in self.projects: return "", 0, [], []
			proj = self.projects[self.current_project_name]
			prefix = proj.get("prefix", "").strip()
		s1 = f"### {prefix} File Structure" if prefix else "### File Structure"
		s2 = f"### {prefix} Code Files provided" if prefix else "### Code Files provided"
		s3 = f"### {prefix} Code Files" if prefix else "### Code Files"
		
		if dir_tree is None: dir_tree = self.generate_directory_tree_custom()
		
		template_content = self.settings_model.get_template_content(template_name)

		placeholders = ["{{dirs}}", "{{files_provided}}", "{{file_contents}}", "{{CLIPBOARD}}"]
		placeholder_positions = {p: template_content.find(p) for p in placeholders}
		found_placeholders = {p: pos for p, pos in placeholder_positions.items() if pos != -1}

		prompt = template_content
		if "{{CLIPBOARD}}" in found_placeholders: prompt = self._replace_placeholder_line(prompt, "{{CLIPBOARD}}", clipboard_content)

		content_blocks, oversized_files, truncated_files = [], [], []
		total_content_size, total_selection_chars = 0, 0
		
		with self._file_content_lock:
			for i, rp in enumerate(selection):
				content = self.file_contents.get(rp)
				if content == self.FILE_TOO_LARGE_SENTINEL:
					oversized_files.append(rp)
					total_selection_chars += self.file_char_counts.get(rp, 0)
					continue
				if content is None: continue
				if total_content_size + len(content) > self.max_content_size and content:
					truncated_files.extend(selection[i:])
					break
				content_blocks.append(f"--- {rp} ---\n{content}\n--- {rp} ---\n")
				total_content_size += len(content)
				total_selection_chars += len(content)

		dirs_replacement = ""
		if "{{dirs}}" in found_placeholders:
			dirs_content = f"{s1}\n\n{dir_tree.strip()}" if dir_tree else ""
			if dirs_content: dirs_replacement = dirs_content
			prompt = self._replace_placeholder_line(prompt, "{{dirs}}", dirs_replacement)

		files_list_replacement = ""
		if "{{files_provided}}" in found_placeholders:
			if selection:
				lines = "".join(f"- {x}\n" for x in selection)
				files_list_content = f"{s2}\n{lines}".rstrip()
				files_list_replacement = files_list_content
			prompt = self._replace_placeholder_line(prompt, "{{files_provided}}", files_list_replacement)

		content_replacement = ""
		if "{{file_contents}}" in found_placeholders:
			if content_blocks:
				content_block_text = ''.join(content_blocks)
				content_replacement_content = f"{s3}\n\n{content_block_text}".rstrip()
				content_replacement = content_replacement_content
			prompt = self._replace_placeholder_line(prompt, "{{file_contents}}", content_replacement)

		return prompt, total_selection_chars, oversized_files, truncated_files

	@staticmethod
	def simulate_generation_static(selection, template_content, clipboard_content, dir_tree, project_prefix, model_config):
		prefix = project_prefix.strip()
		s1 = f"### {prefix} File Structure" if prefix else "### File Structure"
		s2 = f"### {prefix} Code Files provided" if prefix else "### Code Files provided"
		s3 = f"### {prefix} Code Files" if prefix else "### Code Files"

		placeholders = ["{{dirs}}", "{{files_provided}}", "{{file_contents}}", "{{CLIPBOARD}}"]
		placeholder_positions = {p: template_content.find(p) for p in placeholders}
		found_placeholders = {p: pos for p, pos in placeholder_positions.items() if pos != -1}

		prompt = template_content
		if "{{CLIPBOARD}}" in found_placeholders: prompt = ProjectModel._replace_placeholder_line(prompt, "{{CLIPBOARD}}", clipboard_content)

		content_blocks, oversized_files, truncated_files = [], [], []
		total_content_size, total_selection_chars = 0, 0
		
		file_contents = model_config["file_contents"]
		file_char_counts = model_config["file_char_counts"]

		for i, rp in enumerate(selection):
			content = file_contents.get(rp)
			if content == model_config["FILE_TOO_LARGE_SENTINEL"]:
				oversized_files.append(rp)
				total_selection_chars += file_char_counts.get(rp, 0)
				continue
			if content is None: continue
			if total_content_size + len(content) > model_config["max_content_size"]:
				truncated_files.extend(selection[i:])
				break
			content_blocks.append(f"--- {rp} ---\n{content}\n--- {rp} ---\n")
			total_content_size += len(content)
			total_selection_chars += len(content)

		dirs_replacement = ""
		if "{{dirs}}" in found_placeholders:
			dirs_content = f"{s1}\n\n{dir_tree.strip()}" if dir_tree else ""
			if dirs_content: dirs_replacement = dirs_content
			prompt = ProjectModel._replace_placeholder_line(prompt, "{{dirs}}", dirs_replacement)

		files_list_replacement = ""
		if "{{files_provided}}" in found_placeholders:
			if selection:
				lines = "".join(f"- {x}\n" for x in selection)
				files_list_content = f"{s2}\n{lines}".rstrip()
				files_list_replacement = files_list_content
			prompt = ProjectModel._replace_placeholder_line(prompt, "{{files_provided}}", files_list_replacement)

		content_replacement = ""
		if "{{file_contents}}" in found_placeholders:
			if content_blocks:
				content_block_text = ''.join(content_blocks)
				content_replacement_content = f"{s3}\n\n{content_block_text}".rstrip()
				content_replacement = content_replacement_content
			prompt = ProjectModel._replace_placeholder_line(prompt, "{{file_contents}}", content_replacement)

		final_prompt = prompt
		return final_prompt.rstrip('\n') + '\n', total_selection_chars, oversized_files, truncated_files
		
	def get_config_for_simulation(self):
		with self._file_content_lock:
			return {
				"file_contents": self.file_contents.copy(),
				"file_char_counts": self.file_char_counts.copy(),
				"FILE_TOO_LARGE_SENTINEL": self.FILE_TOO_LARGE_SENTINEL,
				"max_content_size": self.max_content_size,
			}

	def generate_directory_tree_custom(self, max_depth=10, max_lines=1000):
		if self.directory_tree_cache:
			return self.directory_tree_cache
		start_path = self.get_project_path(self.current_project_name)
		if not self.is_project_path_valid() or not hasattr(self, 'all_items'): return ""
		tree = {}
		with self._items_lock:
			current_items = self.all_items
		for item in current_items:
			path_parts = item['path'].strip('/').split('/')
			if path_parts == ['']: continue
			current_level = tree
			for i, part in enumerate(path_parts):
				is_last_part = (i == len(path_parts) - 1)
				if item['type'] == 'file' and is_last_part: current_level[part] = 'file'
				else: current_level = current_level.setdefault(part, {})
		lines = [os.path.basename(start_path) + "/"]; indent_str = "    "
		def build_tree_lines(node, depth):
			nonlocal lines
			if depth >= max_depth: return
			keys = sorted(node.keys()); dirs = [k for k in keys if isinstance(node[k], dict)]; files = [k for k in keys if node[k] == 'file']
			for d in dirs:
				if len(lines) >= max_lines: return
				lines.append(f"{indent_str * (depth + 1)}{d}/")
				if len(lines) < max_lines: build_tree_lines(node[d], depth + 1)
			for f in files:
				if len(lines) >= max_lines: return
				lines.append(f"{indent_str * (depth + 1)}{f}")
		build_tree_lines(tree, 0)
		if len(lines) >= max_lines: lines.append("... (output truncated due to size limits)")
		result = "\n".join(lines)
		self.directory_tree_cache = result
		return result

	def _update_outputs_metadata(self, filename, data):
		try:
			with FileLock(self.outputs_metadata_lock_file, timeout=2):
				metadata = {}
				if os.path.exists(self.outputs_metadata_file):
					try:
						with open(self.outputs_metadata_file, 'r', encoding='utf-8') as f:
							metadata = json.load(f)
					except (json.JSONDecodeError, IOError): pass
				metadata[filename] = data
				with open(self.outputs_metadata_file, 'w', encoding='utf-8') as f:
					json.dump(metadata, f, indent=4)
		except (Timeout, IOError) as e:
			logger.error(f"Could not update outputs metadata: {e}")

	def save_and_open_output(self, output, selection, source_name, is_quick_action):
		ts = datetime.now().strftime("%d.%m.%Y_%H.%M.%S")
		sanitized = ''.join(c for c in self.current_project_name if c.isalnum() or c in ' _').rstrip()
		safe_proj_name = os.path.basename(sanitized) if sanitized else "output"
		filename = f"{safe_proj_name}_{ts}.md"; filepath = os.path.join(self.output_dir, filename)
		try:
			with open(filepath, 'w', encoding='utf-8', newline='\n') as f: f.write(output)
			meta_data = {"source_name": source_name, "selection": selection, "is_quick_action": is_quick_action, "project_name": self.current_project_name}
			self._update_outputs_metadata(filename, meta_data)
			open_in_editor(filepath)
		except Exception as e: logger.error("Failed to save and open output: %s", e, exc_info=True)

	def save_output_silently(self, output, project_name, selection, source_name, is_quick_action):
		ts = datetime.now().strftime("%d.%m.%Y_%H.%M.%S")
		sanitized = ''.join(c for c in project_name if c.isalnum() or c in ' _').rstrip()
		safe_proj_name = os.path.basename(sanitized) or "output"
		filename = f"{safe_proj_name}_{ts}.md"; filepath = os.path.join(self.output_dir, filename)
		try:
			with open(filepath, 'w', encoding='utf-8', newline='\n') as f: f.write(output)
			meta_data = {"source_name": source_name, "selection": selection, "is_quick_action": is_quick_action, "project_name": project_name}
			self._update_outputs_metadata(filename, meta_data)
		except Exception as e: logger.error("Failed to save output silently: %s", e, exc_info=True)