# File: code_prompt_generator/app/models/project_model.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import os, time, threading, copy, tkinter as tk, concurrent.futures
import traceback
from app.config import get_logger, PROJECTS_FILE, PROJECTS_LOCK_FILE, OUTPUT_DIR, MAX_FILES, MAX_CONTENT_SIZE, MAX_FILE_SIZE
from app.utils.file_io import load_json_safely, atomic_write_json, safe_read_file
from app.utils.path_utils import parse_gitignore, path_should_be_ignored, is_dir_forced_kept
from app.utils.system_utils import open_in_editor, unify_line_endings
from datetime import datetime

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
        self.max_files = MAX_FILES
        self.max_content_size = MAX_CONTENT_SIZE
        self.max_file_size = MAX_FILE_SIZE
        self.projects = {}
        self.baseline_projects = {}
        self.last_mtime = 0
        self.current_project_name = None
        self.all_items, self.filtered_items = [], []
        self.selected_paths = set()
        self.file_mtimes, self.file_contents = {}, {}
        self.file_char_counts = {}
        self.project_tree_scroll_pos = 0.0
        self._loading_thread = None
        self._autoblacklist_thread = None
        self._file_watcher_thread = None
        self._bulk_update_active = False
        self._file_content_lock = threading.Lock()
        self._file_watcher_queue = None
        self.load()

    def is_loaded(self): return self.projects is not None
    def is_loading(self): return self._loading_thread and self._loading_thread.is_alive()
    def is_autoblacklisting(self): return self._autoblacklist_thread and self._autoblacklist_thread.is_alive()
    def is_bulk_updating(self): return self._bulk_update_active

    def start_file_watcher(self, queue=None):
        from app.config import FILE_WATCHER_INTERVAL_MS
        self._file_watcher_queue = queue
        if self._file_watcher_thread and self._file_watcher_thread.is_alive(): return
        self._file_watcher_thread = threading.Thread(target=self._file_watcher_worker, args=(FILE_WATCHER_INTERVAL_MS / 1000,), daemon=True)
        self._file_watcher_thread.start()
        logger.info("Project file watcher thread started.")

    def _file_watcher_worker(self, interval_sec):
        while True:
            time.sleep(interval_sec)
            if self.current_project_name and self.all_items:
                all_known_files = [item['path'] for item in self.all_items if item['type'] == 'file']
                if all_known_files and self.update_file_contents(all_known_files) and self._file_watcher_queue:
                    self._file_watcher_queue.put(('file_contents_loaded', self.current_project_name))

    # Data Persistence
    # ------------------------------
    def load(self):
        self.projects = load_json_safely(self.projects_file, self.lock_file, is_fatal=True)
        if self.projects is None: self.projects = {}
        self.baseline_projects = copy.deepcopy(self.projects)
        if os.path.exists(self.projects_file): self.last_mtime = os.path.getmtime(self.projects_file)

    def save(self):
        atomic_write_json(self.projects, self.projects_file, self.lock_file, "projects")
        self.baseline_projects = copy.deepcopy(self.projects)

    def check_for_external_changes(self):
        from app.config import LAST_OWN_WRITE_TIMES
        if not os.path.exists(self.projects_file): return False
        try: current_mtime = os.path.getmtime(self.projects_file)
        except OSError: return False
        changed = current_mtime > self.last_mtime and abs(current_mtime - LAST_OWN_WRITE_TIMES.get("projects", 0)) > 1.0
        if changed: self.last_mtime = current_mtime
        return changed

    def have_projects_changed(self): return self.projects != self.baseline_projects

    # Project Management
    # ------------------------------
    def exists(self, name): return name in self.projects
    def add_project(self, name, path):
        self.projects[name] = {"path": path, "last_files": [], "blacklist": [], "keep": [], "prefix": "", "click_counts": {}, "last_usage": time.time(), "usage_count": 1}
        self.save()
    def remove_project(self, name):
        if name in self.projects: del self.projects[name]; self.save()
    def get_project_path(self, name): return self.projects.get(name, {}).get("path")
    def is_project_path_valid(self): return self.current_project_name and os.path.isdir(self.get_project_path(self.current_project_name))
    def set_current_project(self, name):
        self.current_project_name = name
        if name and name in self.projects:
            self.project_tree_scroll_pos = self.projects[name].get("scroll_pos", 0.0)
        else:
            self.project_tree_scroll_pos = 0.0
    def set_project_scroll_pos(self, name, pos):
        if name in self.projects: self.projects[name]['scroll_pos'] = pos
    def update_project_usage(self):
        if self.current_project_name and self.current_project_name in self.projects:
            proj = self.projects[self.current_project_name]
            proj["last_usage"] = time.time()
            proj["usage_count"] = proj.get("usage_count", 0) + 1
            self.save()
    def update_project(self, name, data):
        if name in self.projects:
            self.projects[name].update(data)

    def get_sorted_projects_for_display(self):
        return sorted([(k, p.get("last_usage", 0), p.get("usage_count", 0)) for k, p in self.projects.items()], key=lambda x: (-x[1], -x[2], x[0].lower()))

    # File & Item Management
    # ------------------------------
    def load_items_async(self, is_new_project, queue):
        self._loading_thread = threading.Thread(target=self._load_items_worker, args=(is_new_project, queue), daemon=True)
        self._loading_thread.start()

    def _load_items_worker(self, is_new_project, queue):
        if not self.current_project_name: return
        proj = self.projects[self.current_project_name]; proj_path = proj["path"]
        if not os.path.isdir(proj_path): return queue.put(('load_items_done', ("error", (None,), is_new_project)))
        respect_git = self.settings_model.get('respect_gitignore', True)
        git_patterns = parse_gitignore(os.path.join(proj_path, '.gitignore')) if respect_git and os.path.isfile(os.path.join(proj_path, '.gitignore')) else []
        proj_bl = proj.get("blacklist", []); glob_bl = self.settings_model.get("global_blacklist", [])
        comb_bl_lower = [b.strip().lower().replace("\\", "/") for b in list(set(proj_bl + glob_bl))]
        proj_kp = proj.get("keep", []); glob_kp = self.settings_model.get("global_keep", [])
        comb_kp = list(set(proj_kp + glob_kp))
        found_items, file_count, limit_exceeded = [], 0, False
        for root, dirs, files in os.walk(proj_path, topdown=True):
            if file_count >= self.max_files: limit_exceeded = True; break
            rel_root = os.path.relpath(root, proj_path).replace("\\", "/"); rel_root = "" if rel_root == "." else rel_root
            dirs[:] = sorted([d for d in dirs if not path_should_be_ignored(f"{rel_root}/{d}".lstrip("/").lower(), respect_git, git_patterns, comb_kp, comb_bl_lower) or is_dir_forced_kept(f"{rel_root}/{d}".lstrip("/").lower(), comb_kp)])
            if rel_root: found_items.append({"type": "dir", "path": rel_root + "/", "level": rel_root.count('/')})
            for f in sorted(files):
                if file_count >= self.max_files: limit_exceeded = True; break
                rel_path = f"{rel_root}/{f}".lstrip("/")
                if not path_should_be_ignored(rel_path.lower(), respect_git, git_patterns, comb_kp, comb_bl_lower):
                    if os.path.isfile(os.path.join(root, f)):
                        found_items.append({"type": "file", "path": rel_path, "level": rel_path.count('/')}); file_count += 1
        
        self.all_items = found_items
        self.filtered_items = found_items
        self._initialize_file_data(found_items)

        queue.put(('load_items_done', ("ok", (limit_exceeded,), is_new_project)))
        threading.Thread(target=self._load_file_contents_worker, args=(queue,), daemon=True).start()

    def _initialize_file_data(self, items):
        if not self.current_project_name: return
        proj_path = self.get_project_path(self.current_project_name)
        files_to_load = [item["path"] for item in items if item["type"] == "file"]
        self.file_char_counts.clear(); self.file_contents.clear(); self.file_mtimes.clear()
        for rp in files_to_load:
            ap = os.path.join(proj_path, rp)
            try:
                fsize = os.path.getsize(ap) if os.path.isfile(ap) else 0
                self.file_char_counts[rp] = fsize
                self.file_contents[rp] = None # Placeholder, content loaded on demand
            except OSError:
                self.file_contents[rp], self.file_char_counts[rp] = None, 0

    def _load_file_contents_worker(self, queue):
        queue.put(('file_contents_loaded', self.current_project_name))

    def set_items(self, items): self.all_items = items; self.filtered_items = items
    def set_filtered_items(self, items): self.filtered_items = items
    def get_filtered_items(self): return self.filtered_items

    def update_file_contents(self, selected_files):
        with self._file_content_lock:
            proj_path = self.get_project_path(self.current_project_name)
            if not proj_path or not selected_files: return False

            dirty = []
            for rp in selected_files:
                full_path = os.path.join(proj_path, rp)
                if not os.path.isfile(full_path):
                    if rp in self.file_mtimes: dirty.append(rp)
                    continue
                try:
                    if self.file_mtimes.get(rp) != os.stat(full_path).st_mtime_ns: dirty.append(rp)
                except OSError:
                    if rp in self.file_mtimes: dirty.append(rp)

            if not dirty: return False

            def load_single(relative_path):
                full_path = os.path.join(proj_path, relative_path)
                try:
                    st = os.stat(full_path)
                    content = safe_read_file(full_path) if st.st_size <= self.max_file_size else None
                    if content is not None: content = unify_line_endings(content)
                    return (relative_path, content, st.st_mtime_ns, st.st_size)
                except FileNotFoundError: return (relative_path, None, None, 0)
                except OSError: return (relative_path, None, 0, 0)

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                for rp, content, mtime, size in executor.map(load_single, dirty):
                    if mtime is None:
                        self.file_contents.pop(rp, None)
                        self.file_char_counts.pop(rp, None)
                        self.file_mtimes.pop(rp, None)
                    elif mtime > 0:
                        self.file_contents[rp] = content
                        self.file_char_counts[rp] = len(content) if content is not None else size
                        self.file_mtimes[rp] = mtime
                    else:
                        self.file_contents[rp] = None; self.file_char_counts[rp] = 0; self.file_mtimes.pop(rp, None)
            return True

    # Selection & State Tracking
    # ------------------------------
    def set_selection(self, selection_set):
        self.selected_paths = set(selection_set)

    def update_selection(self, path, is_selected):
        if is_selected: self.selected_paths.add(path)
        else: self.selected_paths.discard(path)

    def get_selected_files(self): return sorted(list(self.selected_paths))
    def set_last_used_files(self, selection):
        if self.current_project_name and self.current_project_name in self.projects: self.projects[self.current_project_name]['last_files'] = selection
    def set_last_used_template(self, template_name):
        if self.current_project_name and self.current_project_name in self.projects: self.projects[self.current_project_name]['last_template'] = template_name
    def increment_click_count(self, file_path):
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
        proj = self.projects[proj_name]
        current_bl = proj.get("blacklist", []) + self.settings_model.get("global_blacklist", [])
        keep_patterns = proj.get("keep", []) + self.settings_model.get("global_keep", [])
        git_patterns = parse_gitignore(os.path.join(proj_path, '.gitignore')) if self.settings_model.get('respect_gitignore', True) else []
        new_blacklisted = []
        for root, dirs, files in os.walk(proj_path):
            rel_root = os.path.relpath(root, proj_path).replace("\\", "/").strip("/")
            if any(bl.lower() in rel_root.lower() for bl in current_bl if rel_root): continue
            unignored_files = [f for f in files if not path_should_be_ignored(f"{rel_root}/{f}".strip("/").lower(), self.settings_model.get('respect_gitignore',True), git_patterns, keep_patterns, current_bl)]
            if len(unignored_files) > threshold and rel_root and rel_root.lower() not in [b.lower() for b in current_bl]: new_blacklisted.append(rel_root)
        return new_blacklisted

    def add_to_blacklist(self, proj_name, dirs):
        if proj_name in self.projects:
            proj = self.projects[proj_name]
            proj["blacklist"] = list(dict.fromkeys(proj.get("blacklist", []) + dirs))
            self.save()

    # Generation & Output Logic
    # ------------------------------
    def simulate_final_prompt(self, selection, template_name, clipboard_content=""):
        prompt, _, total_selection_chars = self.simulate_generation(selection, template_name, clipboard_content)
        return prompt.rstrip('\n') + '\n', total_selection_chars

    def simulate_generation(self, selection, template_name, clipboard_content):
        if not self.current_project_name or self.current_project_name not in self.projects: return "", [], 0
        proj = self.projects[self.current_project_name]
        prefix = proj.get("prefix", "").strip()
        s1 = f"### {prefix} File Structure" if prefix else "### File Structure"
        s2 = f"### {prefix} Code Files provided" if prefix else "### Code Files provided"
        s3 = f"### {prefix} Code Files" if prefix else "### Code Files"
        dir_tree = self.generate_directory_tree_custom()
        template_content = self.settings_model.get_template_content(template_name)
        if "{{CLIPBOARD}}" in template_content: template_content = template_content.replace("{{CLIPBOARD}}", clipboard_content)

        content_blocks, total_size, total_selection_chars = [], 0, 0
        for rp in selection:
            content = self.file_contents.get(rp)
            if content is None: continue
            total_selection_chars += len(content)
            if total_size + len(content) > self.max_content_size: break
            content_blocks.append(f"--- {rp} ---\n{content}\n--- {rp} ---\n")
            total_size += len(content)
        prompt = template_content.replace("{{dirs}}", f"{s1}\n\n{dir_tree.strip()}")
        if "{{files_provided}}" in prompt:
            lines = "".join(f"- {x}\n" for x in selection if x in self.file_contents and self.file_contents.get(x) is not None)
            prompt = prompt.replace("{{files_provided}}", f"\n\n{s2}\n{lines}".rstrip('\n'))
        else: prompt = prompt.replace("{{files_provided}}", "")
        file_content_section = f"\n\n{s3}\n\n{''.join(content_blocks)}" if content_blocks else ""
        return prompt.replace("{{file_contents}}", file_content_section), content_blocks, total_selection_chars

    def generate_directory_tree_custom(self, max_depth=10, max_lines=1000):
        start_path = self.get_project_path(self.current_project_name)
        if not self.is_project_path_valid() or not hasattr(self, 'all_items'): return ""
        tree = {}
        for item in self.all_items:
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
        return "\n".join(lines)

    def save_and_open_output(self, output):
        ts = datetime.now().strftime("%d.%m.%Y_%H.%M.%S")
        safe_proj_name = ''.join(c for c in self.current_project_name if c.isalnum() or c in ' _').rstrip()
        filename = f"{safe_proj_name}_{ts}.md"; filepath = os.path.join(self.output_dir, filename)
        try:
            with open(filepath, 'w', encoding='utf-8', newline='\n') as f: f.write(output)
            open_in_editor(filepath)
        except Exception: logger.error("%s", traceback.format_exc())

    def save_output_silently(self, output, project_name):
        ts = datetime.now().strftime("%d.%m.%Y_%H.%M.%S")
        safe_proj_name = ''.join(c for c in project_name if c.isalnum() or c in ' _').rstrip() or "output"
        filename = f"{safe_proj_name}_{ts}.md"; filepath = os.path.join(self.output_dir, filename)
        try:
            with open(filepath, 'w', encoding='utf-8', newline='\n') as f: f.write(output)
        except Exception as e: logger.error("Failed to save output silently: %s", e, exc_info=True)