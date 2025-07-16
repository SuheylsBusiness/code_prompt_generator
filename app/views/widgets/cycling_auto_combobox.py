# File: code_prompt_generator/app/views/widgets/cycling_auto_combobox.py
# MIT-licensed drop-in; requires autocombobox ≥ 1.5.0   (Python 3.10+)

from autocombobox import AutoCombobox

def _keep_all(options: tuple[str], _text: str) -> list[int]:
    """Identity filter – never hide any rows."""
    return list(range(len(options)))

class CyclingAutoCombobox(AutoCombobox):
    """
    Read-only ttk.Combobox that *keeps the full list visible* and cycles
    through successive items that start with the pressed key, wrapping
    after the last match.  No “snap-back” artefacts.
    """
    def __init__(self, master=None, **kw):
        kw.setdefault("state", "readonly")
        super().__init__(master, filter=_keep_all, **kw)

        self._cycle_pos: dict[str, int] = {}
        self._outside_bind_id = None
        self.bind("<KeyPress>", self._cycle)  # replace default key handler

    # ════════════════════════════════════════════════════════════════
    #  CLICK-OUTSIDE SUPPORT
    # ════════════════════════════════════════════════════════════════
    def show_listbox(self, *a, **kw):
        super().show_listbox(*a, **kw)

        # Bind for click-outside-to-close (once per popup)
        if self._outside_bind_id is None:
            root = self.winfo_toplevel()
            self._outside_bind_id = root.bind(
                "<Button-1>", self._on_click_outside, add="+"
            )
        
        # Explicitly bind mouse selection to the listbox
        lb = getattr(self, "_listbox", None)
        if lb:
            lb.bind("<ButtonRelease-1>", self._on_mouse_select)

    def hide_listbox(self, *a, **kw):
        super().hide_listbox(*a, **kw)
        # unbind when popup disappears
        if self._outside_bind_id is not None:
            self.winfo_toplevel().unbind("<Button-1>", self._outside_bind_id)
            self._outside_bind_id = None

    def _on_click_outside(self, event):
        """Close popup if the click wasn’t on the combobox or its listbox."""
        lb = getattr(self, "_listbox", None)
        if not getattr(self, "_is_posted", False) or lb is None:
            return
        
        # Traverse up from the clicked widget to see if it's part of our combobox.
        w = event.widget
        while w:
            if w == self or w == lb:
                return # Click was inside; do nothing.
            w = getattr(w, 'master', None)

        # If we reached here, the click was outside.
        self.hide_listbox()
        
    # Handler for selecting an item with the mouse
    def _on_mouse_select(self, event):
        """Select the clicked item and close the listbox."""
        lb = event.widget
        index = lb.nearest(event.y)
        if 0 <= index < lb.size():
            self.current(index)
            self._selected_str = self['values'][index]
            # FIXED: Manually generate the event to ensure the app recognizes the change.
            self.event_generate("<<ComboboxSelected>>")
            self.hide_listbox()

    # ------------------------------------------------------------------
    def _cycle(self, event):
        ch = event.char.lower()
        if len(ch) != 1:                             # ignore arrows, etc.
            return                                   # let autocomplete handle

        vals = list(self["values"])
        hits = [i for i, v in enumerate(vals) if v.lower().startswith(ch)]
        if not hits:
            return "break"                           # key handled – no match

        # Validate the last-used index before trying to use it.
        last = self._cycle_pos.get(ch)
        if last not in hits:
            last = hits[-1]

        nxt  = hits[(hits.index(last) + 1) % len(hits)]
        self._cycle_pos[ch] = nxt

        # open the listbox once, only on the first keystroke
        if not getattr(self, "_is_posted", False):
            self.show_listbox()

        # update selection and internal pointer (prevents snap-back)
        self.current(nxt)
        self._selected_str = vals[nxt]

        # highlight the same row when the dropdown is open
        lb = getattr(self, "_listbox", None)
        if lb is not None:
            lb.selection_clear(0, "end")
            lb.selection_set(nxt)
            lb.activate(nxt)
            lb.see(nxt)

        return "break"                               # stop default key-handler