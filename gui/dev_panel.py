"""Silva developer panel — test, train speech, and live-update features."""

from __future__ import annotations

import json
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, scrolledtext, ttk

from silva.config import load_config
from silva.dev.live_update import queue_live_update, read_progress
from silva.dev.panel_instance import consume_panel_tab_request
from silva.dev.paths import DEV_STATE_FILE, ensure_dev_dir
from silva.dev.speech_training import load_speech_training, phrases_to_text, save_speech_training
from silva.dev.test_runner import run_all_tests
from silva.gui.display_manager import register, unregister


def _save_dev_state(state: dict) -> None:
    ensure_dev_dir()
    DEV_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _load_dev_state() -> dict:
    ensure_dev_dir()
    if not DEV_STATE_FILE.exists():
        return {}
    try:
        data = json.loads(DEV_STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


class DevPanelApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        register(self.root)
        self.root.title("Silva System Panel")
        self.root.geometry("760x680")
        self.root.minsize(640, 560)

        self._title_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        self._body_font = tkfont.Font(family="Segoe UI", size=10)
        self._mono_font = tkfont.Font(family="Consolas", size=9)

        self._tests_passed = False
        self._training_saved = False
        self._last_test_label = "Tests not run yet."
        self._poll_job: str | None = None
        self._focus_poll_job: str | None = None
        self._last_scan = None
        self._panel_user = None
        self._can_publish = False

        self._build_ui()
        self._load_training_fields()
        self._restore_session()
        self._init_panel_access()
        self._refresh_confirm_state()
        self._apply_panel_tab_request()
        self._focus_poll_job = self.root.after(500, self._poll_panel_tab_request)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        header = tk.Label(
            self.root,
            text="Silva System Panel",
            font=self._title_font,
            fg="#1A237E",
        )
        header.pack(pady=(10, 2))
        tk.Label(
            self.root,
            text="Run beside Silva to test commands, train phrases, and push live updates.",
            font=self._body_font,
            fg="#455A64",
        ).pack(pady=(0, 8))

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=6)
        self._notebook = notebook

        self._test_tab = tk.Frame(notebook)
        self._train_tab = tk.Frame(notebook)
        self._update_tab = tk.Frame(notebook)
        notebook.add(self._test_tab, text="1. Test")
        notebook.add(self._train_tab, text="2. Train")
        notebook.add(self._update_tab, text="3. Live Update")

        self._build_test_tab()
        self._build_train_tab()
        self._build_update_tab()
        self._build_extension_tabs()

    def _build_extension_tabs(self) -> None:
        from silva.dev.panel_registry import built_in_panel_tabs, load_extension_tab_specs
        from silva.gui.panel_security_tabs import register_panel_tabs

        register_panel_tabs()
        for spec in built_in_panel_tabs():
            frame = tk.Frame(self._notebook)
            self._notebook.add(frame, text=spec.title)
            spec.builder(self, frame)

        for ext in load_extension_tab_specs():
            frame = tk.Frame(self._notebook)
            title = str(ext.get("title") or ext.get("id") or "Extension")
            self._notebook.add(frame, text=title)
            tk.Label(
                frame,
                text=str(ext.get("description") or "Reserved for a future Silva feature."),
                font=self._body_font,
                wraplength=680,
                justify="left",
            ).pack(anchor="w", padx=12, pady=12)
            notes = ext.get("notes")
            if notes:
                box = scrolledtext.ScrolledText(frame, font=self._mono_font, height=12, wrap="word")
                box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
                box.insert("1.0", str(notes))
                box.config(state="disabled")

    def _build_test_tab(self) -> None:
        bar = tk.Frame(self._test_tab)
        bar.pack(fill="x", padx=8, pady=8)

        tk.Button(bar, text="Run All Tests", command=self._run_tests, width=16).pack(side="left", padx=4)
        tk.Button(bar, text="Test Before Update", command=lambda: self._run_tests(before_update=True), width=18).pack(
            side="left", padx=4
        )
        tk.Button(bar, text="Test After Update", command=lambda: self._run_tests(after_update=True), width=18).pack(
            side="left", padx=4
        )

        self._test_status = tk.Label(self._test_tab, text=self._last_test_label, font=self._body_font, fg="#37474F")
        self._test_status.pack(fill="x", padx=10)

        self._test_output = scrolledtext.ScrolledText(
            self._test_tab,
            font=self._mono_font,
            wrap="word",
            height=24,
        )
        self._test_output.pack(fill="both", expand=True, padx=8, pady=8)

    def _build_train_tab(self) -> None:
        tk.Label(
            self._train_tab,
            text="Phrases Silva should recognize (one per line):",
            font=self._body_font,
        ).pack(anchor="w", padx=10, pady=(8, 2))
        self._say_box = scrolledtext.ScrolledText(self._train_tab, font=self._body_font, height=8)
        self._say_box.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        tk.Label(
            self._train_tab,
            text="Phrases Silva should ignore (one per line):",
            font=self._body_font,
        ).pack(anchor="w", padx=10, pady=(0, 2))
        self._dont_say_box = scrolledtext.ScrolledText(self._train_tab, font=self._body_font, height=8)
        self._dont_say_box.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        bar = tk.Frame(self._train_tab)
        bar.pack(fill="x", padx=10, pady=8)
        tk.Button(bar, text="Save Training", command=self._save_training, width=16).pack(side="left")
        self._train_status = tk.Label(bar, text="", font=self._body_font, fg="#37474F")
        self._train_status.pack(side="left", padx=12)

    def _build_update_tab(self) -> None:
        tk.Label(
            self._update_tab,
            text="Enabled features (one per line, applied on live update):",
            font=self._body_font,
        ).pack(anchor="w", padx=10, pady=(10, 2))

        self._features_box = scrolledtext.ScrolledText(self._update_tab, font=self._body_font, height=6)
        self._features_box.pack(fill="x", padx=10, pady=(0, 8))

        confirm = tk.LabelFrame(self._update_tab, text="Confirm before update", font=self._body_font)
        confirm.pack(fill="x", padx=10, pady=6)

        self._tests_ok_var = tk.BooleanVar(value=False)
        self._train_ok_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            confirm,
            text="Tests passed",
            variable=self._tests_ok_var,
            state="disabled",
            font=self._body_font,
        ).pack(anchor="w", padx=8, pady=2)
        tk.Checkbutton(
            confirm,
            text="Training saved",
            variable=self._train_ok_var,
            state="disabled",
            font=self._body_font,
        ).pack(anchor="w", padx=8, pady=2)

        bar = tk.Frame(self._update_tab)
        bar.pack(fill="x", padx=10, pady=8)
        self._scan_btn = tk.Button(
            bar,
            text="Scan Changes",
            command=self._scan_changes,
            width=16,
        )
        self._scan_btn.pack(side="left", padx=(0, 8))
        self._update_btn = tk.Button(
            bar,
            text="Update Silva",
            command=self._apply_live_update,
            width=18,
            state="disabled",
        )
        self._update_btn.pack(side="left")

        self._access_status = tk.Label(
            self._update_tab,
            text="",
            font=self._body_font,
            fg="#455A64",
            wraplength=700,
            justify="left",
        )
        self._access_status.pack(fill="x", padx=10, pady=(0, 4))

        self._progress = ttk.Progressbar(self._update_tab, orient="horizontal", mode="determinate", maximum=100)
        self._progress.pack(fill="x", padx=10, pady=6)

        self._update_status = tk.Label(self._update_tab, text="Ready.", font=self._body_font, fg="#37474F")
        self._update_status.pack(fill="x", padx=10, pady=(0, 8))

        self._update_log = scrolledtext.ScrolledText(self._update_tab, font=self._mono_font, height=10, wrap="word")
        self._update_log.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _load_training_fields(self) -> None:
        data = load_speech_training()
        self._say_box.delete("1.0", tk.END)
        self._dont_say_box.delete("1.0", tk.END)
        self._say_box.insert("1.0", phrases_to_text(data.get("say_phrases", [])))
        self._dont_say_box.insert("1.0", phrases_to_text(data.get("dont_say_phrases", [])))

    def _default_features_text(self) -> str:
        from silva.dev.paths import APPLIED_UPDATE_FILE

        if APPLIED_UPDATE_FILE.exists():
            try:
                applied = json.loads(APPLIED_UPDATE_FILE.read_text(encoding="utf-8"))
                features = applied.get("features")
                if isinstance(features, list) and features:
                    return "\n".join(str(item) for item in features)
            except (json.JSONDecodeError, OSError):
                pass
        features = load_config().get("universal_features", [])
        if isinstance(features, list):
            return "\n".join(str(item) for item in features)
        return ""

    def _restore_session(self) -> None:
        state = _load_dev_state()
        self._tests_passed = bool(state.get("tests_passed"))
        self._training_saved = bool(state.get("training_saved"))

        last_status = state.get("last_test_status")
        if last_status:
            self._last_test_label = str(last_status)
            color = "#2E7D32" if self._tests_passed else "#C62828"
            self._test_status.config(text=self._last_test_label, fg=color)

        output = state.get("last_test_output", "")
        if output:
            self._test_output.insert("1.0", output)

        features_text = state.get("features_text")
        if features_text:
            self._features_box.insert("1.0", str(features_text))
        else:
            default = self._default_features_text()
            if default:
                self._features_box.insert("1.0", default)

        train_note = state.get("training_updated_at")
        if train_note and self._training_saved:
            self._train_status.config(text=f"Last saved: {train_note}", fg="#2E7D32")

        update_log = state.get("last_update_log", "")
        if update_log:
            self._update_log.insert("1.0", update_log)

        progress = read_progress()
        percent = int(progress.get("percent", 0))
        if percent:
            self._progress["value"] = percent
            step = progress.get("step", "Ready")
            self._update_status.config(text=f"{step} ({percent}%)")

        tab = state.get("selected_tab", 0)
        try:
            self._notebook.select(int(tab))
        except (tk.TclError, TypeError, ValueError):
            pass

        geometry = state.get("window_geometry")
        if geometry:
            try:
                self.root.geometry(str(geometry))
            except tk.TclError:
                pass

    def _persist_session(self) -> None:
        try:
            selected_tab = self._notebook.index(self._notebook.select())
        except tk.TclError:
            selected_tab = 0

        state = _load_dev_state()
        state.update(
            {
                "tests_passed": self._tests_passed,
                "training_saved": self._training_saved,
                "last_test_status": self._test_status.cget("text"),
                "last_test_output": self._test_output.get("1.0", tk.END).strip()[:50000],
                "features_text": self._features_box.get("1.0", tk.END).strip(),
                "selected_tab": selected_tab,
                "window_geometry": self.root.geometry(),
                "last_update_log": self._update_log.get("1.0", tk.END).strip()[-20000:],
            }
        )
        _save_dev_state(state)
        save_speech_training(
            say_text=self._say_box.get("1.0", tk.END),
            dont_say_text=self._dont_say_box.get("1.0", tk.END),
        )

    def _refresh_confirm_state(self) -> None:
        from silva.dev.panel_update import owner_quick_update_enabled

        self._tests_ok_var.set(self._tests_passed)
        self._train_ok_var.set(self._training_saved)
        ready = False
        if self._can_publish and self._last_scan is not None and self._last_scan.has_changes:
            if owner_quick_update_enabled() or (self._tests_passed and self._training_saved):
                ready = True
        elif self._tests_passed and self._training_saved:
            ready = True

        if self._can_publish:
            self._update_btn.config(state="normal" if ready else "disabled")
        else:
            self._update_btn.config(state="disabled")

    def _append_test_output(self, text: str) -> None:
        self._test_output.insert(tk.END, text + "\n")
        self._test_output.see(tk.END)

    def _append_update_log(self, text: str) -> None:
        self._update_log.insert(tk.END, text + "\n")
        self._update_log.see(tk.END)

    def _run_tests(self, *, before_update: bool = False, after_update: bool = False) -> None:
        label = "Running all tests..."
        if before_update:
            label = "Running pre-update tests..."
        if after_update:
            label = "Running post-update tests..."
        self._test_status.config(text=label)
        self._test_output.delete("1.0", tk.END)
        self._append_test_output(label)

        def worker() -> None:
            result = run_all_tests(include_unit_tests=True)

            def finish() -> None:
                self._test_output.delete("1.0", tk.END)
                self._append_test_output(result.output)
                if result.broken_items:
                    self._append_test_output("")
                    self._append_test_output("=== Broken items ===")
                    for item in result.broken_items:
                        self._append_test_output(item)

                self._tests_passed = result.passed
                if result.passed:
                    status = f"PASSED — {result.tests_run} unit tests, all scenarios OK."
                else:
                    status = (
                        f"FAILED — {len(result.broken_items)} issue(s), "
                        f"{result.failures} failures, {result.errors} errors."
                    )
                self._test_status.config(text=status, fg="#2E7D32" if result.passed else "#C62828")
                self._refresh_confirm_state()

                state = _load_dev_state()
                state["tests_passed"] = result.passed
                state["last_test_status"] = status
                state["last_test_output"] = result.output
                if before_update:
                    state["pre_update_passed"] = result.passed
                if after_update:
                    state["post_update_passed"] = result.passed
                _save_dev_state(state)

            self.root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def _init_panel_access(self) -> None:
        from silva.dev.panel_update import can_publish_system_update, panel_update_user
        from silva.users.manager import is_owner

        self._panel_user = panel_update_user()
        self._can_publish = can_publish_system_update(self._panel_user)
        name = self._panel_user.get("name", "User")
        if self._can_publish:
            role = "Owner" if is_owner(self._panel_user) else "Admin"
            self._access_status.config(
                text=(
                    f"Signed in as {name} ({role}). Scan your manual changes, then click Update Silva "
                    "to push them to the running assistant."
                ),
                fg="#2E7D32",
            )
        else:
            self._access_status.config(
                text="Only the owner or tier 4 admins can publish updates from this panel.",
                fg="#C62828",
            )
            self._scan_btn.config(state="disabled")
            self._update_btn.config(state="disabled")

    def _scan_changes(self) -> None:
        if not self._can_publish:
            messagebox.showwarning("Not allowed", "Only the owner or admins can scan and publish updates.")
            return

        from silva.dev.panel_update import format_scan_report, scan_panel_changes

        self._save_training(show_message=False)
        features = self._parse_features()
        scan = scan_panel_changes(features=features)
        self._last_scan = scan
        report = format_scan_report(scan)
        self._update_log.delete("1.0", tk.END)
        self._append_update_log(report)
        if scan.has_changes:
            self._update_status.config(text="Changes found. Click Update Silva to publish.", fg="#2E7D32")
        else:
            self._update_status.config(text="No new manual changes detected.", fg="#37474F")
        self._refresh_confirm_state()

    def _save_training(self, *, show_message: bool = True) -> None:
        payload = save_speech_training(
            say_text=self._say_box.get("1.0", tk.END),
            dont_say_text=self._dont_say_box.get("1.0", tk.END),
        )
        self._training_saved = True
        if show_message:
            self._train_status.config(
                text=f"Saved {len(payload['say_phrases'])} say / {len(payload['dont_say_phrases'])} don't-say phrases.",
                fg="#2E7D32",
            )
        self._refresh_confirm_state()

        state = _load_dev_state()
        state["training_saved"] = True
        state["training_updated_at"] = payload.get("updated_at", "")
        state["features_text"] = self._features_box.get("1.0", tk.END).strip()
        _save_dev_state(state)

    def _parse_features(self) -> list[str]:
        lines = []
        for raw in self._features_box.get("1.0", tk.END).splitlines():
            item = raw.strip()
            if item and not item.startswith("#"):
                lines.append(item)
        return lines

    def _apply_live_update(self) -> None:
        if not self._can_publish:
            messagebox.showwarning("Not allowed", "Only the owner or admins can publish updates.")
            return

        from silva.dev.panel_update import (
            format_scan_report,
            owner_quick_update_enabled,
            publish_panel_update,
            scan_panel_changes,
        )

        self._save_training(show_message=False)
        features = self._parse_features()
        scan = self._last_scan or scan_panel_changes(features=features)
        if not scan.has_changes:
            scan = scan_panel_changes(features=features)
        self._last_scan = scan

        tests_ok = self._tests_passed and self._training_saved
        if not scan.has_changes and not tests_ok:
            messagebox.showwarning(
                "Nothing to update",
                "Scan found no manual changes. Edit files or training, click Scan Changes, then update.",
            )
            return

        if not tests_ok and not (owner_quick_update_enabled() and scan.has_changes):
            messagebox.showwarning(
                "Not ready",
                "Run tests and save training, or scan for manual changes as owner/admin.",
            )
            return

        summary = "\n".join(f"- {item}" for item in scan.changes[:8])
        if not messagebox.askyesno(
            "Update Silva",
            "Publish these changes to the running Silva assistant?\n\n" + summary,
        ):
            return

        manifest, scan = publish_panel_update(features=features, changelog=list(scan.changes))
        queue_live_update(features=features)

        from silva.dev.live_update import apply_pending_update
        from silva.notifications.dispatch import notify_owner_async

        ok, message = apply_pending_update()
        notify_owner_async(
            f"Silva update {manifest.get('version', '')} published from the System Panel.",
            reason="silva_update_publish",
            prefer_telegram=True,
        )
        state = _load_dev_state()
        state["features_text"] = "\n".join(features)
        _save_dev_state(state)
        self._progress["value"] = 100 if ok else 0
        status = "Update applied." if ok else "Update queued for running Silva."
        self._update_status.config(text=status, fg="#2E7D32" if ok else "#37474F")
        self._append_update_log(format_scan_report(scan))
        self._append_update_log(message)
        self._last_scan = scan_panel_changes(features=features)
        self._refresh_confirm_state()
        if not ok:
            self._start_progress_poll()

    def _start_progress_poll(self) -> None:
        if self._poll_job is not None:
            self.root.after_cancel(self._poll_job)
        self._poll_job = self.root.after(300, self._poll_progress)

    def _poll_progress(self) -> None:
        progress = read_progress()
        percent = int(progress.get("percent", 0))
        step = progress.get("step", "Working")
        done = bool(progress.get("done"))
        error = progress.get("error", "")

        self._progress["value"] = percent
        if error:
            self._update_status.config(text=f"{step} — {error}", fg="#C62828")
        else:
            self._update_status.config(text=f"{step} ({percent}%)", fg="#37474F")

        if done:
            if error:
                self._append_update_log(f"Update failed: {error}")
            else:
                self._append_update_log("Update complete.")
            self._poll_job = None
            return

        self._poll_job = self.root.after(300, self._poll_progress)

    def _select_named_tab(self, tab_id: str, title: str) -> bool:
        target_id = str(tab_id or "").strip().lower()
        target_title = str(title or "").strip()
        if not target_id and not target_title:
            return False

        from silva.dev.panel_registry import built_in_panel_tabs

        candidates = [
            ("test", "1. Test"),
            ("train", "2. Train"),
            ("live_update", "3. Live Update"),
        ]
        candidates.extend((spec.id, spec.title) for spec in built_in_panel_tabs())

        for key, label in candidates:
            if (target_id and target_id == key) or (target_title and target_title == label):
                for widget in self._notebook.tabs():
                    if str(self._notebook.tab(widget, "text")) == label:
                        self._notebook.select(widget)
                        return True
        return False

    def _apply_panel_tab_request(self) -> bool:
        request = consume_panel_tab_request()
        if not request:
            return False
        selected = self._select_named_tab(
            str(request.get("tab_id") or ""),
            str(request.get("title") or ""),
        )
        if selected:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(300, lambda: self.root.attributes("-topmost", False))
        return selected

    def _poll_panel_tab_request(self) -> None:
        self._apply_panel_tab_request()
        self._focus_poll_job = self.root.after(500, self._poll_panel_tab_request)

    def _on_close(self) -> None:
        if self._poll_job is not None:
            self.root.after_cancel(self._poll_job)
        if self._focus_poll_job is not None:
            self.root.after_cancel(self._focus_poll_job)
        self._persist_session()
        unregister(self.root)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def _log_panel_error(exc: BaseException) -> None:
    from silva.logger import log_path

    try:
        log_file = log_path().parent / "system_panel.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as handle:
            handle.write(f"System panel error: {exc}\n")
    except OSError:
        pass


def run_dev_panel() -> None:
    from silva.dev.panel_instance import PANEL_LOCK_FILE, acquire_panel_instance, focus_existing_panel, hide_console_window

    hide_console_window()

    if not acquire_panel_instance():
        if focus_existing_panel():
            return
        PANEL_LOCK_FILE.unlink(missing_ok=True)
        if not acquire_panel_instance():
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Silva System Panel",
                "Could not open the system panel. Check ~/.silva/logs/system_panel.log",
            )
            root.destroy()
            return

    try:
        DevPanelApp().run()
    except Exception as exc:
        _log_panel_error(exc)
        raise
