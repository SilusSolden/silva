"""Silva profile page - manage users, voice enrollment, and pending approvals."""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from typing import Callable

from silva.gui.bug_report_dialog import run_bug_report_dialog
from silva.gui.face_photo_dialog import FacePhotoDialog
from silva.gui.face_scan_dialog import FaceScanPanel
from silva.gui.tier_permissions_dialog import open_tier_permissions_dialog
from silva.gui.user_features_dialog import open_user_features_dialog
from silva.users.face_id import has_face_enrolled, photo_count
from silva.users.features import can_edit_user_features, editable_features_for_target
from silva.gui.display_manager import register, unregister
from silva.gui.monitors import geometry_on_monitor
from silva.users.enrollment import apply_voice_enrollment
from silva.users.manager import (
    add_user,
    get_active_user,
    get_owner,
    identify_and_set_active,
    is_owner,
    list_users,
    load_store,
    remove_user,
)
from silva.users.tiers import MAX_TIER, normalize_tier, tier_description
from silva.users.voice_requests import (
    approve_voice_request,
    list_voice_requests,
    reject_voice_request,
)


@dataclass
class ProfilePanelResult:
    continued: bool
    active_user_id: str
    cancelled: bool = False


IdentifyCallback = Callable[[], dict | None]


def _can_manage_users(user: dict) -> bool:
    return is_owner(user)


def _can_open_admin_panel(user: dict) -> bool:
    return is_owner(user) or normalize_tier(user.get("tier", 1)) >= 4


def _can_approve_voice(user: dict) -> bool:
    tier = normalize_tier(user.get("tier"))
    return is_owner(user) or tier >= 4


def _can_record_voice(viewer: dict, target: dict) -> bool:
    return _can_manage_users(viewer) or viewer.get("id") == target.get("id")


def _run_panel(
    *,
    startup: bool,
    panel_mode: str,
    self_user_id: str | None,
    on_identify: IdentifyCallback | None,
    result: dict,
) -> None:
    from silva.logger import log_error

    root = None
    try:
        root = tk.Tk()
        register(root)
        result["own_loop"] = True
        _run_panel_ui(
            root,
            startup=startup,
            panel_mode=panel_mode,
            self_user_id=self_user_id,
            on_identify=on_identify,
            result=result,
        )
    except tk.TclError as exc:
        log_error("Profile panel hit a Tcl window error", exc=exc)
        done = result.get("done")
        if done is not None:
            done.set()
    except Exception as exc:
        log_error("Profile panel failed", exc=exc)
        done = result.get("done")
        if done is not None:
            done.set()
    finally:
        if root is None:
            return
        try:
            unregister(root)
            if root.winfo_exists():
                root.destroy()
        except tk.TclError:
            pass
        except Exception:
            pass


