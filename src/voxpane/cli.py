"""voxpane command-line interface.

``doctor`` is fully implemented (milestone M0). The remaining subcommands are
declared here so the CLI is self-documenting, and each is wired to its module as
its milestone lands. Until then they print which milestone owns them and exit
non-zero — see ``docs/plans/voxpane-plan.md``.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from . import __version__, doctor

# subcommand -> (milestone, what it will do). Keeps the "not yet built" surface
# honest and points contributors at the right part of the plan.
_PENDING: dict[str, tuple[str, str]] = {
    "start": ("M1", "record one shot, transcribe, deliver the transcript"),
    "stop": ("M1", "stop recording (SIGINT), transcribe, deliver"),
    "toggle": ("M2", "flip recording state — bind this to SUPER ALT V"),
    "daemon": ("M5", "run voxpaned with the model resident in RAM"),
    "speak": ("M8", "summarise a turn and speak it on the Echo Dot"),
    "ledger": ("M6", "append to / show / prune the activity ledger"),
    "install-hooks": ("M6", "merge voxpane hooks into ~/.claude/settings.json"),
    "install-bindings": ("M2", "install the Hyprland keybinding idempotently"),
    "vocab": ("M9", "build an initial_prompt addendum from the current repo"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voxpane",
        description="Talk to Claude Code; have your Echo Dot say what it did.",
        epilog="Run 'voxpane doctor' first. Full spec: docs/plans/voxpane-plan.md",
    )
    parser.add_argument("--version", action="version", version=f"voxpane {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("doctor", help="check the environment is ready [M0]")

    sub.add_parser("start", help="record one shot, transcribe, deliver [M1]")
    sub.add_parser("stop", help="stop recording and deliver [M1]")
    sub.add_parser("toggle", help="toggle recording — bind to a key [M2]")
    sub.add_parser("daemon", help="run the resident STT daemon [M5]")

    speak = sub.add_parser("speak", help="speak a turn summary [M8]")
    speak.add_argument("text", nargs="?", help="text to speak")
    speak.add_argument("--from-hook", action="store_true", help="read Stop payload from stdin")

    ledger = sub.add_parser("ledger", help="inspect the activity ledger [M6]")
    ledger.add_argument("action", nargs="?", choices=["append", "show", "prune"], default="show")
    ledger.add_argument("--from-hook", action="store_true", help="read PostToolUse payload from stdin")

    sub.add_parser("install-hooks", help="install Claude Code hooks [M6]")
    sub.add_parser("install-bindings", help="install the Hyprland keybind [M2]")

    vocab = sub.add_parser("vocab", help="build a repo vocabulary prompt [M9]")
    vocab.add_argument("--from-repo", action="store_true")

    return parser


def _pending(command: str) -> int:
    milestone, description = _PENDING[command]
    print(
        f"voxpane {command}: not built yet — {description}.\n"
        f"This is milestone {milestone}. See docs/plans/voxpane-plan.md, or run\n"
        f"the 'voxpane' skill in Claude Code to implement it.",
        file=sys.stderr,
    )
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "doctor":
        return doctor.main()
    return _pending(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
