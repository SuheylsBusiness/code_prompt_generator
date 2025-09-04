# File: app/models/settings_model.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization.

import os, copy, time, hashlib, threading
from app.config import (SETTINGS_FILE, SETTINGS_LOCK_FILE, TEMPLATES_FILE, TEMPLATES_LOCK_FILE, HISTORY_FILE, HISTORY_LOCK_FILE, LAST_OWN_WRITE_TIMES, LAST_OWN_WRITE_TIMES_LOCK)
from app.utils.file_io import load_json_safely, atomic_write_with_backup
from filelock import Timeout

# Settings Model
# ------------------------------
class SettingsModel:
	# Initialization & State
	# ------------------------------
	def __init__(self):
		self.settings_file = SETTINGS_FILE; self.lock_file = SETTINGS_LOCK_FILE
		self.templates_file = TEMPLATES_FILE; self.templates_lock_file = TEMPLATES_LOCK_FILE
		self.history_file = HISTORY_FILE; self.history_lock_file = HISTORY_LOCK_FILE
		self.settings, self.templates, self.history = {}, {}, []
		self.baseline_settings, self.baseline_templates, self.baseline_history = {}, {}, []
		self.last_mtime = {"settings": 0, "templates": 0, "history": 0}
		self.data_lock = threading.RLock()
		self.load()

	def is_loaded(self): return self.settings is not None

	# Data Persistence
	# ------------------------------
	def load(self): self.load_settings(); self.load_templates(); self.load_history()
	def load_settings(self):
		data = load_json_safely(self.settings_file, self.lock_file, is_fatal=True)
		with self.data_lock:
			if data is None: return
			self.settings = data; self._initialize_settings_defaults(); self.baseline_settings = copy.deepcopy(self.settings)
		if os.path.exists(self.settings_file):
			try: self.last_mtime['settings'] = os.path.getmtime(self.settings_file)
			except OSError: self.last_mtime['settings'] = 0
	def load_templates(self):
		data = load_json_safely(self.templates_file, self.templates_lock_file)
		with self.data_lock:
			self.templates = data; self._initialize_templates_defaults(); self.baseline_templates = copy.deepcopy(self.templates)
		if os.path.exists(self.templates_file):
			try: self.last_mtime['templates'] = os.path.getmtime(self.templates_file)
			except OSError: self.last_mtime['templates'] = 0
	def load_history(self):
		data = load_json_safely(self.history_file, self.history_lock_file)
		with self.data_lock:
			self.history = data if isinstance(data, list) else []; self.baseline_history = copy.deepcopy(self.history)
		if os.path.exists(self.history_file):
			try: self.last_mtime['history'] = os.path.getmtime(self.history_file)
			except OSError: self.last_mtime['history'] = 0

	def _save_data(self, data, path, lock_path, file_key, baseline_container):
		with self.data_lock: data_copy = copy.deepcopy(data)
		saved = atomic_write_with_backup(data_copy, path, lock_path, file_key)
		if saved:
			with self.data_lock:
				if baseline_container == 'settings': self.baseline_settings = data_copy
				elif baseline_container == 'templates': self.baseline_templates = data_copy
				elif baseline_container == 'history': self.baseline_history = data_copy
		return saved
	def save_settings(self): return self._save_data(self.settings, self.settings_file, self.lock_file, "settings", "settings")
	def save_templates(self): return self._save_data(self.templates, self.templates_file, self.templates_lock_file, "templates", "templates")
	def save_history(self): return self._save_data(self.history, self.history_file, self.history_lock_file, "history", "history")

	def check_for_external_changes(self, file_key):
		path = getattr(self, f"{file_key}_file", None)
		if not path or not os.path.exists(path): return False
		try: current_mtime = os.path.getmtime(path)
		except OSError: return False
		with LAST_OWN_WRITE_TIMES_LOCK: last_own_write = LAST_OWN_WRITE_TIMES.get(file_key, 0)
		if abs(current_mtime - last_own_write) < 0.1: return False
		if current_mtime > self.last_mtime[file_key]:
			self.last_mtime[file_key] = current_mtime
			return True
		return False

	def _initialize_settings_defaults(self):
		with self.data_lock:
			self.settings.setdefault('respect_gitignore', True); self.settings.setdefault('reset_scroll_on_reset', True)
			self.settings.setdefault('autofocus_on_select', True); self.settings.setdefault("global_blacklist", [])
			self.settings.setdefault("global_keep", []); self.settings.setdefault("default_template_name", None)
			self.settings.setdefault('quick_action_history', {}); self.settings.setdefault('output_file_format', '.md')
			self.settings.setdefault('file_content_separator', '--- {path} ---\n{contents}\n--- {path} ---')
			self.settings.setdefault('highlight_base_color', '#ADD8E6'); self.settings.setdefault('selected_files_path_depth', 'Full')
			self.settings.setdefault('highlight_max_value', 200); self.settings.setdefault('sanitize_configs_enabled', False)
	def _initialize_templates_defaults(self):
		with self.data_lock:
			if not self.templates: self.templates["Default"] = "Your task is to\n\n{{dirs}}{{files_provided}}{{file_contents}}"

	def have_settings_changed(self, ignore_geometry=False):
		with self.data_lock:
			s1, s2 = copy.deepcopy(self.settings), copy.deepcopy(self.baseline_settings)
			if ignore_geometry: s1.pop('window_geometry', None); s2.pop('window_geometry', None)
			return s1 != s2
	def have_templates_changed(self):
		with self.data_lock: return self.templates != self.baseline_templates
	def have_history_changed(self):
		with self.data_lock: return self.history != self.baseline_history

	# Getters and Setters
	# ------------------------------
	def get(self, key, default=None):
		with self.data_lock: return self.settings.get(key, default)
	def set(self, key, value):
		with self.data_lock: self.settings[key] = value
	def delete(self, key):
		with self.data_lock:
			if key in self.settings: del self.settings[key]

	# Template Management
	# ------------------------------
	def get_all_templates(self):
		with self.data_lock: return copy.deepcopy(self.templates)
	def set_all_templates(self, data):
		with self.data_lock: self.templates = data
	def get_template_content(self, name):
		with self.data_lock: return self.templates.get(name, "")
	def is_template(self, name):
		with self.data_lock: return name in self.templates
	def get_display_templates(self):
		with self.data_lock: templates = self.templates
		return sorted([n for n, c in templates.items() if not ("{{CLIPBOARD}}" in c and "{{file_contents}}" not in c)])
	def get_quick_copy_templates(self):
		with self.data_lock: templates = self.templates
		return sorted([n for n, c in templates.items() if "{{CLIPBOARD}}" in c and "{{file_contents}}" not in c])

	# History Management
	# ------------------------------
	def get_history(self):
		with self.data_lock: return copy.deepcopy(self.history)
	def add_history_selection(self, selection, project_name, char_count, source_name=None, is_quick_action=False):
		with self.data_lock:
			history = self.history; selection_set = set(selection)
			found = next((h for h in history if set(h["files"]) == selection_set and h.get("project") == project_name), None)
			if found:
				found.update({"gens": found.get("gens", 0) + 1, "timestamp": time.time(), "char_size": char_count, "source_name": source_name, "is_quick_action": is_quick_action})
			else:
				history.append({"id": hashlib.md5(",".join(sorted(selection)).encode('utf-8')).hexdigest(), "files": selection, "timestamp": time.time(), "gens": 1, "project": project_name or "(Unknown)", "char_size": char_count, "source_name": source_name, "is_quick_action": is_quick_action})
			self.history = sorted(history, key=lambda x: x["timestamp"], reverse=True)
		self.save_history()

	def record_quick_action_usage(self, action_name):
		with self.data_lock:
			history = self.get('quick_action_history', {});
			if action_name not in history: history[action_name] = {'count': 0, 'timestamp': 0}
			history[action_name]['count'] += 1; history[action_name]['timestamp'] = time.time()
			self.set('quick_action_history', history)