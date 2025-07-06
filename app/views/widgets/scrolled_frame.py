# File: code_prompt_generator/app/views/widgets/scrolled_frame.py
# LLM NOTE: LLM Editor, follow these code style guidelines: (1) No docstrings or extra comments; (2) Retain the file path comment, LLM note, and grouping/separation markers exactly as is; (3) Favor concise single-line statements; (4) Preserve code structure and organization

# Imports
# ------------------------------
import tkinter as tk
from tkinter import ttk
from app.utils.ui_helpers import handle_mousewheel

# Reusable Scrolled Frame Widget
# ------------------------------
class ScrolledFrame(ttk.Frame):
    def __init__(self, parent, side=tk.LEFT, fill=tk.BOTH, expand=False, width=None, padx=0, pady=0, add_horizontal_scrollbar=False):
        super().__init__(parent)
        self.pack(side=side, fill=fill, expand=expand, padx=padx, pady=pady)
        if width: self.config(width=width); self.pack_propagate(False)
        self.add_horizontal_scrollbar = add_horizontal_scrollbar

        self.canvas = tk.Canvas(self, highlightthickness=0, background='#F3F3F3')
        self.v_scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.v_scrollbar.set)
        if add_horizontal_scrollbar:
            self.h_scrollbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
            self.canvas.configure(xscrollcommand=self.h_scrollbar.set)
            self.h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.inner_frame = ttk.Frame(self.canvas)
        self.inner_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.inner_frame, anchor='nw')
        self.canvas.bind('<Configure>', self._on_canvas_configure)

        self.bind_mousewheel_to_widget(self.canvas)
        self.bind_mousewheel_to_widget(self.inner_frame)

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        
    def _on_canvas_configure(self, event):
        if not self.add_horizontal_scrollbar:
            self.canvas.itemconfig(self.canvas_window, width=event.width)

    def bind_mousewheel_to_widget(self, widget):
        widget.bind("<MouseWheel>", lambda e: handle_mousewheel(e, self.canvas), add='+')
        widget.bind("<Button-4>", lambda e: handle_mousewheel(e, self.canvas), add='+')
        widget.bind("<Button-5>", lambda e: handle_mousewheel(e, self.canvas), add='+')