def _run_panel_ui(
    root: tk.Tk,
    *,
    startup: bool,
    panel_mode: str,
    self_user_id: str | None,
    on_identify: IdentifyCallback | None,
    result: dict,
) -> None:
    root.title("Silva - Profiles")
    root.resizable(True, True)
    root.attributes("-topmost", True)

    width, height = 720, 540
    root.geometry(geometry_on_monitor(width, height, anchor="center"))
    root.minsize(520, 400)

    title_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")
    body_font = tkfont.Font(family="Segoe UI", size=10)
    small_font = tkfont.Font(family="Segoe UI", size=9)

    header = tk.Frame(root, bg="#E8EAF6")
    header.pack(fill="x")
    title_text = "Silva Profiles"
    if panel_mode == "self":
        title_text = "My Profile"
    elif panel_mode == "admin":
        title_text = "Silva Control Panel"

    tk.Label(header, text=title_text, font=title_font, bg="#E8EAF6", fg="#1A237E").pack(
        anchor="w", padx=14, pady=(10, 2)
    )
    if panel_mode == "owner" and startup:
        subtitle = "Set up owner voice, face scan, and user profiles."
    elif panel_mode == "owner":
        subtitle = "Owner setup — manage all users and security."
    elif panel_mode == "admin":
        subtitle = "Admin control panel — help set up profiles and approve voice samples."
    elif panel_mode == "self":
        subtitle = "Set up your own voice and face profile."
    else:
        subtitle = "Manage profiles and voice enrollment."
    tk.Label(header, text=subtitle, font=small_font, bg="#E8EAF6", fg="#455A64").pack(
        anchor="w", padx=14, pady=(0, 10)
    )

    status_var = tk.StringVar(value="")
    status_label = tk.Label(root, textvariable=status_var, font=small_font, fg="#37474F")
    status_label.pack(fill="x", padx=14, pady=(8, 4))

    active_frame = tk.Frame(root)
    active_frame.pack(fill="x", padx=14, pady=(0, 6))

    users_outer = tk.LabelFrame(root, text="Users", font=body_font, padx=8, pady=8)
    users_outer.pack(fill="both", expand=True, padx=14, pady=(0, 6))

    users_canvas = tk.Canvas(users_outer, highlightthickness=0)
    users_scroll = tk.Scrollbar(users_outer, orient="vertical", command=users_canvas.yview)
    users_inner = tk.Frame(users_canvas)
    users_inner.bind(
        "<Configure>",
        lambda _event: users_canvas.configure(scrollregion=users_canvas.bbox("all")),
    )
    users_canvas.create_window((0, 0), window=users_inner, anchor="nw")
    users_canvas.configure(yscrollcommand=users_scroll.set)
    users_canvas.pack(side="left", fill="both", expand=True)
    users_scroll.pack(side="right", fill="y")

    pending_frame = tk.LabelFrame(root, text="Pending voice samples", font=body_font, padx=8, pady=8)
    if panel_mode in {"owner", "admin"}:
        pending_frame.pack(fill="x", padx=14, pady=(0, 6))

    pending_inner = tk.Frame(pending_frame)
    pending_inner.pack(fill="x")

    controls = tk.Frame(root)
    controls.pack(fill="x", padx=14, pady=(4, 12))

    active_recording: dict = {"session": None, "user_id": None, "button": None}

    def set_status(message: str, *, error: bool = False) -> None:
        status_var.set(message)
        status_label.config(fg="#C62828" if error else "#37474F")

    def reset_record_button(button: tk.Button) -> None:
        button.config(
            text="Record Voice",
            state="normal",
            bg="SystemButtonFace",
            fg="SystemButtonText",
            activebackground="SystemButtonFace",
            activeforeground="SystemButtonText",
        )

    def on_voice_record_closed(user: dict, button: tk.Button, result) -> None:
        reset_record_button(button)
        active_recording["session"] = None
        active_recording["user_id"] = None
        active_recording["button"] = None

        if result.saved:
            from silva.gui.voice_panel import SetVoiceResult

            enrolled = apply_voice_enrollment(
                SetVoiceResult(
                    saved=True,
                    name=result.name,
                    user_id=result.user_id,
                    wav_file=result.wav_file,
                    cancelled=False,
                )
            )
            if enrolled:
                wav_name = str(result.wav_file).replace("\\", "/").rsplit("/", 1)[-1] or f"{user.get('id')}.wav"
                set_status(
                    f"Voice saved for {enrolled['name']} as {wav_name}. It is in Pending voice samples for that profile."
                )
            else:
                set_status("Voice file saved but profile could not be updated.", error=True)
        elif not result.cancelled:
            set_status("Recording stopped with no saved voice.", error=True)
        refresh_all()

    def start_voice_record(user: dict, button: tk.Button) -> None:
        if not _can_record_voice(get_active_user(), user):
            set_status("You can only record voice for your own profile.", error=True)
            return

        if active_recording.get("session") is not None:
            set_status("Finish the Record Voice popup first.", error=True)
            return

        button.config(text="Recording...", state="disabled")
        set_status(f"Record Voice popup is open for {user.get('name')}. Speak there, then click Save Voice.")

        from silva.audio_recorder import pause_live_listen
        from silva.gui.audio_record_dialog import get_record_dialog_class

        pause_live_listen()
        session = get_record_dialog_class()(
            root,
            user_id=user["id"],
            user_name=user.get("name", "User"),
            on_closed=lambda result, u=user, b=button: on_voice_record_closed(u, b, result),
        )
        active_recording["session"] = session
        active_recording["user_id"] = user["id"]
        active_recording["button"] = button

    def refresh_active_label() -> None:
        user = get_active_user()
        tier = normalize_tier(user.get("tier", 1))
        voice = "voice enrolled" if user.get("voice_enrolled") else "no voice yet"
        for child in active_frame.winfo_children():
            child.destroy()
        tk.Label(
            active_frame,
            text=f"Active profile: {user.get('name', 'Guest')}  |  Tier {tier}  |  {voice}",
            font=body_font,
            fg="#1B5E20" if user.get("voice_enrolled") else "#E65100",
        ).pack(anchor="w")

    def start_face_capture(user: dict) -> None:
        def on_done(ok: bool, message: str) -> None:
            if ok:
                from silva.users.manager import update_user_profile

                update_user_profile(user["id"], face_recognition_future=True)
            set_status(message, error=not ok)
            refresh_all()

        def open_capture() -> None:
            from silva.gui.face_capture_dialog import FaceCaptureDialog

            set_status(f"Opening live camera for {user.get('name')}...")
            FaceCaptureDialog(
                root,
                user_id=user["id"],
                user_name=user.get("name", "User"),
                on_done=on_done,
            )

        from silva.users.camera_access import FEATURE_PROFILE_FACE, is_camera_granted, request_camera_access

        if is_camera_granted(user["id"], FEATURE_PROFILE_FACE):
            open_capture()
            return
        set_status("Allow camera access for face setup in the popup.")
        request_camera_access(
            user["id"],
            FEATURE_PROFILE_FACE,
            parent=root,
            on_result=lambda ok: root.after(0, open_capture if ok else lambda: set_status("Camera access was declined.", error=True)),
        )

    def open_face_photos(user: dict) -> None:
        def on_done(ok: bool, message: str) -> None:
            if ok:
                from silva.users.manager import update_user_profile

                update_user_profile(user["id"], face_recognition_future=True)
            set_status(message, error=not ok)
            refresh_all()

        FacePhotoDialog(
            root,
            user_id=user["id"],
            user_name=user.get("name", "User"),
            on_done=on_done,
        )

    def enroll_face_for_user(user: dict) -> None:
        def on_done(result) -> None:
            if result.passed:
                from silva.users.manager import update_user_profile

                update_user_profile(user["id"], face_recognition_future=True)
                set_status(f"Face ID enrolled for {user.get('name')}.")
            elif result.message != "Cancelled.":
                set_status(result.message, error=True)
            refresh_all()

        def open_scan() -> None:
            set_status(f"Opening camera for {user.get('name')}...")
            FaceScanPanel(
                root,
                user_id=user["id"],
                user_name=user.get("name", "User"),
                enroll=True,
                on_done=on_done,
            )

        from silva.users.camera_access import FEATURE_PROFILE_FACE, is_camera_granted, request_camera_access

        if is_camera_granted(user["id"], FEATURE_PROFILE_FACE):
            open_scan()
            return
        set_status("Allow camera access for face setup in the popup.")
        request_camera_access(
            user["id"],
            FEATURE_PROFILE_FACE,
            parent=root,
            on_result=lambda ok: root.after(0, open_scan if ok else lambda: set_status("Camera access was declined.", error=True)),
        )

    def pick_profile_image(user: dict) -> None:
        from tkinter import filedialog

        from silva.users.profile_image import save_profile_image

        path = filedialog.askopenfilename(
            parent=root,
            title="Choose a profile image",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.webp"), ("All files", "*.*")],
        )
        if not path:
            return
        ok, message = save_profile_image(user["id"], path)
        set_status(message, error=not ok)
        refresh_all()

    def render_users() -> None:
        for child in users_inner.winfo_children():
            child.destroy()

        viewer = get_active_user()
        owner = get_owner()
        users = sorted(list_users(), key=lambda item: (-normalize_tier(item.get("tier", 1)), item.get("name", "")))
        if panel_mode == "self" and self_user_id:
            users = [user for user in users if user.get("id") == self_user_id]
        elif panel_mode == "self":
            users = [user for user in users if user.get("id") == viewer.get("id")]
        recording_id = active_recording.get("user_id")

        for user in users:
            row = tk.Frame(users_inner, relief="groove", bd=1, padx=8, pady=6)
            row.pack(fill="x", pady=4, padx=2)

            active_id = load_store().get("active_user_id")
            name_text = user.get("name", "User")
            if user.get("id") == active_id:
                name_text = f"* {name_text}"

            left = tk.Frame(row)
            left.pack(side="left", fill="x", expand=True)
            tk.Label(left, text=name_text, font=body_font, anchor="w").pack(anchor="w")
            tier = normalize_tier(user.get("tier", 1))
            details = f"Tier {tier} - {tier_description(tier)}"
            if user.get("id") == owner.get("id"):
                details += "  |  Owner"
            tk.Label(left, text=details, font=small_font, fg="#607D8B", anchor="w").pack(anchor="w")
            from silva.users.profile_image import has_profile_image
            from silva.users.voice_id import wav_path as voice_wav

            if has_profile_image(user["id"]):
                tk.Label(
                    left,
                    text="Profile image: custom picture",
                    font=small_font,
                    fg="#1565C0",
                    anchor="w",
                ).pack(anchor="w")

            saved_wav = voice_wav(user["id"])
            has_wav = saved_wav.exists()
            if has_wav:
                voice_label = f"Voice example: {saved_wav.name}"
            elif user.get("voice_enrolled"):
                voice_label = "Voice: enrolled"
            else:
                voice_label = "Voice: not set"
            tk.Label(
                left,
                text=voice_label,
                font=small_font,
                fg="#2E7D32" if has_wav or user.get("voice_enrolled") else "#C62828",
                anchor="w",
            ).pack(anchor="w")

            actions = tk.Frame(row)
            actions.pack(side="right")

            if _can_record_voice(viewer, user):
                is_recording = recording_id == user["id"]
                voice_btn = tk.Button(
                    actions,
                    text="Recording..." if is_recording else "Record Voice",
                    font=small_font,
                    width=11,
                    state="disabled" if is_recording else "normal",
                )
                if is_recording:
                    active_recording["button"] = voice_btn
                voice_btn.config(command=lambda u=user, b=voice_btn: start_voice_record(u, b))
                voice_btn.pack(side="left", padx=2)
                if has_wav:
                    def _play_saved(path=saved_wav) -> None:
                        from silva.audio_recorder import play_wav_file

                        try:
                            play_wav_file(path)
                        except Exception as exc:
                            set_status(str(exc), error=True)

                    tk.Button(
                        actions,
                        text="Play",
                        font=small_font,
                        width=6,
                        command=_play_saved,
                    ).pack(side="left", padx=2)

            if _can_record_voice(viewer, user):
                tk.Button(
                    actions,
                    text="Profile Image",
                    font=small_font,
                    width=12,
                    command=lambda u=user: pick_profile_image(u),
                ).pack(side="left", padx=2)

            face_count = photo_count(user["id"])
            tk.Button(
                actions,
                text="Record Face",
                font=small_font,
                width=11,
                command=lambda u=user: start_face_capture(u),
            ).pack(side="left", padx=2)
            face_btn = tk.Button(
                actions,
                text=f"Face ({face_count})" if face_count else "Face Photos",
                font=small_font,
                width=12,
                command=lambda u=user: open_face_photos(u),
            )
            face_btn.pack(side="left", padx=2)

            if can_edit_user_features(viewer) and editable_features_for_target(viewer, user):
                tk.Button(
                    actions,
                    text="Features",
                    font=small_font,
                    width=9,
                    command=lambda u=user, v=viewer: open_user_features_dialog(root, viewer=v, target=u),
                ).pack(side="left", padx=2)

            tk.Button(
                actions,
                text="Use Profile",
                font=small_font,
                width=10,
                command=lambda uid=user["id"], uname=user.get("name", ""): (
                    identify_and_set_active(uid),
                    set_status(f"Switched to {uname}."),
                    refresh_all(),
                ),
            ).pack(side="left", padx=2)

            if _can_manage_users(viewer) and user.get("id") != owner.get("id") and panel_mode == "owner":
                tk.Button(
                    actions,
                    text="Remove",
                    font=small_font,
                    width=8,
                    command=lambda uid=user["id"], uname=user.get("name", ""): remove_user_prompt(uid, uname),
                ).pack(side="left", padx=2)

    def remove_user_prompt(user_id: str, name: str) -> None:
        if remove_user(user_id):
            set_status(f"Removed {name}.")
            refresh_all()
        else:
            set_status(f"Could not remove {name}.", error=True)

    def render_pending() -> None:
        for child in pending_inner.winfo_children():
            child.destroy()

        viewer = get_active_user()
        if panel_mode == "self":
            return

        if not _can_approve_voice(viewer):
            tk.Label(
                pending_inner,
                text="Only the owner or tier 4+ admins can approve voice samples.",
                font=small_font,
                fg="#607D8B",
            ).pack(anchor="w")
            return

        from silva.users.voice_requests import queue_saved_profile_voices

        try:
            queue_saved_profile_voices()
        except Exception as exc:
            from silva.logger import log_info

            log_info(f"Could not queue saved profile voices: {exc}")
        pending = list_voice_requests()
        if not pending:
            tk.Label(
                pending_inner,
                text="No pending voice samples. Record Voice and the WAV will show here to assign per profile.",
                font=small_font,
                fg="#607D8B",
                wraplength=640,
                justify="left",
            ).pack(anchor="w")
            return

        users = list_users()
        names = {user["id"]: user.get("name", user["id"]) for user in users}
        user_name_list = [user.get("name", user["id"]) for user in users]

        for item in pending[-12:]:
            row = tk.Frame(pending_inner, relief="ridge", bd=1, padx=6, pady=4)
            row.pack(fill="x", pady=3)

            hint = item.get("note") or "Recorded voice sample"
            intended = item.get("intended_user_id") or item.get("best_match_id")
            if intended and intended in names:
                hint += f"  |  for {names[intended]}"
            wav_name = str(item.get("wav_file", "")).replace("\\", "/").rsplit("/", 1)[-1]
            if wav_name:
                hint += f"  |  {wav_name}"
            tk.Label(row, text=hint, font=small_font, anchor="w", wraplength=620, justify="left").pack(
                anchor="w"
            )

            picker = tk.Frame(row)
            picker.pack(fill="x", pady=(4, 0))
            tk.Label(picker, text="Use for profile:", font=small_font).pack(side="left")
            default_name = names.get(intended or "", user_name_list[0] if user_name_list else "")
            var = tk.StringVar(value=default_name)
            menu = tk.OptionMenu(picker, var, *user_name_list)
            menu.config(font=small_font, width=18)
            menu.pack(side="left", padx=6)

            def _play_pending(path=item.get("wav_file", "")) -> None:
                from silva.audio_recorder import play_wav_file

                try:
                    play_wav_file(path)
                except Exception as exc:
                    set_status(str(exc), error=True)

            tk.Button(picker, text="Play", font=small_font, command=_play_pending).pack(side="left", padx=2)
            tk.Button(
                picker,
                text="Use for profile",
                font=small_font,
                command=lambda rid=item["id"], v=var: approve_request(rid, v.get()),
            ).pack(side="left", padx=2)
            tk.Button(
                picker,
                text="Reject",
                font=small_font,
                command=lambda rid=item["id"]: reject_request(rid),
            ).pack(side="left", padx=2)

    def approve_request(request_id: str, user_name: str) -> None:
        store = load_store()
        user_id = next(
            (uid for uid, user in store["users"].items() if user.get("name") == user_name),
            None,
        )
        if user_id is None:
            set_status("Pick a valid user to assign.", error=True)
            return
        approver = get_active_user()
        if approve_voice_request(request_id, user_id, approver_id=approver.get("id", "unknown")):
            identify_and_set_active(user_id)
            set_status(f"Voice sample assigned to {user_name}'s profile.")
            refresh_all()
        else:
            set_status("Could not approve that voice sample.", error=True)

    def reject_request(request_id: str) -> None:
        approver = get_active_user()
        if reject_voice_request(request_id, rejected_by=approver.get("id", "unknown")):
            set_status("Voice sample rejected.")
            refresh_all()
        else:
            set_status("Could not reject that voice sample.", error=True)

    def refresh_all() -> None:
        refresh_active_label()
        render_users()
        render_pending()

    def add_user_dialog() -> None:
        viewer = get_active_user()
        if not _can_manage_users(viewer):
            set_status("Only the owner can add users.", error=True)
            return

        dialog = tk.Toplevel(root)
        dialog.title("Add User")
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        tk.Label(dialog, text="Name", font=body_font).pack(padx=12, pady=(12, 2))
        name_entry = tk.Entry(dialog, font=body_font, width=28)
        name_entry.pack(padx=12, pady=(0, 8))
        name_entry.focus_set()

        tk.Label(dialog, text="Tier (1-5)", font=body_font).pack(padx=12, pady=(0, 2))
        tier_var = tk.StringVar(value="1")
        tier_menu = tk.OptionMenu(dialog, tier_var, "1", "2", "3", "4", "5")
        tier_menu.config(font=body_font, width=10)
        tier_menu.pack(padx=12, pady=(0, 10))

        def save_user() -> None:
            name = name_entry.get().strip()
            if not name:
                return
            tier = int(tier_var.get())
            if tier >= MAX_TIER and name.strip().lower() != get_owner()["name"].lower():
                tier = MAX_TIER - 1
            user = add_user(name, tier=tier)
            set_status(f"Added {user['name']} at tier {user['tier']}.")
            dialog.destroy()
            refresh_all()

        tk.Button(dialog, text="Add", font=body_font, command=save_user, width=12).pack(pady=(0, 12))

    def identify_now() -> None:
        if on_identify is None:
            set_status("Voice check is only available in voice mode.", error=True)
            return
        set_status("Listening for your voice...")
        root.update_idletasks()
        identified = on_identify()
        if identified is None:
            set_status("No voice detected. Try again or use Record Voice on your row.", error=True)
            return
        set_status(f"Recognized {identified.get('name', 'user')}.")
        refresh_all()

    def finish() -> None:
        session = active_recording.get("session")
        if session is not None:
            set_status("Save Voice or Cancel in the Record Voice popup first.", error=True)
            return
        user = get_active_user()
        result["value"] = ProfilePanelResult(
            continued=True,
            active_user_id=user.get("id", "guest"),
            cancelled=False,
        )
        _close_panel()

    def cancel() -> None:
        session = active_recording.get("session")
        if session is not None:
            try:
                session.cancel()
            except tk.TclError:
                pass
        user = get_active_user()
        result["value"] = ProfilePanelResult(
            continued=False,
            active_user_id=user.get("id", "guest"),
            cancelled=True,
        )
        _close_panel()

    def _close_panel() -> None:
        try:
            unregister(root)
            if root.winfo_exists():
                root.destroy()
        except tk.TclError:
            pass
        done = result.get("done")
        if done is not None:
            done.set()
        if result.get("own_loop"):
            try:
                root.quit()
            except tk.TclError:
                pass

    refresh_all()

    if _can_manage_users(get_active_user()) and panel_mode == "owner":
        tk.Button(controls, text="Add User", font=body_font, width=12, command=add_user_dialog).pack(
            side="left", padx=(0, 6)
        )
        tk.Button(
            controls,
            text="Tier Permissions",
            font=body_font,
            width=14,
            command=lambda: open_tier_permissions_dialog(root),
        ).pack(side="left", padx=(0, 6))

    if on_identify is not None:
        tk.Button(controls, text="Identify Me", font=body_font, width=12, command=identify_now).pack(
            side="left", padx=(0, 6)
        )

    tk.Button(
        controls,
        text="Report Bug",
        font=body_font,
        width=11,
        command=lambda: run_bug_report_dialog(get_active_user()),
    ).pack(side="left", padx=(0, 6))

    tk.Button(controls, text="Continue", font=body_font, width=12, command=finish).pack(side="right")
    root.protocol("WM_DELETE_WINDOW", cancel)
    if result.get("own_loop", True):
        root.mainloop()


