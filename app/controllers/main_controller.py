# File: code_prompt_generator/app/controllers/main_controller.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import os, time, threading, queue, hashlib, platform, subprocess, codecs, re, concurrent.futures
from tkinter import filedialog
import traceback
from app.config import get_logger, set_project_file_handler
from app.utils.ui_helpers import show_error_centered, show_warning_centered, show_yesno_centered, show_yesnocancel_centered, format_german_thousand_sep
from app.utils.system_utils import open_in_editor, unify_line_endings
from datetime import datetime

logger = get_logger(__name__)

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
        self.is_precomputing = threading.Lock()
        self.precompute_args = (None, "")
        self._stop_event = threading.Event()
        self.char_count_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.generation_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self.quick_action_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self.initialize_state()

    def set_view(self, view):
        self.view = view
        self.load_initial_state()
        self.start_background_watchers()
        self.view.update_quick_action_buttons()

    def initialize_state(self):
        self.project_search_buffer = ""
        self.project_search_last_key_time = 0

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
        self.watch_file_changes()
        self.start_precompute_worker()
        self.project_model.start_file_watcher(self.queue)

    def stop_threads(self):
        logger.info("Stopping controller background threads.")
        self._stop_event.set()
        if self.char_count_executor:
            self.char_count_executor.shutdown(wait=False, cancel_futures=True)
        if self.generation_pool:
            self.generation_pool.shutdown(wait=False, cancel_futures=True)
        if self.quick_action_pool:
            self.quick_action_pool.shutdown(wait=False, cancel_futures=True)
        self.precompute_request.set()
        if self.precompute_thread and self.precompute_thread.is_alive():
            self.precompute_thread.join(timeout=1.0)

    # Application Lifecycle & Context
    # ------------------------------
    def on_closing(self):
        projects_changed = self.project_model.have_projects_changed()
        settings_changed = self.settings_model.have_settings_changed(ignore_geometry=True)
        change_descs = []
        if projects_changed: change_descs.append("Project data (e.g., last file selections, usage stats)")
        if settings_changed: change_descs.append("Application settings (e.g., templates, last project)")

        if change_descs:
            message = "There are unsaved changes:\n\n- " + "\n- ".join(change_descs) + "\n\nSave changes before closing?"
            res = show_yesnocancel_centered(self.view, "Unsaved Changes", message, yes_text="Save", no_text="Don't Save")
            if res == "cancel": return
            if res == "yes":
                self.settings_model.set('window_geometry', self.view.geometry())
                settings_saved = self.settings_model.save()
                projects_saved = self.project_model.save()
                if not settings_saved or not projects_saved:
                    show_warning_centered(self.view, "Save Failed", "Could not save all changes. A file might be locked.")
        elif self.settings_model.get('window_geometry') != self.view.geometry():
                        self.settings_model.set('window_geometry', self.view.geometry())
                        self.settings_model.save()

        self.project_model.stop_threads()
        self.stop_threads()
        self.view.destroy()

    def watch_file_changes(self):
        projects_changed = self.project_model.check_for_external_changes()
        settings_changed = self.settings_model.check_for_external_changes()
        if projects_changed:
            logger.info("External change in projects.json, reloading.")
            current_project = self.project_model.current_project_name
            self.project_model.load()
            self.update_projects_list()
            if current_project and not self.project_model.exists(current_project):
                self.project_model.set_current_project(None)
                self.view.clear_project_view()
            elif current_project:
                self.refresh_files()
        if settings_changed:
            logger.info("External change in settings.json, reloading.")
            self.settings_model.load()
            self.load_templates(force_refresh=True)
            self.view.update_quick_action_buttons()
        if self.view.winfo_exists():
            self.view.after(500, self.watch_file_changes)

    # Project & Template Management
    # ------------------------------
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
        name = disp.split(' (')[0] if ' (' in disp else disp
        if not name: return show_warning_centered(self.view, "No Project Selected", "Please select a project to remove.")
        if not self.project_model.exists(name): return show_warning_centered(self.view, "Invalid Selection", "Project not found.")
        if show_yesno_centered(self.view, "Remove Project", f"Are you sure you want to remove '{name}'?"):
            self.project_model.remove_project(name)
            if self.settings_model.get('last_selected_project') == name:
                self.settings_model.delete('last_selected_project')
                self.settings_model.save()
            
            if self.project_model.current_project_name == name: self.project_model.set_current_project(None)

            self.update_projects_list()
            all_projs = self.view.project_dropdown['values']
            if all_projs:
                new_proj_disp = all_projs[0]
                new_proj_name = new_proj_disp.split(' (')[0] if ' (' in new_proj_disp else new_proj_disp
                self.view.project_var.set(new_proj_disp)
                self.load_project(new_proj_name)
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
        if self.project_model.current_project_name and self.project_model.exists(self.project_model.current_project_name):
            try:
                if self.view.files_canvas.winfo_height() > 1:
                    scroll_pos = self.view.files_canvas.yview()[0]
                    self.project_model.set_project_scroll_pos(self.project_model.current_project_name, scroll_pos)
                self.project_model.set_last_used_files(self.project_model.get_selected_files())
                self.project_model.save()
            except (AttributeError, Exception): pass
        
        self.view.clear_ui_for_loading()
        self.view.show_loading_placeholder()
        
        self.project_model.set_current_project(name)
        self.precomputed_prompt_cache.clear()
        
        last_files = [] if is_new_project else self.project_model.projects.get(name, {}).get("last_files", [])
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
        self.project_model.update_project(proj_name, proj_data)
        self.project_model.save()

    def update_global_settings(self, settings_data):
        self.settings_model.set('respect_gitignore', settings_data['respect_gitignore'])
        self.settings_model.set('reset_scroll_on_reset', settings_data['reset_scroll_on_reset'])
        self.settings_model.set("global_blacklist", settings_data['global_blacklist'])
        self.settings_model.set("global_keep", settings_data['global_keep'])
        self.settings_model.save()

    def handle_raw_template_update(self, new_data):
        self.settings_model.set("global_templates", new_data)
        self.settings_model.save()
        self.load_templates(force_refresh=True)
        if self.view:
            self.view.quick_copy_var.set("")

    # File & Item Management
    # ------------------------------
    def refresh_files(self, is_manual=False):
        if not self.project_model.current_project_name: return
        
        self.project_model.directory_tree_cache = None
        if self.view.files_canvas.winfo_height() > 1:
            scroll_pos = self.view.files_canvas.yview()[0]
            self.project_model.set_project_scroll_pos(self.project_model.current_project_name, scroll_pos)

        self.load_items_in_background(is_silent=not is_manual)

    # Selection & State Tracking
    # ------------------------------
    def toggle_select_all(self):
        # flush a pending search‑debounce run so that filtered_items is up‑to‑date
        try:
            if self.view.search_debounce_timer:
                self.view.after_cancel(self.view.search_debounce_timer)
                self.view.search_debounce_timer = None
                self.view.filter_and_display_items(scroll_to_top=False)
        except Exception:
            pass

        filtered_files = [i["path"] for i in self.project_model.get_filtered_items() if i["type"] == "file"]
        if not filtered_files: return
        current_selection = self.project_model.get_selected_files_set()
        filtered_files_set = set(filtered_files)
        
        is_all_selected = filtered_files_set.issubset(current_selection)

        if not is_all_selected:
            new_selection = current_selection.union(filtered_files_set)
        else:
            new_selection = current_selection.difference(filtered_files_set)

        self.project_model.set_selection(new_selection)
        self.view.sync_checkboxes_to_model()
        self.handle_file_selection_change()

    def reset_selection(self):
        to_uncheck = self.project_model.get_selected_files()
        search_was_active = self.view.file_search_var.get() != ""
        if not to_uncheck and not search_was_active: return

        self.view.reset_button_clicked = True

        self.project_model.set_selection(set())
        self.view.sync_checkboxes_to_model()
        self.handle_file_selection_change()

        if search_was_active:
            self.view.file_search_var.set("")
        else:
            if self.settings_model.get('reset_scroll_on_reset', True):
                self.view.files_canvas.yview_moveto(0.0)
            self.view.reset_button_clicked = False

    def reselect_history(self, files_to_select):
        self.project_model.set_selection(set(files_to_select))
        self.view.sync_checkboxes_to_model()
        self.handle_file_selection_change()

    # Generation & Output Logic
    # ------------------------------
    def generate_output(self, template_override=None): self._initiate_generation(template_override, to_clipboard=False)
    def generate_output_to_clipboard(self, template_override=None): self._initiate_generation(template_override, to_clipboard=True)

    def _initiate_generation(self, template_override, to_clipboard):
        proj_name = self.project_model.current_project_name
        if not proj_name: return show_warning_centered(self.view, "No Project Selected", "Please select a project first.")
        
        template_name = template_override if template_override is not None else self.view.template_var.get()
        template_content = self.settings_model.get_template_content(template_name)
        selected_files = self.project_model.get_selected_files()
        
        if not selected_files and "{{CLIPBOARD}}" not in template_content: return show_warning_centered(self.view, "Warning", "No files selected.")
        if len(selected_files) > self.project_model.max_files: return show_warning_centered(self.view, "Warning", f"Selected {len(selected_files)} files. Max is {self.project_model.max_files}.")
        if not self.project_model.is_project_path_valid(): return show_error_centered(self.view, "Error", "Project directory does not exist.")
        
        try: clipboard_content = self.view.clipboard_get()
        except Exception: clipboard_content = ""

        with self.is_precomputing:
            key = self.get_precompute_key(selected_files, template_name, clipboard_content)
            if key in self.precomputed_prompt_cache and not to_clipboard:
                prompt, total_chars, oversized, truncated = self.precomputed_prompt_cache[key]
                self.finalize_generation(prompt, selected_files, total_chars, oversized, truncated)
                return

        self.view.set_generation_state(True, to_clipboard)
        self.project_model.set_last_used_files(selected_files)
        if template_override is None: self.project_model.set_last_used_template(template_name)
        
        worker = self.generate_output_to_clipboard_worker if to_clipboard else self.generate_output_worker
        self.generation_pool.submit(worker, selected_files, template_name, clipboard_content)

    def get_precompute_key(self, selected_files, template_name, clipboard_content=""):
        h = hashlib.md5()
        if self.project_model.current_project_name:
            h.update(self.project_model.current_project_name.encode())
        proj_path = self.project_model.get_project_path(self.project_model.current_project_name)
        for fp in sorted(selected_files):
            h.update(fp.encode())
            full_path = os.path.join(proj_path, fp)
            try: mtime = os.stat(full_path).st_mtime_ns
            except OSError: mtime = 0
            h.update(str(mtime).encode())
        if "{{CLIPBOARD}}" in self.settings_model.get_template_content(template_name):
            h.update(clipboard_content.encode())
        h.update(template_name.encode())
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
        except Exception: logger.error("%s", traceback.format_exc()); show_error_centered(self.view, "Error", "Failed to open in editor.")

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

    def _precompute_worker(self):
        while not self._stop_event.is_set():
            self.precompute_request.wait()
            if self._stop_event.is_set(): break
            with self.is_precomputing:
                self.precompute_request.clear()
                if not self.project_model.current_project_name: continue
                selected_files = self.project_model.get_selected_files()
                template_name, clipboard_content = self.precompute_args
                if template_name is None: continue
                self.project_model.update_file_contents(selected_files)
                prompt, total_chars, oversized, truncated = self.project_model.simulate_final_prompt(selected_files, template_name, clipboard_content)
                key = self.get_precompute_key(selected_files, template_name, clipboard_content)
                self.precomputed_prompt_cache = {key: (prompt, total_chars, oversized, truncated)}

    def char_count_worker(self, template_name, clipboard_content, request_token):
        try:
            if not self.project_model.current_project_name: return
            selected_files = self.project_model.get_selected_files()
            self.project_model.update_file_contents(selected_files)
            prompt, total_selection_chars, _, _ = self.project_model.simulate_final_prompt(selected_files, template_name, clipboard_content)
            prompt_chars = len(prompt)
            if self.char_count_token == request_token: self.queue.put(('char_count_done', (len(selected_files), prompt_chars, total_selection_chars)))
        except Exception as e:
            logger.error("Character count worker failed: %s", e, exc_info=True)
            if self.char_count_token == request_token: self.queue.put(('char_count_done', (len(selected_files), -1, -1)))

    def generate_output_worker(self, selected_files, template_name, clipboard_content):
        try:
            self.project_model.update_file_contents(selected_files)
            prompt, total_chars, oversized, truncated = self.project_model.simulate_final_prompt(selected_files, template_name, clipboard_content)
            self.queue.put(('save_and_open', (prompt, selected_files, total_chars, oversized, truncated)))
        except Exception as e:
            logger.error("Error generating output: %s", e, exc_info=True)
            self.queue.put(('error', "Error generating output."))

    def generate_output_to_clipboard_worker(self, selected_files, template_name, clipboard_content):
        try:
            self.project_model.update_file_contents(selected_files)
            prompt, total_chars, oversized, truncated = self.project_model.simulate_final_prompt(selected_files, template_name, clipboard_content)
            self.queue.put(('copy_and_save_silently', (prompt, selected_files, total_chars, oversized, truncated)))
        except Exception as e:
            logger.error("Error generating for clipboard: %s", e, exc_info=True)
            self.queue.put(('error', "Error generating for clipboard."))

    def _quick_action_worker(self, val, clip_in):
        project_name = self.project_model.current_project_name or "ClipboardAction"
        op_map = {
            "Truncate Between '---'": self.process_truncate_format,
            "Replace \"**\"": lambda t: (self._extended_text_cleaning(t), "Cleaned text and copied"),
            "Gemini Whitespace Fix": lambda t: (t.replace('\u00A0', ' '), "Fixed whitespace and copied"),
            "Remove Duplicates": lambda t: ('\n'.join(dict.fromkeys(t.rstrip('\n').split('\n'))), "Removed duplicates and copied"),
            "Sort Alphabetically": lambda t: ('\n'.join(sorted(t.rstrip('\n').split('\n'))), "Sorted alphabetically and copied"),
            "Sort by Length": lambda t: ('\n'.join(sorted(t.rstrip('\n').split('\n'), key=len)), "Sorted by length and copied"),
            "Escape Text": lambda t: (t.rstrip('\n').encode('unicode_escape').decode('ascii', 'ignore'), "Escaped text and copied"),
            "Unescape Text": lambda t: (codecs.decode(t.rstrip('\n'), 'unicode_escape'), "Unescaped text and copied")
        }
        try:
            if val in op_map:
                new_clip, msg = op_map[val](clip_in)
                new_clip = new_clip.strip()
                self.project_model.save_output_silently(new_clip, project_name)
                self.queue.put(('quick_action_done', (new_clip, msg)))
            elif self.settings_model.is_template(val) and "{{CLIPBOARD}}" in self.settings_model.get_template_content(val):
                content = self.settings_model.get_template_content(val).replace("{{CLIPBOARD}}", clip_in).strip()
                self.project_model.save_output_silently(content, project_name)
                self.queue.put(('quick_action_done', (content, "Copied to clipboard")))
        except Exception as e:
            logger.error("Quick action '%s' failed: %s", val, e)
            self.queue.put(('set_status_temporary', ("Operation failed!", 3000)))

    # Event Handlers
    # ------------------------------
    def on_project_selected(self, _=None):
        disp = self.view.project_var.get()
        if not disp: self.view.clear_project_view(); return
        name = disp.split(' (')[0] if ' (' in disp else disp
        self.load_project(name)

    def on_template_selected(self, _=None):
        if self.project_model.current_project_name:
            self.project_model.set_last_used_template(self.view.template_var.get())
        self.request_precomputation()

    def update_file_selection(self, file_path, var_value):
        self.project_model.update_selection(file_path, var_value)
        if var_value: self.project_model.increment_click_count(file_path)

    def handle_file_selection_change(self, *a):
        if self.project_model.is_bulk_updating(): return
        selected_files = self.project_model.get_selected_files()
        
        self.view.update_selection_count_label(len(selected_files), "Calculating...", "Calculating...")
        self.char_count_token += 1
        try:
            clipboard_content = self.view.clipboard_get()
        except Exception:
            clipboard_content = ""
        template_name = self.view.template_var.get()
        self.char_count_executor.submit(self.char_count_worker, template_name, clipboard_content, self.char_count_token)
        
        self.view.refresh_selected_files_list(selected_files)
        self.view.update_select_all_button()
        self.request_precomputation()

    def on_project_dropdown_search(self, event):
        now = time.time()
        if now - self.project_search_last_key_time > 1.0: self.project_search_buffer = ""
        self.project_search_last_key_time = now
        if event.keysym == "BackSpace":
            if self.project_search_buffer: self.project_search_buffer = self.project_search_buffer[:-1]
        elif (len(event.char) == 1 and event.char.isprintable()) or (len(event.keysym) == 1 and event.keysym.isprintable()):
            self.project_search_buffer += (event.char if event.char else event.keysym).lower()
        elif event.keysym == "Escape": self.project_search_buffer = ""; return
        else: return
        if not self.project_search_buffer: return
        self.view.find_and_select_project(self.project_search_buffer, event)
        
    def on_no_project_selected(self):
        show_warning_centered(self.view, "No Project Selected", "Please select a project first.")

    def on_quick_copy_selected(self, _=None):
        val = self.view.quick_copy_var.get()
        self.view.quick_copy_dropdown.set("")
        if not val or val.startswith("-- "): return
        self.settings_model.record_quick_action_usage(val)
        self.settings_model.save()
        self._execute_quick_action(val)
        self.view.update_quick_action_buttons()

    def _execute_quick_action(self, val):
        if not val or val.startswith("-- "): return
        try: clip_in = self.view.clipboard_get()
        except Exception: clip_in = ""
        if self.quick_action_pool._work_queue.qsize() < 20:
            self.quick_action_pool.submit(self._quick_action_worker, val, clip_in)
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

    # Queue Processing & UI Updates
    # ------------------------------
    def process_queue(self):
        try:
            while True:
                task, data = self.queue.get_nowait()
                if task == 'save_and_open': self.finalize_generation(data[0], data[1], data[2], data[3], data[4])
                elif task == 'copy_and_save_silently': self.finalize_clipboard_generation(data[0], data[1], data[2], data[3], data[4])
                elif task == 'error':
                    self.view.set_generation_state(False)
                    show_error_centered(self.view, "Error", data)
                elif task == 'load_items_done':
                    status, result, is_new_project = data
                    if status == "error":
                        show_error_centered(self.view, "Invalid Path", "Project directory does not exist.")
                        self.project_model.all_items = []
                        self.project_model.filtered_items = []
                    else:
                        found_items, limit_exceeded = result
                        existing_files = {item['path'] for item in found_items if item['type'] == 'file'}
                        current_selection = self.project_model.get_selected_files_set()
                        removed_files = current_selection - existing_files

                        if removed_files:
                            self.project_model.set_selection(current_selection - removed_files)
                            logger.info(f"Silently unselected {len(removed_files)} files that no longer exist.")
                            if not self.view.is_silent_refresh:
                                self.view.set_status_temporary(f"Project files updated; {len(removed_files)} missing file(s) unselected.")

                        self.project_model.all_items = found_items
                        self.project_model.filtered_items = found_items
                        self.project_model._initialize_file_data(found_items)
                        threading.Thread(target=self.project_model._load_file_contents_worker, args=(self.queue,), daemon=True).start()
                        self.view.load_items_result((limit_exceeded,), is_new_project)
                    self.view.status_label.config(text="Ready")
                elif task == 'auto_bl': self.on_auto_blacklist_done(data[0], data[1])
                elif task == 'char_count_done':
                    file_count, prompt_chars, file_chars = data
                    self.view.update_selection_count_label(
                        file_count,
                        format_german_thousand_sep(prompt_chars) if prompt_chars >= 0 else "Error",
                        format_german_thousand_sep(file_chars) if file_chars >= 0 else "Error"
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
        except queue.Empty: pass
        if self.view and self.view.winfo_exists(): self.view.after(50, self.process_queue)

    def finalize_generation(self, output, selection, char_count, oversized, truncated):
        self.project_model.update_project_usage()
        self.update_projects_list()
        self.project_model.save_and_open_output(output)
        self.view.set_generation_state(False)
        self.settings_model.add_history_selection(selection, self.project_model.current_project_name, char_count)
        self.settings_model.save()
        self._check_and_warn_for_omissions(oversized, truncated)

    def finalize_clipboard_generation(self, output, selection, char_count, oversized, truncated):
        self.view.update_clipboard(output)
        self.view.set_status_temporary("Copied to clipboard.")
        self.project_model.save_output_silently(output, self.project_model.current_project_name)
        self.view.set_generation_state(False)
        self.settings_model.add_history_selection(selection, self.project_model.current_project_name, char_count)
        self.settings_model.save()
        self._check_and_warn_for_omissions(oversized, truncated)

    def on_auto_blacklist_done(self, proj_name, dirs):
        self.project_model.add_to_blacklist(proj_name, dirs)
        if self.project_model.current_project_name == proj_name:
            show_warning_centered(self.view, "Auto-Blacklisted", f"Directories with >50 files were blacklisted and added to project settings:\n\n{', '.join(dirs)}")

    # Internal Helpers
    # ------------------------------
    def _set_project_file_handler(self, project_name): set_project_file_handler(project_name)
    def request_precomputation(self):
        if not self.view or not self.view.winfo_exists(): return
        template_name = self.view.template_var.get()
        try:
            clipboard_content = self.view.clipboard_get()
        except Exception:
            clipboard_content = ""
        self.precompute_args = (template_name, clipboard_content)
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
            if in_fenced_code or s.startswith('    '):
                output_lines.append(s); continue
            parts = re.split(r'(`[^`]*`)', s)
            processed_line = "".join([part if i % 2 == 1 else part.replace('**', '') for i, part in enumerate(parts)])
            output_lines.append(processed_line)
        return '\n'.join(output_lines)

    def process_truncate_format(self, text):
        text = unify_line_endings(text)
        text = self._extended_text_cleaning(text)
        lines = text.split('\n')
        delim_idx = [i for i, l in enumerate(lines) if re.match(r'^\s*---\s*$', l)]
        between = False
        if len(delim_idx) >= 2:
            between = True
            lines = lines[delim_idx[0] + 1:delim_idx[-1]]
        while lines and not lines[0].strip(): lines.pop(0)
        while lines and not lines[-1].strip(): lines.pop()
        final_text = '\n'.join(lines)
        char_cnt = len(final_text)
        notification = f"✅ Copied {char_cnt} chars (between delimiters)" if between else f"ℹ️ {'Only one' if len(delim_idx) == 1 else 'No'} ‘---’ found – copied whole document ({char_cnt} chars)."
        return final_text, notification

    def _check_and_warn_for_omissions(self, oversized, truncated):
        warnings = []
        if oversized:
            warnings.append(f"The following files were SKIPPED as they exceed the max file size ({self.project_model.max_file_size/1000:g} kB):\n- " + "\n- ".join(oversized))
        if truncated:
            warnings.append(f"The following files were TRUNCATED as the prompt exceeds the max content size ({self.project_model.max_content_size/1000000:g} MB):\n- " + "\n- ".join(truncated))
        if warnings:
            show_warning_centered(self.view, "Prompt Content Omissions", "\n\n".join(warnings))