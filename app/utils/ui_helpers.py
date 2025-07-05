# File: code_prompt_generator/app/utils/ui_helpers.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import tkinter as tk
from tkinter import ttk
import platform

# Formatting & String Utilities
# ------------------------------
def format_german_thousand_sep(num): return f"{num:,}".replace(",", ".")

# GUI Helper Utilities
# ------------------------------
def center_window(win, parent):
    try:
        win.update_idletasks()
        if parent and parent.winfo_exists():
            px, py, pw, ph = parent.winfo_rootx(), parent.winfo_rooty(), parent.winfo_width(), parent.winfo_height()
            w, h = win.winfo_width(), win.winfo_height()
            x, y = px + (pw//2) - (w//2), py + (ph//2) - (h//2)
            win.geometry(f"+{x}+{y}")
        else:
            win.update_idletasks()
            sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
            w, h = win.winfo_width(), win.winfo_height()
            x, y = (sw // 2) - (w // 2), (sh // 2) - (h // 2)
            win.geometry(f"+{x}+{y}")
    except Exception: pass

def apply_modal_geometry(win, parent_view, key):
    geom = parent_view.controller.settings_model.get('modal_geometry', {}).get(key)
    if geom: win.geometry(geom)
    else: center_window(win, parent_view)
    def on_close():
        geometry = parent_view.controller.settings_model.get('modal_geometry', {})
        geometry[key] = win.geometry()
        parent_view.controller.settings_model.set('modal_geometry', geometry)
        parent_view.controller.settings_model.save()
        win.destroy()
    win.protocol("WM_DELETE_WINDOW", on_close)
    win.resizable(True, True); win.focus_force()
    if parent_view.winfo_exists(): win.transient(parent_view)

def _show_dialog(parent, title, message, dialog_key, is_error=False):
    root_for_centering = parent
    if not parent and is_error:
        root_for_centering = tk.Tk(); root_for_centering.withdraw()
    win = tk.Toplevel(); win.title(title)
    ttk.Label(win, text=message, justify=tk.CENTER).pack(padx=20, pady=20)
    ttk.Button(win, text="OK", command=win.destroy).pack(pady=5)
    if parent: apply_modal_geometry(win, parent, dialog_key)
    else: center_window(win, root_for_centering)
    if not parent and is_error: win.after(100, root_for_centering.destroy)

def show_info_centered(parent, title, message): _show_dialog(parent, title, message, "InfoDialog")
def show_warning_centered(parent, title, message): _show_dialog(parent, title, message, "WarningDialog")
def show_error_centered(parent, title, message): _show_dialog(parent, title, message, "ErrorDialog", is_error=True)

def show_yesno_centered(parent, title, message):
    win = tk.Toplevel(); win.title(title)
    result = {"answer": False}
    ttk.Label(win, text=message).pack(padx=20, pady=20)
    def on_yes(): result["answer"] = True; win.destroy()
    btn_frame = ttk.Frame(win); btn_frame.pack(pady=5)
    ttk.Button(btn_frame, text="Yes", command=on_yes).pack(side=tk.LEFT, padx=10)
    ttk.Button(btn_frame, text="No", command=win.destroy).pack(side=tk.LEFT, padx=10)
    apply_modal_geometry(win, parent, "YesNoDialog")
    parent.wait_window(win)
    return result["answer"]

def show_yesnocancel_centered(parent, title, message, yes_text="Yes", no_text="No", cancel_text="Cancel"):
    win = tk.Toplevel(); win.title(title)
    result = {"answer": "cancel"}
    ttk.Label(win, text=message, justify=tk.CENTER).pack(padx=20, pady=20)
    def set_answer(ans): result["answer"] = ans; win.destroy()
    btn_frame = ttk.Frame(win); btn_frame.pack(pady=5)
    ttk.Button(btn_frame, text=yes_text, command=lambda: set_answer("yes")).pack(side=tk.LEFT, padx=10)
    ttk.Button(btn_frame, text=no_text, command=lambda: set_answer("no")).pack(side=tk.LEFT, padx=10)
    ttk.Button(btn_frame, text=cancel_text, command=win.destroy).pack(side=tk.LEFT, padx=10)
    win.protocol("WM_DELETE_WINDOW", win.destroy)
    apply_modal_geometry(win, parent, "YesNoCancelDialog")
    parent.wait_window(win)
    return result["answer"]

def handle_mousewheel(event, canvas):
    delta = 0
    if platform.system() == "Linux":
        if event.num == 4: delta = -1
        elif event.num == 5: delta = 1
    elif platform.system() == "Windows":
        delta = -int(event.delta / 120)
    else: # macOS
        delta = -event.delta
    canvas.yview_scroll(delta, "units")
    return "break"