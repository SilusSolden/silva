import argparse
import subprocess
import sys

from silva.assistant import SilvaAssistant


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="silva",
        description="Silva - local voice assistant with TTS and command support.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--voice",
        action="store_true",
        default=True,
        help="Use microphone for voice input (default)",
    )
    mode.add_argument(
        "--type",
        "-t",
        action="store_true",
        help="Use keyboard typing instead of voice",
    )
    parser.add_argument(
        "--dev-panel",
        action="store_true",
        help="Open the Silva developer panel (test, train, live update)",
    )
    parser.add_argument(
        "--with-dev-panel",
        action="store_true",
        help="Run Silva and open the developer panel beside it",
    )
    parser.add_argument(
        "--live-chat",
        action="store_true",
        help="Open the standalone Silva live chat popup",
    )
    parser.add_argument(
        "--console",
        action="store_true",
        help="Keep the Silva window visible so you can read it or close it.",
    )
    parser.add_argument(
        "--stream-deck",
        action="store_true",
        help="Stream Deck button: start Silva, or show the window if it is already running.",
    )
    parser.add_argument(
        "--resume-sleep",
        action="store_true",
        help="Stay-active restart: come back in sleep mode without speaking.",
    )
    parser.add_argument(
        "--deck-slot",
        nargs=2,
        metavar=("PAGE", "SLOT"),
        help="Print the JSON action bound to a Stream Deck page and slot.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.deck_slot:
        import json

        from silva.dev.stream_deck import resolve_slot_action
        from silva.users.manager import get_active_user

        try:
            page, slot = (int(value) for value in args.deck_slot)
        except ValueError:
            page, slot = 0, 0
        action = resolve_slot_action(user_id=str(get_active_user().get("id") or "guest"), page=page, slot=slot)
        print(json.dumps(action))
        return

    if args.stream_deck:
        from silva.launch import launch_or_show

        raise SystemExit(launch_or_show())

    if args.dev_panel and not args.with_dev_panel:
        from silva.gui.dev_panel import run_dev_panel

        run_dev_panel()
        return

    if args.live_chat:
        from silva.gui.live_chat_popup import run_live_chat_popup

        run_live_chat_popup()
        return

    voice_mode = not args.type

    if args.with_dev_panel:
        import subprocess
        import sys

        subprocess.Popen([sys.executable, "-m", "silva", "--dev-panel"])

    SilvaAssistant(voice_mode=voice_mode, resume_sleep=args.resume_sleep).run()


if __name__ == "__main__":
    main()
