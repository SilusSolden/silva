"""Speak a short last-crash reason and open a .txt dump when the details are technical."""

from __future__ import annotations

from silva.logger import log_command, log_info


def handle_crash_report_speech(assistant, text: str) -> bool:
    if not text or not str(text).strip():
        return False

    from silva.commands.crash_report_phrases import (
        is_command_fail_ask,
        is_crash_report_ask,
        wants_crash_file,
    )

    command_ask = is_command_fail_ask(text)
    if not command_ask and not is_crash_report_ask(text):
        return False

    from silva.crash_record import explain_last_command_fail, explain_last_crash

    if command_ask:
        log_command("command_fail_report", query=text[:120])
        report = explain_last_command_fail()
        log_info(f"Command-fail report: {report.kind} file={report.path}")
    else:
        log_command("crash_report", query=text[:120])
        report = explain_last_crash()
        log_info(f"Crash report: {report.kind} file={report.path}")
    assistant.say(report.spoken, interruptible=True)
    if report.open_file or wants_crash_file(text):
        from silva.commands.news_display import open_briefing_txt

        try:
            open_briefing_txt(report.path, auto_close_minutes=0)
        except FileNotFoundError:
            assistant.say("I could not open the text file.", interruptible=False)
    return True
