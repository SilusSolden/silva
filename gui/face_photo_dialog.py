"""Face photo gallery dialog — camera capture or file upload."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog
from typing import Callable

from silva.gui.display_manager import register, unregister
from silva.users.face_id import (
    list_gallery_photos,
    photo_count,
    remove_gallery_photo,
)


class FacePhotoDialog:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        user_id: str,
        user_name: str,
        on_done: Callable[[bool, str], None] | None = None,
    ) -> None:
        self.user_id = user_id
        self.user_name = user_name
        self._on_done = on_done
        self._closed = False

        self.dialog = tk.Toplevel(parent)
        register(self.dialog)
        self.dialog.title(f"Silva - Face Photos ({user_name})")
        self.dialog.resizable(False, False)
        self.dialog.attributes("-topmost", True)
        self.dialog.transient(parent)
        self.dialog.protocol("WM_DELETE_WINDOW", self._close)

        body = tkfont.Font(family="Segoe UI", size=10)
        title = tkfont.Font(family="Segoe UI", size=11, weight="bold")

        width, height = 440, 320
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
        self.dialog.geometry(f"{width}x{height}+{px}+{py}")

        tk.Label(self.dialog, text=f"Face photos: {user_name}", font=title, fg="#1A237E").pack(
            pady=(12, 4)
        )
        self._status = tk.Label(
            self.dialog,
            text=f"{photo_count(user_id)} photo(s) saved. Add as many as you like.",
            font=body,
            fg="#455A64",
            wraplength=400,
        )
        self._status.pack(pady=(0, 8))

        self._list = tk.Listbox(self.dialog, font=body, height=8, width=52)
        self._list.pack(padx=14, pady=(0, 8))
        self._refresh_list()

        row = tk.Frame(self.dialog)
        row.pack(pady=(0, 10))
        tk.Button(row, text="Take Photo", font=body, width=12, command=self._take_photo).pack(
            side="left", padx=4
        )
        tk.Button(row, text="Upload Image", font=body, width=12, command=self._upload_image).pack(
            side="left", padx=4
        )
        tk.Button(row, text="Remove Selected", font=body, width=14, command=self._remove_selected).pack(
            side="left", padx=4
        )
        tk.Button(self.dialog, text="Close", font=body, width=12, command=self._close).pack(pady=(0, 12))

    def _refresh_list(self) -> None:
        self._list.delete(0, tk.END)
        for item in list_gallery_photos(self.user_id):
            label = f"{item.get('id', '?')}  ({item.get('source', 'photo')})"
            self._list.insert(tk.END, label)
        self._status.config(text=f"{photo_count(self.user_id)} photo(s) saved for matching.")

    def _set_status(self, message: str, *, error: bool = False) -> None:
        if self._closed or not self.dialog.winfo_exists():
            return
        self.dialog.after(
            0,
            lambda: self._status.config(text=message, fg="#C62828" if error else "#1B5E20"),
        )

    def _take_photo(self) -> None:
        def open_capture() -> None:
            self._set_status("Opening live camera...")
            from silva.gui.face_capture_dialog import FaceCaptureDialog

            FaceCaptureDialog(
                self.dialog,
                user_id=self.user_id,
                user_name=self.user_name,
                on_done=lambda ok, message: self.dialog.after(0, lambda: self._after_save(ok, message)),
            )

        from silva.users.camera_access import FEATURE_PROFILE_FACE, is_camera_granted, request_camera_access

        if is_camera_granted(self.user_id, FEATURE_PROFILE_FACE):
            open_capture()
            return
        self._set_status("Allow camera access in the popup.")
        request_camera_access(
            self.user_id,
            FEATURE_PROFILE_FACE,
            parent=self.dialog,
            on_result=lambda ok: self.dialog.after(
                0,
                open_capture if ok else lambda: self._set_status("Camera access was declined.", error=True),
            ),
        )

    def _upload_image(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.dialog,
            title="Choose face photo",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.webp"), ("All files", "*.*")],
        )
        if not path:
            return
        from silva.users.face_id import add_face_photo_from_file

        ok, message = add_face_photo_from_file(self.user_id, self.user_name, path)
        self._after_save(ok, message)

    def _after_save(self, ok: bool, message: str) -> None:
        self._set_status(message, error=not ok)
        self._refresh_list()
        if self._on_done:
            self._on_done(ok, message)

    def _remove_selected(self) -> None:
        selection = self._list.curselection()
        if not selection:
            return
        photos = list_gallery_photos(self.user_id)
        index = selection[0]
        if index >= len(photos):
            return
        photo_id = photos[index].get("id", "")
        if photo_id and remove_gallery_photo(self.user_id, photo_id):
            self._refresh_list()
            self._set_status("Photo removed.")

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.dialog.winfo_exists():
            unregister(self.dialog)
            self.dialog.destroy()
