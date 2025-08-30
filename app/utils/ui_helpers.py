# File: app/utils/ui_helpers.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization.

import tkinter as tk
from tkinter import ttk, messagebox
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
	except tk.TclError: pass

def apply_modal_geometry(win, parent, key):
	if hasattr(parent, 'controller'):
		controller = parent.controller
		parent_view = parent
	else:
		controller = parent
		parent_view = getattr(parent, 'view', parent if isinstance(parent, tk.Widget) else None)
		
	geom = controller.settings_model.get('modal_geometry', {}).get(key)
	if geom: win.geometry(geom)
	else: center_window(win, parent_view)
	def on_close():
		geometry = controller.settings_model.get('modal_geometry', {})
		geometry[key] = win.geometry()
		controller.settings_model.set('modal_geometry', geometry)
		controller.settings_model.save()
		win.destroy()
	win.protocol("WM_DELETE_WINDOW", on_close)
	win.resizable(True, True); win.focus_force()
	if parent_view and isinstance(parent_view, tk.Widget) and parent_view.winfo_exists():
		win.transient(parent_view)
	return on_close

def _show_dialog(parent, title, message, is_error=False):
	if parent is None or not parent.winfo_exists():
		if is_error: messagebox.showerror(title, message)
		else: messagebox.showwarning(title, message)
		return
	
	win = tk.Toplevel(parent); win.title(title); win.transient(parent)
	label = ttk.Label(win, text=message, justify=tk.LEFT, wraplength=max(400, parent.winfo_width()//3))
	label.pack(padx=20, pady=20)
	ok_button = ttk.Button(win, text="OK", command=win.destroy); ok_button.pack(pady=(0, 10))
	win.resizable(False, False); win.update_idletasks()
	center_window(win, parent); win.grab_set(); ok_button.focus_set()
	parent.wait_window(win)

def show_info_centered(parent, title, message): _show_dialog(parent, title, message)
def show_warning_centered(parent, title, message): _show_dialog(parent, title, message)
def show_error_centered(parent, title, message): _show_dialog(parent, title, message, is_error=True)

def show_yesno_centered(parent, title, message):
	if parent is None or not parent.winfo_exists(): return messagebox.askyesno(title, message)
	win = tk.Toplevel(parent); win.title(title); win.transient(parent)
	result = {"answer": False}
	def on_close(): win.destroy()
	def on_yes(): result["answer"] = True; on_close()

	label = ttk.Label(win, text=message, justify=tk.LEFT, wraplength=max(400, parent.winfo_width()//3))
	label.pack(padx=20, pady=20)
	btn_frame = ttk.Frame(win); btn_frame.pack(pady=(0,10))
	yes_btn = ttk.Button(btn_frame, text="Yes", command=on_yes); yes_btn.pack(side=tk.LEFT, padx=10)
	ttk.Button(btn_frame, text="No", command=on_close).pack(side=tk.LEFT, padx=10)
	
	win.protocol("WM_DELETE_WINDOW", on_close); win.resizable(False, False); win.update_idletasks()
	center_window(win, parent); win.grab_set(); yes_btn.focus_set()
	parent.wait_window(win)
	return result["answer"]

def show_yesnocancel_centered(parent, title, message, yes_text="Yes", no_text="No", cancel_text="Cancel"):
	if parent is None or not parent.winfo_exists():
		answer = messagebox.askquestion(title, message, type=messagebox.YESNOCANCEL)
		return answer

	win = tk.Toplevel(parent); win.title(title); win.transient(parent)
	result = {"answer": "cancel"}
	def on_close(): win.destroy()
	def set_answer(ans): result["answer"] = ans; on_close()

	label = ttk.Label(win, text=message, justify=tk.LEFT, wraplength=max(400, parent.winfo_width()//3))
	label.pack(padx=20, pady=20)
	btn_frame = ttk.Frame(win); btn_frame.pack(pady=(0,10))
	yes_btn = ttk.Button(btn_frame, text=yes_text, command=lambda: set_answer("yes")); yes_btn.pack(side=tk.LEFT, padx=10)
	ttk.Button(btn_frame, text=no_text, command=lambda: set_answer("no")).pack(side=tk.LEFT, padx=10)
	ttk.Button(btn_frame, text=cancel_text, command=on_close).pack(side=tk.LEFT, padx=10)

	win.protocol("WM_DELETE_WINDOW", on_close); win.resizable(False, False); win.update_idletasks()
	center_window(win, parent); win.grab_set(); yes_btn.focus_set()
	parent.wait_window(win)
	return result["answer"]

def create_enhanced_text_widget(parent, with_scrollbars=True, **kwargs):
	frame = ttk.Frame(parent)
	text_kwargs = {'undo': True, 'wrap': 'none', 'font': ('Consolas', 10) if platform.system() == "Windows" else ('Menlo', 11) if platform.system() == "Darwin" else ('monospace', 10)}
	text_kwargs.update(kwargs)
	text = tk.Text(frame, **text_kwargs)
	if with_scrollbars:
		v_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
		h_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=text.xview)
		text.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
		frame.grid_rowconfigure(0, weight=1); frame.grid_columnconfigure(0, weight=1)
		text.grid(row=0, column=0, sticky='nsew'); v_scroll.grid(row=0, column=1, sticky='ns'); h_scroll.grid(row=1, column=0, sticky='ew')
		def _on_mousewheel(event):
			if platform.system() == "Linux":
				if event.num == 4: text.yview_scroll(-3, "units")
				elif event.num == 5: text.yview_scroll(3, "units")
			elif platform.system() == "Windows":
				text.yview_scroll(int(-1 * (event.delta / 120)) * 3, "units")
			else:
				text.yview_scroll(-event.delta * 3, "units")
			return "break"
		def _on_shift_mousewheel(event):
			if platform.system() == "Linux":
				if event.num == 4: text.xview_scroll(-3, "units")
				elif event.num == 5: text.xview_scroll(3, "units")
			elif platform.system() == "Windows":
				text.xview_scroll(int(-1 * (event.delta / 120)) * 3, "units")
			else:
				text.xview_scroll(-event.delta * 3, "units")
			return "break"
		text.bind('<MouseWheel>', _on_mousewheel, add='+'); text.bind('<Button-4>', _on_mousewheel, add='+'); text.bind('<Button-5>', _on_mousewheel, add='+'); text.bind('<Shift-MouseWheel>', _on_shift_mousewheel, add='+')
	else:
		frame.grid_rowconfigure(0, weight=1); frame.grid_columnconfigure(0, weight=1); text.grid(row=0, column=0, sticky='nsew')
	text.container = frame
	return text

def handle_mousewheel(event, canvas):
	delta = 0
	if platform.system() == "Linux":
		if event.num == 4: delta = -3
		elif event.num == 5: delta = 3
	elif platform.system() == "Windows":
		delta = -int(event.delta / 120) * 3
	else:
		delta = -event.delta * 3
	canvas.yview_scroll(delta, "units")
	return "break"