def run_profile_panel(
    *,
    startup: bool = False,
    panel_mode: str = "owner",
    self_user_id: str | None = None,
    on_identify: IdentifyCallback | None = None,
) -> ProfilePanelResult:
    result: dict = {
        "value": ProfilePanelResult(
            continued=False,
            active_user_id=get_active_user().get("id", "guest"),
            cancelled=True,
        ),
        "done": threading.Event(),
        "own_loop": True,
    }

    def _fallback() -> None:
        _run_panel(
            startup=startup,
            panel_mode=panel_mode,
            self_user_id=self_user_id,
            on_identify=on_identify,
            result=result,
        )

    try:
        from silva.gui.display_host import host_root

        parent = host_root()
    except Exception:
        parent = None

    if parent is not None:
        from silva.logger import log_error

        def _open() -> None:
            try:
                window = tk.Toplevel(parent)
                register(window)
                result["own_loop"] = False
                _run_panel_ui(
                    window,
                    startup=startup,
                    panel_mode=panel_mode,
                    self_user_id=self_user_id,
                    on_identify=on_identify,
                    result=result,
                )
            except tk.TclError as exc:
                log_error("Profile panel hit a Tcl window error", exc=exc)
                result["done"].set()
            except Exception as exc:
                log_error("Profile panel failed", exc=exc)
                result["done"].set()

        try:
            parent.after(0, _open)
            result["done"].wait(timeout=600)
        except tk.TclError:
            _fallback()
    else:
        thread = threading.Thread(target=_fallback, daemon=True)
        thread.start()
        thread.join(timeout=600)

    return result.get(
        "value",
        ProfilePanelResult(
            continued=False,
            active_user_id=get_active_user().get("id", "guest"),
            cancelled=True,
        ),
    )
