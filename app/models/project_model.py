# File: code_prompt_generator/app/models/project_model.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import os, time, threading, copy, tkinter as tk, concurrent.futures, itertools, json
import traceback
try:
	from watchdog.observers import Observer
	from watchdog.events import FileSystemEventHandler
except ImportError:
	Observer = None
	FileSystemEventHandler = object
from app.config import get_logger, PROJECTS_FILE, PROJECTS_LOCK_FILE, OUTPUT_DIR, MAX_FILES, MAX_CONTENT_SIZE, MAX_FILE_SIZE, LAST_OWN_WRITE_TIMES, LAST_OWN_WRITE_TIMES_LOCK
from app.utils.file_io import load_json_safely, atomic_write_json, safe_read_file
from app.utils.path_utils import parse_gitignore, path_should_be_ignored
from app.utils.system_utils import open_in_editor, unify_line_endings
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
		self.projects_file = PROJECTS_FILE
		self.lock_file = PROJECTS_LOCK_FILE
		self.output_dir = OUTPUT_DIR
		self.outputs_metadata_file = os.path.join(self.output_dir, '_metadata.json')
		self.outputs_metadata_lock_file = self.outputs_metadata_file + '.lock'
		self.max_files = MAX_FILES
		self.max_content_size = MAX_CONTENT_SIZE
		self.max_file_size = MAX_FILE_SIZE
		self.projects = {}
		self.projects_lock = threading.RLock()
		self.baseline_projects = {}
		self.last_mtime = 0
		self.current_project_name = None
		self.all_items, self.filtered_items = [], []
		self.selected_paths = set()
		self.selected_paths_lock = threading.Lock()
		self.file_mtimes, self.file_contents = {}, {}
		self.file_char_counts = {}
		self.project_tree_scroll_pos = 0.0
		self.directory_tree_cache = None
		self._loading_thread = None
		self._autoblacklist_thread = None
		self._observer = None
		self._bulk_update_active = False
		self._items_lock = threading.Lock()
		self._file_content_lock = threading.Lock()
		self._file_watcher_queue = None
		self._stop_event = threading.Event()
		self.MAX_IO_WORKERS = min(8, (os.cpu_count() or 1))
		self._thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.MAX_IO_WORKERS)
		self.FILE_TOO_LARGE_SENTINEL = "<FILE TOO LARGE – SKIPPED>"
		self.load()

	def is_loaded(self): return self.projects is not None
	def is_loading(self): return self._loading_thread and self._loading_thread.is_alive()
	def is_autoblacklisting(self): return self._autoblacklist_thread and self._autoblacklist_thread.is_alive()
	def is_bulk_updating(self): return self._bulk_update_active

	def start_file_watcher(self, queue=None):
		self._file_watcher_queue = queue
		if not Observer: return logger.warning("Watchdog not installed. File changes will not be detected automatically.")
		with self.projects_lock:
			if self._observer and self._observer.is_alive(): return
			proj_path = self.get_project_path(self.current_project_name)
			if not proj_path or not os.path.isdir(proj_path): return
			proj_bl = self.projects.get(self.current_project_name, {}).get("blacklist", [])
		
		model = self # Avoid passing self to inner class
		class _Handler(FileSystemEventHandler):
			def _handle(self, p):
				if model._stop_event.is_set(): return
				try: rel = os.path.relpath(p, proj_path).replace("\\", "/")
				except ValueError: return
				
				glob_bl = model.settings_model.get("global_blacklist", [])
				blacklist_patterns = {b.strip().lower().replace("\\", "/") for b in proj_bl + glob_bl if b.strip()}
				if any(pattern in rel.lower().split('/') for pattern in blacklist_patterns): return

				if model.update_file_contents([rel]) and queue:
					queue.put(('file_contents_loaded', model.current_project_name))

			def on_modified(self, e): self._handle(e.src_path)
			def on_created(self, e): self._handle(e.src_path)
			def on_deleted(self, e): self._handle(e.src_path)

		h = _Handler()
		self._observer = Observer()
		self._observer.schedule(h, proj_path, recursive=True)
		self._observer.daemon = True
		self._observer.start()
		logger.info("Project file watcher started via watchdog.")

	def stop_threads(self):
		logger.info("Stopping model background threads.")
		self._stop_event.set()
		if self._observer and Observer:
			try:
				self._observer.stop()
				self._observer.join(timeout=1.0)
			except Exception: pass
		if self._thread_pool:
			self._thread_pool.shutdown(wait=True)

	# Data Persistence
	# ------------------------------
	def load(self):
		loaded_projects = load_json_safely(self.projects_file, self.lock_file, is_fatal=True)
		with self.projects_lock:
			self.projects = loaded_projects if loaded_projects is not None else {}
			self.baseline_projects = copy.deepcopy(self.projects)
		if os.path.exists(self.projects_file): self.last_mtime = os.path.getmtime(self.projects_file)

	def save(self, update_baseline=True):
		try:
			with self.projects_lock:
				projects_copy = copy.deepcopy(self.projects)
			ok = atomic_write_json(projects_copy, self.projects_file, self.lock_file, "projects")
			if ok and update_baseline:
				with self.projects_lock:
					self.baseline_projects = copy.deepcopy(self.projects)
			return ok
		except Timeout:
			return False

	def check_for_external_changes(self, check_content=False):
		if not os.path.exists(self.projects_file): return False
		current_mtime = 0
		with LAST_OWN_WRITE_TIMES_LOCK:
			try: current_mtime = os.path.getmtime(self.projects_file)
			except OSError: return False
			last_write = LAST_OWN_WRITE_TIMES.get("projects", 0)

		if current_mtime <= self.last_mtime: return False
		if abs(current_mtime - last_write) < 0.1:
			self.last_mtime = current_mtime
			return False
		
		if check_content:
			externally_loaded_data = load_json_safely(self.projects_file, self.lock_file)
			with self.projects_lock:
				if externally_loaded_data == self.projects:
					self.last_mtime = current_mtime
					return False

		self.last_mtime = current_mtime
		return True

	def have_projects_changed(self):
		with self.projects_lock:
			return self.projects != self.baseline_projects

	# Project Management
	# ------------------------------
	def exists(self, name):
		with self.projects_lock: return name in self.projects
	def add_project(self, name, path):
		with self.projects_lock: self.projects[name] = {"path": path, "last_files": [], "blacklist": [], "keep": [], "prefix": "", "click_counts": {}, "last_usage": time.time(), "usage_count": 1, "ui_state": {}}
		self.save()
	def remove_project(self, name):
		with self.projects_lock:
			if name in self.projects: del self.projects[name]
		self.save()
	def get_project_path(self, name):
		with self.projects_lock: return self.projects.get(name, {}).get("path")
	def get_project_data(self, name, key=None, default=None):
		with self.projects_lock:
			if key: return self.projects.get(name, {}).get(key, default)
			return self.projects.get(name, {})
	def is_project_path_valid(self): return self.current_project_name and os.path.isdir(self.get_project_path(self.current_project_name))
	def set_current_project(self, name):
		if self.current_project_name != name:
			self.file_contents.clear(); self.file_mtimes.clear(); self.file_char_counts.clear()
			self.directory_tree_cache = None
			if self._observer:
				self._observer.stop()
				try: self._observer.join(timeout=1.0)
				except Exception: pass
				self._observer = None
			with self._items_lock: self.all_items.clear(); self.filtered_items.clear()
			with self.selected_paths_lock: self.selected_paths.clear()
		self.current_project_name = name
		with self.projects_lock:
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
		self.save()
	def update_project(self, name, data):
		with self.projects_lock:
			if name in self.projects: self.projects[name].update(data)

	def get_sorted_projects_for_display(self):
		with self.projects_lock:
			return sorted([(k, p.get("last_usage", 0), p.get("usage_count", 0)) for k, p in self.projects.items()], key=lambda x: (-x[1], -x[2], x[0].lower()))

	# File & Item Management
	# ------------------------------
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

		def scan_recursively(path, rel_prefix):
			nonlocal file_count, limit_exceeded
			if file_count >= self.max_files: limit_exceeded = True; return
			
			try: entries = sorted(os.scandir(path), key=lambda e: e.name)
			except OSError: return

			dirs_to_scan = []
			for entry in entries:
				if file_count >= self.max_files: limit_exceeded = True; break
				entry_rel_path = f"{rel_prefix}/{entry.name}".lstrip("/")
				
				if entry.is_dir():
					if not path_should_be_ignored(f"{entry_rel_path}/", respect_git, git_patterns, comb_kp_lower, comb_bl_lower):
						found_items.append({"type": "dir", "path": entry_rel_path + "/", "level": entry_rel_path.count('/')})
						dirs_to_scan.append(entry)
				elif entry.is_file():
					if not path_should_be_ignored(entry_rel_path, respect_git, git_patterns, comb_kp_lower, comb_bl_lower):
						found_items.append({"type": "file", "path": entry_rel_path, "level": entry_rel_path.count('/')})
						file_count += 1
			
			for d_entry in dirs_to_scan:
				scan_recursively(d_entry.path, f"{rel_prefix}/{d_entry.name}".lstrip("/"))

		scan_recursively(proj_path, "")
		queue.put(('load_items_done', ("ok", (found_items, limit_exceeded), is_new_project)))

	def _initialize_file_data(self, items):
		if not self.current_project_name: return
		proj_path = self.get_project_path(self.current_project_name)
		files_to_load = [item["path"] for item in items if item["type"] == "file"]
		with self._file_content_lock:
			self.file_char_counts.clear(); self.file_contents.clear(); self.file_mtimes.clear()
			for rp in files_to_load:
				ap = os.path.join(proj_path, rp)
				try:
					fsize = os.path.getsize(ap) if os.path.isfile(ap) else 0
					self.file_char_counts[rp] = fsize
					self.file_contents[rp] = None # Placeholder, content loaded on demand
				except OSError:
					self.file_contents[rp], self.file_char_counts[rp] = None, 0
		self.directory_tree_cache = None

	def _load_file_contents_worker(self, queue):
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

		with self._file_content_lock: mtimes_copy = self.file_mtimes.copy()

		dirty = []
		for rp in selected_files:
			full_path = os.path.join(proj_path, rp)
			if not os.path.isfile(full_path):
				if rp in mtimes_copy: dirty.append(rp)
				continue
			try:
				if mtimes_copy.get(rp) != os.stat(full_path).st_mtime_ns: dirty.append(rp)
			except OSError:
				if rp in mtimes_copy: dirty.append(rp)

		if not dirty: return False

		def load_single(relative_path):
			full_path = os.path.join(proj_path, relative_path)
			try:
				st = os.stat(full_path)
				content = safe_read_file(full_path) if st.st_size <= self.max_file_size else self.FILE_TOO_LARGE_SENTINEL
				if content not in [None, self.FILE_TOO_LARGE_SENTINEL]: content = unify_line_endings(content)
				return (relative_path, content, st.st_mtime_ns, st.st_size)
			except FileNotFoundError: return (relative_path, None, None, 0)
			except OSError: return (relative_path, None, 0, 0)

		if self._stop_event.is_set(): return False
		results = list(self._thread_pool.map(load_single, dirty))

		with self._file_content_lock:
			for rp, content, mtime, size in results:
				if mtime is None:
					self.file_contents.pop(rp, None)
					self.file_char_counts.pop(rp, None)
					self.file_mtimes.pop(rp, None)
				elif mtime > 0:
					self.file_contents[rp] = content
					self.file_char_counts[rp] = len(content) if content not in [None, self.FILE_TOO_LARGE_SENTINEL] else size
					self.file_mtimes[rp] = mtime
				else:
					self.file_contents[rp] = None; self.file_char_counts[rp] = 0; self.file_mtimes.pop(rp, None)
		return True

	# Selection & State Tracking
	# ------------------------------
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

	def set_last_used_files(self, selection):
		with self.projects_lock:
			if self.current_project_name and self.current_project_name in self.projects: self.projects[self.current_project_name]['last_files'] = selection
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

	# Auto-Blacklisting
	# ------------------------------
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
		self.save()

	# Generation & Output Logic
	# ------------------------------
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
		if "{{CLIPBOARD}}" in template_content: template_content = template_content.replace("{{CLIPBOARD}}", clipboard_content)

		content_blocks, oversized_files, truncated_files = [], [], []
		total_content_size, total_selection_chars = 0, 0
		files_processed = set()

		with self._file_content_lock:
			for i, rp in enumerate(selection):
				content = self.file_contents.get(rp)
				is_oversized = (content == self.FILE_TOO_LARGE_SENTINEL)

				if is_oversized:
					oversized_files.append(rp)
					total_selection_chars += self.file_char_counts.get(rp, 0)
					files_processed.add(rp)
					continue

				if content is None: continue

				if total_content_size + len(content) > self.max_content_size and content:
					truncated_files.extend(selection[i:])
					break

				content_blocks.append(f"--- {rp} ---\n{content}\n--- {rp} ---\n")
				total_content_size += len(content)
				total_selection_chars += len(content)
				files_processed.add(rp)

		prompt = template_content.replace("{{dirs}}", f"{s1}\n\n{dir_tree.strip()}")
		if "{{files_provided}}" in prompt:
			files_for_list = selection # List all selected files, even if content is omitted
			lines = "".join(f"- {x}\n" for x in files_for_list)
			prompt = prompt.replace("{{files_provided}}", f"\n\n{s2}\n{lines}".rstrip('\n'))
		else: prompt = prompt.replace("{{files_provided}}", "")
		file_content_section = f"\n\n{s3}\n\n{''.join(content_blocks)}" if content_blocks else ""
		return prompt.replace("{{file_contents}}", file_content_section), total_selection_chars, oversized_files, truncated_files

	@staticmethod
	def simulate_generation_static(selection, template_content, clipboard_content, dir_tree, project_data, model_config):
		prefix = project_data.get("prefix", "").strip()
		s1 = f"### {prefix} File Structure" if prefix else "### File Structure"
		s2 = f"### {prefix} Code Files provided" if prefix else "### Code Files provided"
		s3 = f"### {prefix} Code Files" if prefix else "### Code Files"

		if "{{CLIPBOARD}}" in template_content: template_content = template_content.replace("{{CLIPBOARD}}", clipboard_content)

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

		prompt = template_content.replace("{{dirs}}", f"{s1}\n\n{dir_tree.strip()}")
		if "{{files_provided}}" in prompt:
			lines = "".join(f"- {x}\n" for x in selection)
			prompt = prompt.replace("{{files_provided}}", f"\n\n{s2}\n{lines}".rstrip('\n'))
		else: prompt = prompt.replace("{{files_provided}}", "")
		file_content_section = f"\n\n{s3}\n\n{''.join(content_blocks)}" if content_blocks else ""
		final_prompt = prompt.replace("{{file_contents}}", file_content_section)
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
		lines = [os.path.basename(start_path) + "/"]; indent_str = "    "
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
					with open(self.outputs_metadata_file, 'r', encoding='utf-8') as f:
						try: metadata = json.load(f)
						except json.JSONDecodeError: pass
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
			self._update_outputs_metadata(os.path.basename(filepath), meta_data)
			open_in_editor(filepath)
		except Exception: logger.error("%s", traceback.format_exc())

	def save_output_silently(self, output, project_name, selection, source_name, is_quick_action):
		ts = datetime.now().strftime("%d.%m.%Y_%H.%M.%S")
		sanitized = ''.join(c for c in project_name if c.isalnum() or c in ' _').rstrip()
		safe_proj_name = os.path.basename(sanitized) or "output"
		filename = f"{safe_proj_name}_{ts}.md"; filepath = os.path.join(self.output_dir, filename)
		try:
			with open(filepath, 'w', encoding='utf-8', newline='\n') as f: f.write(output)
			meta_data = {"source_name": source_name, "selection": selection, "is_quick_action": is_quick_action, "project_name": project_name}
			self._update_outputs_metadata(os.path.basename(filename), meta_data)
		except Exception as e: logger.error("Failed to save output silently: %s", e, exc_info=True)