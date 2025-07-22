# File: code_prompt_generator/app/views/widgets/cycling_auto_combobox.py
# MIT-licensed drop-in; requires autocombobox ≥ 1.5.0   (Python 3.10+)

from autocombobox import AutoCombobox
import logging

logger = logging.getLogger(__name__)

__all__ = ["CyclingAutoCombobox"]


def _keep_all(options: tuple[str], _text: str) -> list[int]:
    """Identity filter – never hide any rows."""
    return list(range(len(options)))


class CyclingAutoCombobox(AutoCombobox):
    """
    Read-only ttk.Combobox that *keeps the full list visible* and cycles
    through successive items that start with the pressed key, wrapping
    after the last match.  No “snap-back” artefacts.
    """

    def __init__(self, master=None, **kw):
        kw.setdefault("state", "readonly")
        super().__init__(master, filter=_keep_all, **kw)

        self._cycle_pos: dict[str, int] = {}
        self._outside_bind_id = None
        self._lb_bind_ids: dict[str, str] = {}  # For listbox-specific bindings
        self.bind("<KeyPress>", self._cycle)  # replace default key handler

    # ───────────────────────────────────────────────────────────────
    #  Keep INTERNAL STATE in sync when caller uses .current(idx)
    # ───────────────────────────────────────────────────────────────
    def current(self, newindex: int | None = None):
        """
        • When called **without** an argument, behave like ttk.Combobox.current()
          and just return the active index.
        • When called **with** an index, forward to the base implementation
          *and* update our private `_selected_str` and cycling cache so every
          other helper sees the new value immediately.
        """
        if newindex is None:
            return super().current()  # getter – unchanged

        super().current(newindex)  # set highlight/entry field
        try:
            value = self["values"][newindex]
        except IndexError:
            value = ""

        # Mirror displayed text
        self._selected_str = value

        # Reset or realign cycling cache for the first character
        if value:
            ch = str(value)[0].lower()
            self._cycle_pos[ch] = newindex
        else:
            self._cycle_pos.clear()

    # Keep internal pointer in sync when code calls .set(...)
    def set(self, value):
        logger.debug("CyclingAutoCombobox.set(%s)", value)
        super().set(value)  # update entry field
        self._selected_str = value  # mirror displayed text

        # Align the “current selection index” with the new text
        try:
            idx = list(self["values"]).index(value)
        except ValueError:
            idx = -1

        if idx >= 0:
            self.current(idx)  # safe: Tk accepts >= 0 only
        else:
            self._cycle_pos.clear()

    # ════════════════════════════════════════════════════════════════
    #  CLICK-OUTSIDE SUPPORT
    # ════════════════════════════════════════════════════════════════
    def show_listbox(self, *a, **kw):
        super().show_listbox(*a, **kw)
        logger.debug("show_listbox() opened – current value='%s'", self.get())

        # Bind for click-outside-to-close (once per popup)
        if self._outside_bind_id is None:
            root = self.winfo_toplevel()
            self._outside_bind_id = root.bind("<Button-1>", self._on_click_outside, add="+")

        # Explicitly bind mouse selection to the listbox
        lb = getattr(self, "_listbox", None)
        if lb:
            # ------------------------------------------------------------------
            # 1)  Make *sure* the highlight matches the widget’s current value
            #     (even if that value was set via `variable.set()` which bypasses
            #     the Combobox.set() method and leaves `current()` at −1).
            # ------------------------------------------------------------------
            cur_val = self.get()
            try:
                idx = list(self["values"]).index(cur_val)
            except ValueError:
                idx = -1
            if idx < 0:  # fall back to first real entry
                for i, v in enumerate(self["values"]):
                    if not str(v).startswith("-- "):
                        idx = i
                        break
            if idx >= 0:
                self.current(idx)  # update Combobox’ internal pointer

            # We have to delay the list‑box highlight until Tk has *drawn*
            # and populated it – one idle‑callback later is enough.
            self.after_idle(
                lambda lb=lb: (self._sync_listbox_to_current(lb), logger.debug("after_idle highlight done"))
            )

            # Bind mouse events ONCE per listbox instance to avoid stacking.
            if "<Motion>" not in self._lb_bind_ids:
                self._lb_bind_ids["<Motion>"] = lb.bind("<Motion>", self._on_mouse_move, add="+")
                # run *in addition* to Tk’s own click‑handler – don’t replace it
                self._lb_bind_ids["<ButtonRelease-1>"] = lb.bind(
                    "<ButtonRelease-1>", self._on_mouse_select, add="+"
                )

    # ―――― helpers ――――――――――――――――――――――――――――――――――――――――――――
    def _sync_listbox_to_current(self, lb):
        """Highlight the list‑row that matches the combobox’ current value.
        Falls back to the first *selectable* entry (skipping “-- … --”)."""
        vals = list(self["values"])
        logger.debug("_sync_listbox_to_current → value='%s'", self.get())
        cur_val = self.get()
        try:
            idx = vals.index(cur_val)
        except ValueError:
            idx = -1
        if idx < 0:  # nothing selected yet → pick first real item
            for i, v in enumerate(vals):
                if not str(v).startswith("-- "):
                    idx = i
                    break
        if idx >= 0:
            lb.selection_clear(0, "end")
            lb.selection_set(idx)
            lb.activate(idx)
            lb.see(idx)

    def hide_listbox(self, *a, **kw):
        super().hide_listbox(*a, **kw)
        # unbind when popup disappears
        if self._outside_bind_id is not None:
            self.winfo_toplevel().unbind("<Button-1>", self._outside_bind_id)
            self._outside_bind_id = None

        # unbind per-listbox events to prevent memory leaks
        lb = getattr(self, "_listbox", None)
        if lb:
            for evt, bid in self._lb_bind_ids.items():
                try:
                    lb.unbind(evt, bid)
                except Exception:  # Widget might be dead already
                    pass
        self._lb_bind_ids.clear()

    def _on_click_outside(self, event):
        """Close popup if the click wasn’t on the combobox or its listbox."""
        lb = getattr(self, "_listbox", None)
        if not getattr(self, "_is_posted", False) or lb is None:
            return

        # Traverse up from the clicked widget to see if it's part of our combobox.
        w = event.widget
        while w:
            if w == self or w == lb:
                return  # Click was inside; do nothing.
            w = getattr(w, "master", None)

        # If we reached here, the click was outside.
        self.hide_listbox()

    def _on_mouse_move(self, event):
        """
        Hover feedback – keep the listbox *visually* in sync with the pointer.
        We repaint the blue selection bar ourselves so users always see which
        row will be chosen when they click.
        """
        lb = event.widget
        idx = lb.nearest(event.y)
        if idx >= 0:
            lb.selection_clear(0, "end")
            lb.selection_set(idx)  # blue highlight follows mouse
            lb.activate(idx)  # underline too

    def _on_mouse_select(self, event):
        """Pick the row the user clicked, fire <<ComboboxSelected>>, shut popup."""
        lb = event.widget
        index = lb.nearest(event.y)
        if index < 0:
            return

        value = self["values"][index]
        if str(value).startswith("-- "):
            logger.debug("mouse_select ignored separator row idx=%s", index)
            return

        # Update combobox value
        self.current(index)
        self._selected_str = value

        logger.debug("mouse_select picked idx=%s val='%s'", index, value)
        # Notify listeners once
        self.event_generate("<<ComboboxSelected>>")

        # Close popup **after** Tk’s own handlers have run. This prevents
        # the classic "off-by-one" selection error.
        self.after_idle(self.hide_listbox)

    # ------------------------------------------------------------------
    def _cycle(self, event):
        ch = event.char.lower()
        logger.debug("cycle key='%s'", ch)
        if len(ch) != 1:  # ignore arrows, etc.
            return  # let autocomplete handle

        vals = list(self["values"])
        # skip separator rows; coerce to string for safety
        hits = [
            i
            for i, v in enumerate(vals)
            if (not str(v).startswith("-- ")) and str(v).lower().startswith(ch)
        ]
        if not hits:
            return "break"  # key handled – no match

        # Validate the last-used index before trying to use it.
        last = self._cycle_pos.get(ch)
        if last not in hits:
            last = hits[-1]

        nxt = hits[(hits.index(last) + 1) % len(hits)]
        logger.debug("cycle hits=%s next=%s val='%s'", hits, nxt, vals[nxt])
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

        return "break"  # stop default key-handler