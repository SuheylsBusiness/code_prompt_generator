# File: code_prompt_generator/app/views/main_view.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
import os, time, platform
from app.config import get_logger
from app.utils.path_utils import resource_path
from app.utils.system_utils import get_relative_time_str, suspend_var_traces
from app.utils.ui_helpers import format_german_thousand_sep, show_warning_centered, handle_mousewheel
from app.views.widgets.scrolled_frame import ScrolledFrame
from app.views.dialogs.settings_dialog import SettingsDialog
from app.views.dialogs.templates_dialog import TemplatesDialog
from app.views.dialogs.history_selection_dialog import HistorySelectionDialog
from app.views.dialogs.output_files_dialog import OutputFilesDialog
from app.views.dialogs.text_editor_dialog import TextEditorDialog

logger = get_logger(__name__)

# Main Application View
# ------------------------------
class MainView(tk.Tk):
    # Initialization & State
    # ------------------------------
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.title(f"Code Prompt Generator - PID: {os.getpid()}")
        self.initialize_styles()
        self.initialize_state()
        self.create_layout()
        self.protocol("WM_DELETE_WINDOW", self.controller.on_closing)

    def initialize_styles(self):
        self.style = ttk.Style(self)
        try: self.style.theme_use('vista')
        except tk.TclError:
            try: self.style.theme_use(self.style.theme_names()[0])
            except Exception as e: logger.warning("Failed to set a theme: %s", e)
        self.style.configure('.', font=('Segoe UI', 10), background='#F3F3F3')
        for s in ['TFrame', 'TLabel', 'TCheckbutton', 'Modern.TCheckbutton', 'TRadiobutton']: self.style.configure(s, background='#F3F3F3')
        for s in ['ProjectOps.TLabelframe', 'TemplateOps.TLabelframe', 'FilesFrame.TLabelframe', 'SelectedFiles.TLabelframe']: self.style.configure(s, background='#F3F3F3', padding=10, foreground='#444444')
        self.style.configure('TButton', foreground='black', background='#F0F0F0', padding=6, font=('Segoe UI',10,'normal'))
        self.style.map('TButton', foreground=[('disabled','#7A7A7A'),('active','black')], background=[('active','#E0E0E0'),('disabled','#F0F0F0')])
        self.style.configure('RemoveFile.TButton', anchor='center', padding=(2,1))
        self.style.configure('Toolbutton', padding=1)
        italic_font = tkfont.Font(family="Segoe UI", size=9, slant="italic")
        self.style.configure("Italic.TLabel", font=italic_font, background='#F3F3F3')
        self.icon_path = resource_path('app_icon.ico')
        if os.path.exists(self.icon_path):
            try: self.iconbitmap(self.icon_path)
            except tk.TclError: logger.warning("Could not set .ico file.")

    def initialize_state(self):
        self.file_vars = {}
        self.row_frames = {}
        self.file_labels = {}
        self.reset_button_clicked = False
        self.is_silent_refresh = False
        self.scroll_restore_job = None
        self.search_debounce_timer = None
        self.checkbox_toggle_timer = None
        self.skip_search_scroll = False
        self._project_listbox = None
        self.selected_files_sort_mode = tk.StringVar(value='default')

    # GUI Layout Creation
    # ------------------------------
    def create_layout(self):
        self.top_frame = ttk.Frame(self); self.top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)
        self.create_top_widgets(self.top_frame)
        main_area_frame = ttk.Frame(self)
        main_area_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(5,0))
        self.file_frame = ttk.LabelFrame(main_area_frame, text="Project Files", style='FilesFrame.TLabelframe')
        self.file_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.create_file_widgets(self.file_frame)
        self.selected_files_frame = ttk.LabelFrame(main_area_frame, text="Selected Files View", style='SelectedFiles.TLabelframe')
        self.selected_files_frame.pack(side=tk.RIGHT, fill=tk.Y, expand=False)
        self.create_selected_files_widgets(self.selected_files_frame)
        self.control_frame = ttk.Frame(self); self.control_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=5)
        self.create_bottom_widgets(self.control_frame)

    def create_top_widgets(self, container):
        pa = ttk.LabelFrame(container, text="Project Operations", style='ProjectOps.TLabelframe')
        pa.pack(side=tk.LEFT, fill=tk.Y, padx=(0,5))
        ttk.Label(pa, text="Select Project:").pack(anchor='w', pady=(0,2))
        self.project_var = tk.StringVar()
        self.project_dropdown = ttk.Combobox(pa, textvariable=self.project_var, state='readonly', width=20, takefocus=True)
        self.project_dropdown.pack(anchor='w', pady=(0,5))
        self.project_dropdown.bind("<KeyPress>", self.controller.on_project_dropdown_search)
        self.project_dropdown.configure(postcommand=self.bind_project_listbox)
        self.project_dropdown.bind("<<ComboboxSelected>>", self.controller.on_project_selected)
        of = ttk.Frame(pa); of.pack(anchor='w', pady=(5,0))
        ttk.Button(of, text="Add Project", command=self.controller.add_project, takefocus=True).pack(side=tk.LEFT)
        ttk.Button(of, text="Open Folder", command=self.controller.open_project_folder, takefocus=True).pack(side=tk.LEFT, padx=5)
        ttk.Button(of, text="Remove Project", command=self.controller.remove_project, takefocus=True).pack(side=tk.LEFT, padx=5)

        tf = ttk.LabelFrame(container, text="Template", style='TemplateOps.TLabelframe'); tf.pack(side=tk.RIGHT, fill=tk.Y, padx=(5,0))
        template_frame_inner = ttk.Frame(tf); template_frame_inner.pack(anchor='w')
        ttk.Label(template_frame_inner, text="Select Template:").pack(anchor='w', pady=(0,2))
        self.template_var = tk.StringVar(); self.template_var.trace_add('write', lambda *a: self.controller.request_precomputation())
        self.template_dropdown = ttk.Combobox(template_frame_inner, textvariable=self.template_var, state='readonly', width=20, takefocus=True); self.template_dropdown.pack(anchor='w', pady=(0,5)); self.template_dropdown.bind("<<ComboboxSelected>>", self.controller.on_template_selected)
        template_buttons_frame = ttk.Frame(tf); template_buttons_frame.pack(anchor='w', pady=5)
        self.manage_templates_btn = ttk.Button(template_buttons_frame, text="Manage Templates", command=self.open_templates_dialog, takefocus=True); self.manage_templates_btn.pack(side=tk.LEFT)
        self.reset_template_btn = ttk.Button(template_buttons_frame, text="Reset to Default", command=self.reset_template_to_default, takefocus=True, state=tk.DISABLED); self.reset_template_btn.pack(side=tk.LEFT, padx=5)

        qf = ttk.LabelFrame(container, text="Quick Action", style='TemplateOps.TLabelframe'); qf.pack(side=tk.RIGHT, fill=tk.BOTH, padx=5, expand=True)
        self.quick_copy_var = tk.StringVar()
        self.quick_copy_dropdown = ttk.Combobox(qf, textvariable=self.quick_copy_var, state='readonly', width=20, takefocus=True); self.quick_copy_dropdown.pack(anchor='w', pady=(0,5), fill=tk.X)
        self.quick_copy_dropdown.bind("<<ComboboxSelected>>", self.controller.on_quick_copy_selected)
        quick_buttons_frame = ttk.Frame(qf); quick_buttons_frame.pack(anchor='w', pady=(5,0), fill=tk.X, expand=True)
        self.most_frequent_button = ttk.Button(quick_buttons_frame, text="Most Frequent:\n(N/A)", command=self.controller.execute_most_frequent_quick_action)
        self.most_frequent_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        self.most_recent_button = ttk.Button(quick_buttons_frame, text="Most Recent:\n(N/A)", command=self.controller.execute_most_recent_quick_action)
        self.most_recent_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 0))

    def create_file_widgets(self, container):
        sf = ttk.Frame(container); sf.pack(anchor='w', padx=5, pady=(5,2))
        ttk.Label(sf, text="Search:").pack(side=tk.LEFT, padx=(0,5))
        self.file_search_var = tk.StringVar(); self.file_search_var.trace_add("write", self.on_search_changed)
        ttk.Entry(sf, textvariable=self.file_search_var, width=25, takefocus=True).pack(side=tk.LEFT)
        ttk.Button(sf, text="✕", command=lambda: self.file_search_var.set(""), style='Toolbutton').pack(side=tk.LEFT, padx=(5,0))

        tf = ttk.Frame(container); tf.pack(fill=tk.X, padx=5, pady=(5,2))
        self.select_all_button = ttk.Button(tf, text="Select All", command=self.controller.toggle_select_all, takefocus=True); self.select_all_button.pack(side=tk.LEFT)
        self.reset_button = ttk.Button(tf, text="Reset", command=self.controller.reset_selection, takefocus=True); self.reset_button.pack(side=tk.LEFT, padx=5)
        self.file_selected_label = ttk.Label(tf, text="Files selected: 0 / 0 (Chars: 0)", width=45); self.file_selected_label.pack(side=tk.LEFT, padx=10)
        self.view_outputs_button = ttk.Button(tf, text="View Outputs", command=self.open_output_files, takefocus=True); self.view_outputs_button.pack(side=tk.RIGHT)
        self.history_button = ttk.Button(tf, text="History Selection", command=self.open_history_selection, takefocus=True); self.history_button.pack(side=tk.RIGHT, padx=5)

        self.files_scrolled_frame = ScrolledFrame(container, side=tk.TOP, expand=True, fill=tk.BOTH, padx=5, pady=5); self.files_canvas = self.files_scrolled_frame.canvas; self.inner_frame = self.files_scrolled_frame.inner_frame

    def create_selected_files_widgets(self, container):
        sort_frame = ttk.Frame(container); sort_frame.pack(fill=tk.X, padx=5, pady=0)
        ttk.Label(sort_frame, text="Sort by:").pack(side=tk.LEFT)
        ttk.Radiobutton(sort_frame, text="Default", variable=self.selected_files_sort_mode, value="default", command=self.on_sort_mode_changed).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(sort_frame, text="Char Count", variable=self.selected_files_sort_mode, value="char_count", command=self.on_sort_mode_changed).pack(side=tk.LEFT)
        self.selected_files_scrolled_frame = ScrolledFrame(container, side=tk.TOP, expand=True, fill=tk.BOTH, padx=5, pady=5); self.selected_files_canvas = self.selected_files_scrolled_frame.canvas; self.selected_files_inner = self.selected_files_scrolled_frame.inner_frame
        container.pack_propagate(False)
        container.config(width=250)

    def create_bottom_widgets(self, container):
        gen_frame = ttk.Frame(container); gen_frame.pack(side=tk.LEFT, padx=5)
        self.generate_button = ttk.Button(gen_frame, text="Generate", width=12, command=self.controller.generate_output, takefocus=True); self.generate_button.pack(side=tk.LEFT)
        ttk.Label(gen_frame, text="MD:").pack(side=tk.LEFT, padx=(10, 0)); self.generate_menu_button_md = ttk.Button(gen_frame, text="▼", width=2, command=self.show_quick_generate_menu); self.generate_menu_button_md.pack(side=tk.LEFT)
        ttk.Label(gen_frame, text="CB:").pack(side=tk.LEFT, padx=(10, 0)); self.generate_menu_button_cb = ttk.Button(gen_frame, text="▼", width=2, command=self.show_quick_generate_menu_cb); self.generate_menu_button_cb.pack(side=tk.LEFT)

        self.refresh_button = ttk.Button(container, text="Refresh Files", width=12, command=lambda: self.controller.refresh_files(is_manual=True), takefocus=True); self.refresh_button.pack(side=tk.LEFT, padx=5)
        self.status_label = ttk.Label(container, text="Ready"); self.status_label.pack(side=tk.RIGHT, padx=10)
        self.text_editor_button = ttk.Button(container, text="Open Text Editor", command=self.open_text_editor, takefocus=True); self.text_editor_button.pack(side=tk.RIGHT)
        self.settings_button = ttk.Button(container, text="Settings", command=self.open_settings_dialog, takefocus=True); self.settings_button.pack(side=tk.RIGHT, padx=5)

    # UI Update Methods
    # ------------------------------
    def restore_window_geometry(self):
        geom = self.controller.settings_model.get('window_geometry')
        self.geometry(geom if geom else "1200x800")

    def set_status_temporary(self, msg, duration=2000):
        self.status_label.config(text=msg)
        self.after(duration, lambda: self.status_label.config(text="Ready"))

    def set_status_loading(self): self.status_label.config(text="Loading...")
    def set_generation_state(self, is_generating, to_clipboard=False):
        state = tk.DISABLED if is_generating else tk.NORMAL
        self.generate_button.config(state=state)
        self.generate_menu_button_md.config(state=state)
        self.generate_menu_button_cb.config(state=state)
        if is_generating: self.status_label.config(text=f"Generating{' for clipboard' if to_clipboard else ''}...")
        else: self.status_label.config(text="Ready")

    def update_selection_count_label(self, file_count, char_count_text):
        total_files = len([i for i in self.controller.project_model.all_items if i["type"] == "file"])
        self.file_selected_label.config(text=f"Files selected: {file_count} / {total_files} (Total Chars: {char_count_text})")

    def schedule_scroll_restore(self, pos):
        if self.scroll_restore_job: self.after_cancel(self.scroll_restore_job)
        self.scroll_restore_job = self.after(50, lambda p=pos: (self.files_canvas.yview_moveto(p), setattr(self, "scroll_restore_job", None)))

    def filter_and_display_items(self, scroll_to_top=False):
        if self.reset_button_clicked and not self.controller.settings_model.get('reset_scroll_on_reset', True): scroll_to_top = False
        for w in self.inner_frame.winfo_children(): w.destroy()
        self.row_frames.clear(); self.file_labels.clear()
        
        query = self.file_search_var.get().strip().lower()
        filtered = [it for it in self.controller.project_model.all_items if query in it["path"].lower()] if query else self.controller.project_model.all_items
        self.controller.project_model.set_filtered_items(filtered)
        
        for item in filtered:
            rf = tk.Frame(self.inner_frame); rf.pack(fill=tk.X, anchor='w')
            self.files_scrolled_frame.bind_mousewheel_to_widget(rf)
            indent = (4 + item["level"] * 10, 2)
            if item["type"] == "dir":
                rf.config(bg='#F3F3F3'); lbl = tk.Label(rf, text=f"{os.path.basename(item['path'].rstrip('/'))}/", bg='#F3F3F3', fg='#0066AA')
                lbl.pack(side=tk.LEFT, padx=indent); self.files_scrolled_frame.bind_mousewheel_to_widget(lbl)
            else:
                path = item["path"]; self.row_frames[path] = rf; self.update_row_color(path)
                chk = ttk.Checkbutton(rf, variable=self.file_vars.get(path), style='Modern.TCheckbutton'); chk.pack(side=tk.LEFT, padx=indent); self.files_scrolled_frame.bind_mousewheel_to_widget(chk)
                char_count = format_german_thousand_sep(self.controller.project_model.file_char_counts.get(path, 0))
                lbl = tk.Label(rf, text=f"{os.path.basename(path)} [{char_count}]", bg=rf["bg"]); lbl.pack(side=tk.LEFT, padx=2)
                lbl.bind("<Button-1>", lambda e, p=path: self.file_vars.get(p).set(not self.file_vars.get(p).get()))
                self.files_scrolled_frame.bind_mousewheel_to_widget(lbl); self.file_labels[path] = lbl
        
        self.controller.handle_file_selection_change()
        
        if scroll_to_top or (self.reset_button_clicked and self.controller.settings_model.get('reset_scroll_on_reset', True)): self.schedule_scroll_restore(0.0)
        else: self.schedule_scroll_restore(self.controller.project_model.project_tree_scroll_pos)
        
        self.reset_button_clicked = False; self.is_silent_refresh = False

    def clear_project_view(self):
        self.controller.project_model.set_items([]); self.file_vars.clear()
        for w in self.inner_frame.winfo_children(): w.destroy()
        for w in self.selected_files_inner.winfo_children(): w.destroy()
        self.controller.handle_file_selection_change()

    def update_project_list(self, projects_data):
        cur_disp = self.project_var.get()
        cur_name = cur_disp.split(" (")[0] if " (" in cur_disp else cur_disp
        sorted_display_values = [f"{n} ({get_relative_time_str(lu)})" if lu > 0 else n for n, lu, uc in projects_data]
        self.project_dropdown["values"] = sorted_display_values
        match = next((d for d in sorted_display_values if d == cur_name or d.startswith(f"{cur_name} (")), None)
        if match: self.project_dropdown.set(match)
        elif sorted_display_values: self.project_dropdown.set(sorted_display_values[0])
        else: self.project_var.set("")
        if sorted_display_values: self.project_dropdown.configure(width=max(max((len(d) for d in sorted_display_values), default=20), 20))

    def get_display_name_for_project(self, name):
        projects_data = self.controller.project_model.get_sorted_projects_for_display()
        for proj_name, last_usage, _ in projects_data:
            if proj_name == name:
                return f"{proj_name} ({get_relative_time_str(last_usage)})" if last_usage > 0 else proj_name
        return name

    def update_template_dropdowns(self, force_refresh):
        display_templates = self.controller.settings_model.get_display_templates()
        if not force_refresh and list(self.template_dropdown['values']) == display_templates: return
        self.template_dropdown['values'] = display_templates
        if display_templates: self.template_dropdown.config(height=min(len(display_templates), 15), width=max(max((len(x) for x in display_templates), default=0)+2, 20))

        qc_menu_items = self.controller.settings_model.get_quick_copy_templates()
        editor_tools = ["Replace \"**\"", "Gemini Whitespace Fix", "Remove Duplicates", "Sort Alphabetically", "Sort by Length", "Escape Text", "Unescape Text"]
        qc_menu = []
        if qc_menu_items: qc_menu.extend(["-- Template Content --"] + qc_menu_items)
        qc_menu.extend(["-- Text Editor Tools --", "Truncate Between '---'"] + editor_tools)
        
        self.quick_copy_dropdown.config(values=qc_menu, height=min(len(qc_menu), 15))
        if qc_menu: self.quick_copy_dropdown.config(width=max(max((len(x) for x in qc_menu), default=0)+2, 20))
        self.quick_copy_var.set("")

        default_to_set = self.controller.settings_model.get("default_template_name")
        if default_to_set and default_to_set in display_templates: self.template_var.set(default_to_set)
        elif display_templates: self.template_var.set(display_templates[0])
        else: self.template_var.set("")

    def refresh_selected_files_list(self, selected):
        for w in self.selected_files_inner.winfo_children(): w.destroy()
        if self.selected_files_sort_mode.get() == 'char_count':
            selected = sorted(selected, key=lambda f: self.controller.project_model.file_char_counts.get(f, 0), reverse=True)
        longest_lbl_text = ""
        for i, f in enumerate(selected):
            lbl_text = f"{f} [{format_german_thousand_sep(self.controller.project_model.file_char_counts.get(f, 0))}]"
            if len(lbl_text) > len(longest_lbl_text): longest_lbl_text = lbl_text
            rf = ttk.Frame(self.selected_files_inner); rf.pack(fill=tk.X, anchor='w')
            self.selected_files_scrolled_frame.bind_mousewheel_to_widget(rf)
            xb = ttk.Button(rf, text="x", width=1, style='RemoveFile.TButton', command=lambda ff=f: self.file_vars.get(ff).set(False))
            xb.pack(side=tk.LEFT, padx=(0,5)); self.selected_files_scrolled_frame.bind_mousewheel_to_widget(xb)
            lbl = ttk.Label(rf, text=lbl_text, cursor="hand2"); lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
            lbl.bind("<Button-1>", lambda e, ff=f: self.on_selected_file_clicked(ff)); self.selected_files_scrolled_frame.bind_mousewheel_to_widget(lbl)
        if longest_lbl_text:
            try:
                font = tkfont.nametofont("TkDefaultFont")
                new_width = font.measure(longest_lbl_text) + 40
                self.selected_files_frame.config(width=new_width)
            except tk.TclError: pass
        else:
            self.selected_files_frame.config(width=250)
        self.selected_files_canvas.yview_moveto(0)

    def update_select_all_button(self):
        filtered_files = self.controller.project_model.get_filtered_items()
        file_paths = {x["path"] for x in filtered_files if x["type"] == "file"}
        if file_paths:
            is_all_selected = file_paths.issubset(self.controller.project_model.selected_paths)
            self.select_all_button.config(text="Unselect All" if is_all_selected else "Select All")
        else:
            self.select_all_button.config(text="Select All")

    def update_row_color(self, p):
        if p not in self.row_frames: return
        proj = self.controller.project_model.projects.get(self.controller.project_model.current_project_name, {})
        ratio = min(proj.get("click_counts", {}).get(p, 0) / 100, 1.0)
        nr, ng, nb = int(243 + (206-243)*ratio), int(243 + (230-243)*ratio), int(243 + (255-243)*ratio)
        hexcolor = f"#{nr:02x}{ng:02x}{nb:02x}"
        self.row_frames[p].config(bg=hexcolor)
        for w in self.row_frames[p].winfo_children():
            if isinstance(w, tk.Label): w.config(bg=hexcolor)

    def update_file_char_counts(self):
        for p, lbl in self.file_labels.items():
            if p in self.controller.project_model.file_char_counts and lbl.winfo_exists():
                lbl.config(text=f"{os.path.basename(p)} [{format_german_thousand_sep(self.controller.project_model.file_char_counts.get(p,0))}]")

    def update_quick_action_buttons(self):
        frequent_action = self.controller.get_most_frequent_action()
        recent_action = self.controller.get_most_recent_action()
        f_text = frequent_action or "(N/A)"
        r_text = recent_action or "(N/A)"
        # Note: Italicizing part of a ttk Button's text is not possible. The colon is added as requested.
        self.most_frequent_button.config(text=f"Most Frequent:\n{f_text}")
        self.most_recent_button.config(text=f"Most Recent:\n{r_text}")

    # Event Handlers
    # ------------------------------
    def on_checkbox_toggled(self, file_path):
        if self.controller.project_model.is_bulk_updating(): return
        self.update_row_color(file_path)
        self.controller.update_file_selection(file_path, self.file_vars[file_path].get())
        if self.checkbox_toggle_timer: self.after_cancel(self.checkbox_toggle_timer)
        self.checkbox_toggle_timer = self.after(10, self.controller.handle_file_selection_change)

    def on_search_changed(self, *args):
        if self.search_debounce_timer: self.after_cancel(self.search_debounce_timer)
        stt = not self.skip_search_scroll; self.skip_search_scroll = False
        self.search_debounce_timer = self.after(200, lambda top=stt: self.filter_and_display_items(scroll_to_top=top))

    def on_selected_file_clicked(self, f_path): self.update_clipboard(f_path, "Copied path to clipboard")
    def on_sort_mode_changed(self): self.refresh_selected_files_list(self.controller.project_model.get_selected_files())

    def find_and_select_project(self, buffer, event):
        values = list(self.project_dropdown["values"])
        match_val = next((v for v in values if v.split(" (")[0].lower().startswith(buffer)), None)
        if not match_val: return
        idx = values.index(match_val)
        
        lb = getattr(self, "_project_listbox", None)
        if lb and lb.winfo_exists():
            lb.selection_clear(0, tk.END); lb.selection_set(idx); lb.activate(idx); lb.see(idx)
            self.project_dropdown.set(match_val)
            self.project_dropdown.icursor(tk.END)
            if event.widget is lb: return "break"
        
        self.project_var.set(match_val)
        self.project_dropdown.event_generate("<<ComboboxSelected>>")

    # Dialog Openers
    # ------------------------------
    def open_settings_dialog(self):
        if self.controller.project_model.current_project_name: SettingsDialog(self, self.controller)
        else: self.controller.on_no_project_selected()
        
    def open_templates_dialog(self):
        if self.controller.project_model.current_project_name:
            dialog = TemplatesDialog(self, self.controller)
            self.wait_window(dialog)
            self.controller.load_templates(force_refresh=True)
        else:
            self.controller.on_no_project_selected()

    def open_history_selection(self):
        if self.controller.project_model.current_project_name: HistorySelectionDialog(self, self.controller)
        else: self.controller.on_no_project_selected()
        
    def open_output_files(self): OutputFilesDialog(self, self.controller)
    def open_text_editor(self): TextEditorDialog(self, self.controller, initial_text="")

    def show_quick_generate_menu(self): self._show_quick_menu(self.generate_menu_button_md, self.controller.generate_output)
    def show_quick_generate_menu_cb(self): self._show_quick_menu(self.generate_menu_button_cb, self.controller.generate_output_to_clipboard)

    def _show_quick_menu(self, button, command_func):
        quick_templates = self.controller.settings_model.get_display_templates()
        if not quick_templates: return
        menu = tk.Menu(self, tearoff=0)
        for tpl in quick_templates: menu.add_command(label=tpl, command=lambda t=tpl: command_func(template_override=t))
        menu.post(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())

    def update_default_template_button(self): self.reset_template_btn.config(state=tk.NORMAL if self.controller.settings_model.get("default_template_name") else tk.DISABLED)
    def reset_template_to_default(self):
        default_name = self.controller.settings_model.get("default_template_name")
        if default_name and default_name in self.template_dropdown['values']: self.template_var.set(default_name)

    def bind_project_listbox(self):
        try:
            popdown_path = self.tk.call("ttk::combobox::PopdownWindow", self.project_dropdown)
            popdown_widget = self.nametowidget(popdown_path)
            def _find_listbox(widget):
                if isinstance(widget, tk.Listbox): return widget
                for child in widget.winfo_children():
                    if (result := _find_listbox(child)) is not None: return result
                return None
            if (listbox := _find_listbox(popdown_widget)) is not None:
                self._project_listbox = listbox
                listbox.bind("<KeyPress>", self.controller.on_project_dropdown_search, add="+")
        except Exception as e: logger.debug("bind_project_listbox: %s", e, exc_info=False)

    # Queue Processing & Item Loading
    # ------------------------------
    def load_items_result(self, data, is_new_project):
        limit_exceeded, = data
        if limit_exceeded: show_warning_centered(self, "File Limit Exceeded", f"Only the first {self.controller.project_model.max_files} files are loaded.")
        
        self.file_vars.clear()
        
        selected_paths = self.controller.project_model.selected_paths
        for it in self.controller.project_model.all_items:
            if it["type"] == "file":
                path = it["path"]
                self.file_vars[path] = tk.BooleanVar(value=(path in selected_paths))
                self.file_vars[path].trace_add('write', lambda n,i,m,p=path: self.on_checkbox_toggled(p))
                
        self.filter_and_display_items()

    def update_clipboard(self, text, status_msg=""):
        self.clipboard_clear(); self.clipboard_append(text)
        if status_msg: self.set_status_temporary(status_msg)

    # Bulk Update
    # ------------------------------
    def sync_checkboxes_to_model(self):
        self.controller.project_model._bulk_update_active = True
        with suspend_var_traces(self.file_vars.values()):
            selection = self.controller.project_model.selected_paths
            for path, var in self.file_vars.items():
                is_selected = path in selection
                if var.get() != is_selected:
                    var.set(is_selected)
        self.controller.project_model._bulk_update_active = False