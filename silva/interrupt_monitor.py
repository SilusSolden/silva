"""Interrupt typing bar and voice monitoring during long Silva responses."""

from __future__ import annotations

import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable

from silva.config import load_config
from silva.gui.display_manager import is_shutting_down, register, unregister, watch_shutdown
from silva.gui.monitors import geometry_on_monitor
from silva.interrupt import is_interrupt_command
from silva.logger import log_info
from silva.commands.intent import is_action_command
from silva.stt_quick_commands import is_complete_command
from silva.wake import is_sleep_command

CommandCallback = Callable[[str], None]


class InterruptBar:
    """Compact typing bar for long Silva responses."""

    def __init__(
        self,
        on_interrupt,
        *,
        on_command: CommandCallback | None = None,
    ) -> None:
        self._on_interrupt = on_interrupt
        self._on_command = on_command
        self._thread: threading.Thread | None = None
        self._root: tk.Tk | None = None
        self._closed = threading.Event()

    def start(self) -> None:
        if is_shutting_down():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def close(self) -> None:
        if self._root is not None:
            try:
                self._root.after(0, self._destroy_root)
            except Exception:
                self._destroy_root()
        self._closed.wait(timeout=1.0)

    def _destroy_root(self) -> None:
        if self._root is None:
            return
        try:
            unregister(self._root)
            self._root.quit()
        except Exception:
            pass
        try:
            self._root.destroy()
        except Exception:
            pass
        self._root = None
        self._closed.set()

    def _run(self) -> None:
        if is_shutting_down():
            self._closed.set()
            return

        root = tk.Tk()
        self._root = root
        register(root)
        watch_shutdown(root)
        root.bind("<Destroy>", lambda _event: unregister(root))
        root.title("Silva")
        root.resizable(False, False)

        width = int(load_config().get("interrupt_bar_width", 300))
        height = int(load_config().get("interrupt_bar_height", 54))
        root.geometry(geometry_on_monitor(width, height, anchor="se", margin=16))

        body_font = tkfont.Font(family="Segoe UI", size=9)
        entry_font = tkfont.Font(family="Segoe UI", size=9)

        frame = tk.Frame(root, padx=8, pady=6)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text="Talking — type a command, or stop",
            font=body_font,
            fg="#455A64",
        ).pack(anchor="w")

        entry = tk.Entry(frame, font=entry_font)
        entry.pack(fill="x", pady=(4, 0))
        entry.focus_set()

        def submit() -> None:
            text = entry.get().strip()
            if not text:
                return
            if is_interrupt_command(text) or is_sleep_command(text):
                self._on_interrupt("typed", command=text)
                self._destroy_root()
                return
            if is_action_command(text) or is_complete_command(text):
                if self._on_command is not None:
                    self._on_command(text)
                entry.delete(0, tk.END)

        entry.bind("<Return>", lambda _event: submit())
        root.protocol("WM_DELETE_WINDOW", self._destroy_root)
        root.mainloop()
        self._closed.set()


class InterruptMonitor:
    """Listen for spoken or typed commands while output is active."""

    def __init__(
        self,
        *,
        voice_mode: bool,
        stt,
        show_bar: bool = False,
        on_parallel_command: CommandCallback | None = None,
    ) -> None:
        self._voice_mode = voice_mode
        self._stt = stt
        self._show_bar = show_bar
        self._on_parallel_command = on_parallel_command
        self._bar_delay = float(load_config().get("interrupt_bar_delay_seconds", 4.0))
        self._stop_event = threading.Event()
        self._interrupted = threading.Event()
        self._source = ""
        self._bar: InterruptBar | None = None
        self._bar_thread: threading.Thread | None = None
        self._voice_thread: threading.Thread | None = None
        self._priority_command: str | None = None

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    def start(self) -> None:
        if is_shutting_down():
            return
        if self._voice_mode and self._stt is not None:
            self._voice_thread = threading.Thread(
                target=self._voice_loop,
                daemon=True,
                name="silva-stop-listen",
            )
            self._voice_thread.start()
        if self._show_bar:
            self._bar_thread = threading.Thread(target=self._run_bar_delayed, daemon=True)
            self._bar_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._bar is not None:
            self._bar.close()
        if self._bar_thread is not None:
            self._bar_thread.join(timeout=0.2)
        if self._voice_thread is not None:
            self._voice_thread.join(timeout=1.0)

    def was_interrupted(self) -> bool:
        return self._interrupted.is_set()

    @property
    def source(self) -> str:
        return self._source

    @property
    def priority_command(self) -> str | None:
        return self._priority_command

    def _run_bar_delayed(self) -> None:
        delay = max(0.0, self._bar_delay)
        if delay:
            time.sleep(delay)
        if self._stop_event.is_set() or self._interrupted.is_set() or is_shutting_down():
            return
        self._bar = InterruptBar(self._trigger, on_command=self._handle_parallel)
        self._bar.start()

    def _trigger(self, source: str, command: str | None = None) -> None:
        if self._interrupted.is_set():
            return
        if command:
            self._priority_command = command
        self._source = source
        self._interrupted.set()
        self._stop_event.set()
        log_info(f"User interrupted Silva output ({source})")

    def _is_end_session(self, text: str) -> bool:
        from silva.close_phrases import is_close_command

        return is_close_command(text)

    def _handle_parallel(self, text: str) -> None:
        if is_interrupt_command(text) or is_sleep_command(text) or self._is_end_session(text):
            self._trigger("command", command=text)
            return
        if self._on_parallel_command is None:
            self._priority_command = text
            self._trigger("voice-priority")
            return
        log_info(f"Parallel command while speaking: {text[:120]}")
        self._on_parallel_command(text)

    def _voice_loop(self) -> None:
        from silva.interrupt_listen import voice_stop_loop

        voice_stop_loop(self)
