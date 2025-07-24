# File: code_prompt_generator/app/views/widgets/cycling_auto_combobox.py

from autocombobox import AutoCombobox
import tkinter as tk

class CyclingAutoCombobox(AutoCombobox):
    _active_comboboxes = set()
    _global_bind_id = None

    def __init__(self, master=None, **kw):
        kw.setdefault("state", "readonly")
        super().__init__(master, filter=lambda options, _: list(range(len(options))), **kw)
        self._selected_str = ""
        self._cycle_pos = {}
        self._lb_bind_ids = {}
        self._cached_values = None
        self._values_map = None
        self._prefix_map = None
        self.bind("<KeyPress>", self._cycle)
        self.bind("<Destroy>", self._on_destroy, add="+")

    def current(self, newindex=None):
        if newindex is None:
            return super().current()
        super().current(newindex)
        self._selected_str = self.get()
        value = self._selected_str
        if value:
            ch = str(value)[0].casefold()
            indices = self._get_values_map().get(value)
            idx = indices[0] if indices else -1
            if idx != -1:
                self._cycle_pos[ch] = idx
        else:
            self._cycle_pos.clear()

    def set(self, value):
        super().set(value)
        self._selected_str = value
        indices = self._get_values_map().get(value)
        idx = indices[0] if indices else -1
        if idx >= 0:
            self.current(idx)
        else:
            self._cycle_pos.clear()

    def show_listbox(self, *a, **kw):
        super().show_listbox(*a, **kw)
        if not CyclingAutoCombobox._global_bind_id:
            root = self.winfo_toplevel()
            CyclingAutoCombobox._global_bind_id = root.bind(
                "<Button-1>", CyclingAutoCombobox._on_global_click, add="+"
            )
        CyclingAutoCombobox._active_comboboxes.add(self)
        lb = getattr(self, "_listbox", None)
        if lb:
            cur_val = self.get()
            indices = self._get_values_map().get(cur_val)
            idx = indices[0] if indices else -1
            if idx < 0:
                for i, v in enumerate(self._get_values()):
                    if not str(v).startswith("-- "):
                        idx = i
                        break
            if idx >= 0:
                self.current(idx)
            self.after_idle(lambda lb=lb: self._safe_sync_listbox(lb))
            if "<Motion>" not in self._lb_bind_ids:
                self._lb_bind_ids["<Motion>"] = lb.bind("<Motion>", self._on_mouse_move, add="+")
                self._lb_bind_ids["<ButtonRelease-1>"] = lb.bind("<ButtonRelease-1>", self._on_mouse_select, add="+")
                self._lb_bind_ids["<Return>"] = lb.bind("<Return>", self._on_enter_press, add="+")

    def _safe_sync_listbox(self, lb):
        if lb and lb.winfo_exists():
            try:
                self._sync_listbox_to_current(lb)
            except tk.TclError:
                pass

    def _sync_listbox_to_current(self, lb):
        vals = self._get_values()
        cur_val = self.get()
        indices = self._get_values_map().get(cur_val)
        idx = indices[0] if indices else -1
        if idx < 0:
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
        lb = getattr(self, "_listbox", None)
        if lb and lb.winfo_exists():
            self._commit_listbox_selection(lb)
        super().hide_listbox(*a, **kw)
        CyclingAutoCombobox._active_comboboxes.discard(self)
        if not CyclingAutoCombobox._active_comboboxes and CyclingAutoCombobox._global_bind_id:
            try:
                self.winfo_toplevel().unbind("<Button-1>", CyclingAutoCombobox._global_bind_id)
            except Exception:
                pass
            CyclingAutoCombobox._global_bind_id = None
        if lb:
            for evt, bid in self._lb_bind_ids.items():
                try:
                    lb.unbind(evt, bid)
                except Exception:
                    pass
        self._lb_bind_ids.clear()

    def _commit_listbox_selection(self, lb):
        if not lb or not lb.winfo_exists():
            return
        sel = lb.curselection()
        index_str = sel[0] if sel else lb.index("active")
        try:
            index = int(index_str)
        except (TypeError, ValueError):
            return
        if index < 0 or lb.bbox(index) is None:
            return
        value = self._get_values()[index]
        if str(value).startswith("-- "):
            return
        if self.get() != value:
            self.current(index)
            self._selected_str = self.get()
            self.event_generate("<<ComboboxSelected>>")

    @classmethod
    def _on_global_click(cls, event):
        for combo in list(cls._active_comboboxes):
            if combo.winfo_exists():
                combo._on_click_outside(event)

    def _on_click_outside(self, event):
        lb = getattr(self, "_listbox", None)
        if not getattr(self, "_is_posted", False) or lb is None:
            return
        w = event.widget
        while w:
            if w == self or w == lb:
                return
            w = getattr(w, "master", None)
        self.hide_listbox()

    def _on_mouse_move(self, event):
        lb = event.widget
        idx = lb.nearest(event.y)
        prev = lb.curselection()
        if prev and int(prev[0]) == idx:
            return
        if idx >= 0:
            if str(self._get_values()[idx]).startswith("-- "):
                lb.selection_clear(0, "end")
                return
            lb.selection_clear(0, "end")
            lb.selection_set(idx)
            lb.activate(idx)

    def _on_mouse_select(self, event):
        lb = event.widget
        self.after_idle(lambda lb=lb, y=event.y: self._apply_mouse_choice(lb, y))
        return "break"

    def _apply_mouse_choice(self, lb, y):
        if not lb.winfo_exists():
            return
        index = lb.nearest(y)
        if index < 0:
            return
        value = self._get_values()[index]
        if str(value).startswith("-- "):
            return
        self.current(index)
        self._selected_str = self.get()
        self.event_generate("<<ComboboxSelected>>")
        self.hide_listbox()

    def _on_enter_press(self, event):
        lb = event.widget
        current_selection = lb.curselection()
        index_str = current_selection[0] if current_selection else lb.index("active")
        try:
            index = int(index_str)
        except (ValueError, TypeError):
            return "break"
        if index < 0:
            return "break"
        value = self._get_values()[index]
        if str(value).startswith("-- "):
            return "break"
        self.current(index)
        self._selected_str = self.get()
        self.event_generate("<<ComboboxSelected>>")
        self.after_idle(self.hide_listbox)
        return "break"

    def _on_destroy(self, _):
        CyclingAutoCombobox._active_comboboxes.discard(self)
        if not CyclingAutoCombobox._active_comboboxes and CyclingAutoCombobox._global_bind_id:
            try:
                root = self.winfo_toplevel()
                if root.winfo_exists():
                    root.unbind("<Button-1>", CyclingAutoCombobox._global_bind_id)
            except Exception:
                pass
            CyclingAutoCombobox._global_bind_id = None

    def _cycle(self, event):
        key = event.char
        if not key or len(key) != 1 or not key.isprintable():
            return
        folded_key = key.casefold()
        if self._prefix_map is None:
            self._build_prefix_index()
        hits = self._prefix_map.get(folded_key, [])
        if not hits:
            return "break"
        
        last_idx = self._cycle_pos.get(folded_key)
        try:
            current_hit_pos = hits.index(last_idx)
            next_hit_pos = (current_hit_pos + 1) % len(hits)
        except (ValueError, TypeError):
            next_hit_pos = 0
        nxt = hits[next_hit_pos]

        self._cycle_pos[folded_key] = nxt
        if not getattr(self, "_is_posted", False):
            self.show_listbox()
        self.current(nxt)
        self._selected_str = self.get()
        lb = getattr(self, "_listbox", None)
        if lb and lb.winfo_exists():
            lb.selection_clear(0, "end")
            lb.selection_set(nxt)
            lb.activate(nxt)
            lb.see(nxt)
        return "break"

    def _invalidate_values_cache(self):
        self._cached_values = None
        self._values_map = None
        self._prefix_map = None

    def _build_prefix_index(self):
        self._prefix_map = {}
        for i, v in enumerate(self._get_values()):
            val_str = str(v)
            if val_str.startswith("-- ") or not val_str:
                continue
            first = val_str[0].casefold()
            self._prefix_map.setdefault(first, []).append(i)

    def configure(self, cnf=None, **kw):
        if "values" in kw or (isinstance(cnf, dict) and "values" in cnf):
            self._invalidate_values_cache()
        return super().configure(cnf, **kw)

    config = configure

    def __setitem__(self, key, value):
        if key == "values":
            self._invalidate_values_cache()
        super().__setitem__(key, value)

    def _get_values(self):
        if self._cached_values is None:
            self._cached_values = list(self["values"])
        return self._cached_values

    def _get_values_map(self):
        if self._values_map is None:
            self._values_map = {}
            for i, v in enumerate(self._get_values()):
                self._values_map.setdefault(v, []).append(i)
        return self._values_map