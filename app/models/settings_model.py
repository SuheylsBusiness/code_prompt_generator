# File: code_prompt_generator/app/models/settings_model.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import os, copy, time, hashlib, threading
from app.config import SETTINGS_FILE, SETTINGS_LOCK_FILE, HISTORY_SELECTION_KEY, LAST_OWN_WRITE_TIMES, LAST_OWN_WRITE_TIMES_LOCK
from app.utils.file_io import load_json_safely, atomic_write_json
from filelock import Timeout

# Settings Model
# ------------------------------
class SettingsModel:
	# Initialization & State
	# ------------------------------
	def __init__(self):
		self.settings_file = SETTINGS_FILE
		self.lock_file = SETTINGS_LOCK_FILE
		self.settings = {}
		self.settings_lock = threading.RLock()
		self.baseline_settings = {}
		self.last_mtime = 0
		self.load()

	def is_loaded(self): return self.settings is not None

	# Data Persistence
	# ------------------------------
	def load(self):
		loaded_settings = load_json_safely(self.settings_file, self.lock_file, is_fatal=True)
		with self.settings_lock:
			if loaded_settings is None: return
			self.settings = loaded_settings
			self._initialize_defaults()
			self.baseline_settings = copy.deepcopy(self.settings)
		if os.path.exists(self.settings_file): self.last_mtime = os.path.getmtime(self.settings_file)

	def save(self):
		try:
			with self.settings_lock:
				settings_copy = copy.deepcopy(self.settings)
			saved = atomic_write_json(settings_copy, self.settings_file, self.lock_file, "settings")
			if saved:
				with self.settings_lock: self.baseline_settings = copy.deepcopy(self.settings)
			return saved
		except Timeout:
			return False

	def check_for_external_changes(self):
		if not os.path.exists(self.settings_file): return False
		try: current_mtime = os.path.getmtime(self.settings_file)
		except OSError: return False
		with LAST_OWN_WRITE_TIMES_LOCK:
			last_write = LAST_OWN_WRITE_TIMES.get("settings", 0)
		changed = current_mtime > self.last_mtime and abs(current_mtime - last_write) > 0.05
		if changed: self.last_mtime = current_mtime
		return changed

	def _initialize_defaults(self):
		with self.settings_lock:
			self.settings.setdefault('respect_gitignore', True)
			self.settings.setdefault("global_templates", {"Default": "Your task is to\n\n{{dirs}}{{files_provided}}{{file_contents}}"})
			self.settings.setdefault('reset_scroll_on_reset', True)
			self.settings.setdefault("global_blacklist", [])
			self.settings.setdefault("global_keep", [])
			self.settings.setdefault("default_template_name", None)
			self.settings.setdefault(HISTORY_SELECTION_KEY, [])
			self.settings.setdefault('quick_action_history', {})

	def have_settings_changed(self, ignore_geometry=False):
		with self.settings_lock:
			if not ignore_geometry: return self.settings != self.baseline_settings
			
			keys1 = set(self.settings.keys())
			keys2 = set(self.baseline_settings.keys())
			keys1.discard('window_geometry'); keys2.discard('window_geometry')
			if keys1 != keys2: return True
			
			for key in keys1:
				if self.settings[key] != self.baseline_settings.get(key): return True
			return False

	# Getters and Setters
	# ------------------------------
	def get(self, key, default=None):
		with self.settings_lock: return self.settings.get(key, default)
	def set(self, key, value):
		with self.settings_lock: self.settings[key] = value
	def delete(self, key):
		with self.settings_lock:
			if key in self.settings: del self.settings[key]

	# Template Management
	# ------------------------------
	def get_all_templates(self): return self.get("global_templates", {})
	def get_template_content(self, name): return self.get_all_templates().get(name, "")
	def is_template(self, name): return name in self.get_all_templates()
	def get_display_templates(self):
		return sorted([n for n, c in self.get_all_templates().items() if not ("{{CLIPBOARD}}" in c and "{{file_contents}}" not in c)])
	def get_quick_copy_templates(self):
		return sorted([n for n, c in self.get_all_templates().items() if "{{CLIPBOARD}}" in c and "{{file_contents}}" not in c])

	# History Management
	# ------------------------------
	def add_history_selection(self, selection, project_name, char_count):
		with self.settings_lock:
			history = self.get(HISTORY_SELECTION_KEY, [])
			selection_set = set(selection)
			found = next((h for h in history if set(h["files"]) == selection_set and h.get("project") == project_name), None)
			if found:
				found["gens"] = found.get("gens", 0) + 1
				found["timestamp"] = time.time()
				found["char_size"] = char_count
			else:
				history.append({
					"id": hashlib.md5(",".join(sorted(selection)).encode('utf-8')).hexdigest(),
					"files": selection, "timestamp": time.time(), "gens": 1, "project": project_name or "(Unknown)",
					"saved_project_name": project_name,
					"char_size": char_count
				})
			self.set(HISTORY_SELECTION_KEY, sorted(history, key=lambda x: x["timestamp"], reverse=True)[:50])

	def record_quick_action_usage(self, action_name):
		with self.settings_lock:
			history = self.get('quick_action_history', {})
			if action_name not in history: history[action_name] = {'count': 0, 'timestamp': 0}
			history[action_name]['count'] += 1
			history[action_name]['timestamp'] = time.time()
			self.set('quick_action_history', history)