"""
Face labeling window.

Lets the user:
  - See every cluster (avatar + count + current label + quality)
  - Type a name → press Save → cluster gets renamed (DB + folder + desktop.ini)
  - Mark a cluster as "merge target" + select another → merge them
  - Mark a cluster as a stranger → quarantine it
  - Restore a quarantined stranger
"""
import os
import logging
from typing import Optional, List

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

logger = logging.getLogger(__name__)


class LabelingWindow(tk.Toplevel):
    def __init__(self, parent, output_dir: str):
        super().__init__(parent)
        self.title("Label People")
        self.geometry("960x640")
        self.output_dir = output_dir

        from .database import Database
        self.db = Database(os.path.join(output_dir, "manifest.db"))

        self._photo_cache = {}  # keep PhotoImage refs alive
        self._merge_source: Optional[str] = None

        self._build_ui()
        self._reload()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=8, pady=8)
        ttk.Button(toolbar, text="Refresh", command=self._reload).pack(side="left")
        ttk.Button(toolbar, text="Show strangers",
                   command=self._toggle_strangers).pack(side="left", padx=4)

        self.var_show_strangers = tk.BooleanVar(value=False)

        # Treeview of clusters
        cols = ("key", "label", "count", "quality", "stranger")
        self.tree = ttk.Treeview(self, columns=cols, show="tree headings",
                                  height=18)
        self.tree.heading("#0", text="Avatar")
        self.tree.heading("key", text="Cluster")
        self.tree.heading("label", text="Label")
        self.tree.heading("count", text="Photos")
        self.tree.heading("quality", text="Quality")
        self.tree.heading("stranger", text="Stranger?")
        self.tree.column("#0", width=80, stretch=False)
        self.tree.column("key", width=140)
        self.tree.column("label", width=200)
        self.tree.column("count", width=70, anchor="e")
        self.tree.column("quality", width=80, anchor="center")
        self.tree.column("stranger", width=80, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=8, pady=4)

        scroll = ttk.Scrollbar(self.tree, orient="vertical",
                                command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)

        # Action bar
        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=8, pady=8)
        ttk.Button(actions, text="Rename / label",
                   command=self._rename_selected).pack(side="left", padx=4)
        ttk.Button(actions, text="Mark as stranger",
                   command=self._mark_stranger).pack(side="left", padx=4)
        ttk.Button(actions, text="Restore stranger",
                   command=self._restore_stranger).pack(side="left", padx=4)
        ttk.Button(actions, text="Set merge source",
                   command=self._set_merge_source).pack(side="left", padx=12)
        self.merge_label = ttk.Label(actions, text="Merge source: (none)",
                                       foreground="#555")
        self.merge_label.pack(side="left", padx=4)
        ttk.Button(actions, text="Merge into selected",
                   command=self._merge_into_selected).pack(side="left", padx=4)

        # Status
        self.var_status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.var_status,
                   relief="sunken", anchor="w").pack(side="bottom", fill="x")

    # ---------- Data load ----------
    def _reload(self):
        self.tree.delete(*self.tree.get_children())
        self._photo_cache.clear()
        clusters = self.db.get_face_clusters()

        show_strangers = self.var_show_strangers.get()
        for c in clusters:
            if c["cluster_key"].startswith("unknown_"):
                continue
            if bool(c["is_stranger"]) != show_strangers:
                continue
            avatar_img = self._load_avatar(c)
            self.tree.insert(
                "", "end",
                iid=c["cluster_key"],
                image=avatar_img,
                values=(
                    c["cluster_key"],
                    c["label"] or "",
                    c["member_count"] or 0,
                    c["quality_flag"] or "",
                    "yes" if c["is_stranger"] else "",
                ),
            )

    def _toggle_strangers(self):
        self.var_show_strangers.set(not self.var_show_strangers.get())
        self.var_status.set(
            "Showing strangers." if self.var_show_strangers.get()
            else "Showing labelled / candidate people."
        )
        self._reload()

    def _load_avatar(self, cluster_row) -> Optional[tk.PhotoImage]:
        from .organizer import face_folder_path
        folder = (cluster_row["folder_path"]
                   or face_folder_path(self.output_dir,
                                         cluster_row["cluster_key"],
                                         cluster_row["label"]))
        if not folder:
            return None
        path = os.path.join(folder, "cluster_avatar.jpg")
        if not os.path.isfile(path):
            return None
        try:
            from PIL import Image, ImageTk
            with Image.open(path) as im:
                im.thumbnail((64, 64))
                photo = ImageTk.PhotoImage(im)
            self._photo_cache[cluster_row["cluster_key"]] = photo
            return photo
        except Exception:
            return None

    # ---------- Actions ----------
    def _selected_key(self) -> Optional[str]:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(self.title(), "Select a cluster first.")
            return None
        return sel[0]

    def _rename_selected(self):
        ck = self._selected_key()
        if not ck:
            return
        cluster = self.db.get_cluster(ck)
        current = cluster["label"] or ""
        new = simpledialog.askstring(
            "Label person",
            f"Enter a name for cluster {ck}:",
            initialvalue=current, parent=self,
        )
        if new is None:
            return
        new = new.strip()
        try:
            from .labeling import label_person
            ok = label_person(self.db, self.output_dir, ck, new)
            if ok:
                self.var_status.set(f"Labeled {ck} → {new}")
                self._reload()
            else:
                self.var_status.set(f"Could not label {ck}")
        except Exception as e:
            messagebox.showerror(self.title(), f"Failed: {e}")

    def _mark_stranger(self):
        ck = self._selected_key()
        if not ck:
            return
        if not messagebox.askyesno(
            self.title(),
            f"Move cluster {ck} to _strangers/ folder?\n\n"
            "Photos are NOT deleted — they move into "
            "Photos_By_Face/_strangers/ for review."
        ):
            return
        try:
            from .stranger_filter import quarantine_strangers
            res = quarantine_strangers(self.db, self.output_dir, [ck])
            self.var_status.set(f"Quarantined: {res}")
            self._reload()
        except Exception as e:
            messagebox.showerror(self.title(), f"Failed: {e}")

    def _restore_stranger(self):
        ck = self._selected_key()
        if not ck:
            return
        try:
            from .stranger_filter import restore_stranger
            ok = restore_stranger(self.db, self.output_dir, ck)
            if ok:
                self.var_status.set(f"Restored {ck}")
                self._reload()
            else:
                self.var_status.set(f"Could not restore {ck}")
        except Exception as e:
            messagebox.showerror(self.title(), f"Failed: {e}")

    def _set_merge_source(self):
        ck = self._selected_key()
        if not ck:
            return
        self._merge_source = ck
        self.merge_label.config(text=f"Merge source: {ck}", foreground="#1976d2")

    def _merge_into_selected(self):
        if not self._merge_source:
            messagebox.showinfo(self.title(),
                                  "First click 'Set merge source' on a cluster.")
            return
        target = self._selected_key()
        if not target:
            return
        if target == self._merge_source:
            messagebox.showinfo(self.title(),
                                  "Source and target are the same cluster.")
            return
        if not messagebox.askyesno(
            self.title(),
            f"Merge {self._merge_source} → {target}?\n\n"
            "All detections + photos move into the target. "
            "The source cluster is removed."
        ):
            return
        try:
            from .cluster_repair import merge_clusters
            res = merge_clusters(self.db, self.output_dir,
                                   self._merge_source, target)
            self.var_status.set(f"Merge: {res}")
            self._merge_source = None
            self.merge_label.config(text="Merge source: (none)", foreground="#555")
            self._reload()
        except Exception as e:
            messagebox.showerror(self.title(), f"Failed: {e}")

    def _on_close(self):
        try:
            self.db.close()
        except Exception:
            pass
        self.destroy()
