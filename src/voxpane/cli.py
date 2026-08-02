"""voxpane command-line interface.

``doctor`` is fully implemented (milestone M0). The remaining subcommands are
declared here so the CLI is self-documenting, and each is wired to its module as
its milestone lands. Until then they print which milestone owns them and exit
non-zero — see ``docs/plans/voxpane-plan.md``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import __version__, doctor

# subcommand -> (milestone, what it will do). Keeps the "not yet built" surface
# honest and points contributors at the right part of the plan.
_PENDING: dict[str, tuple[str, str]] = {
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

    sub.add_parser("start", help="record; then `voxpane stop` transcribes")
    sub.add_parser("stop", help="stop, transcribe, copy transcript to clipboard")
    sub.add_parser("toggle", help="toggle recording — bind to a key [M2]")
    sub.add_parser("daemon", help="run the resident STT daemon [M5]")

    speak = sub.add_parser("speak", help="speak a turn summary [M8]")
    speak.add_argument("text", nargs="?", help="text to speak")
    speak.add_argument("--from-hook", action="store_true", help="read Stop payload from stdin")

    ledger = sub.add_parser("ledger", help="inspect the activity ledger [M6]")
    ledger.add_argument("action", nargs="?", choices=["append", "show", "prune"], default="show")
    ledger.add_argument(
        "--from-hook", action="store_true", help="read PostToolUse payload from stdin"
    )

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


def _log(message: str) -> None:
    """Append a timestamp-free line to the state log; best-effort."""
    from . import paths

    try:
        paths.ensure(paths.state_dir())
        with paths.log_file().open("a") as fh:
            fh.write(message + "\n")
    except OSError:
        pass


def _cmd_start() -> int:
    from . import config, recorder

    try:
        wav = recorder.start(config.load())
    except RuntimeError as exc:
        print(f"voxpane start: {exc}", file=sys.stderr)
        return 1
    print(f"🎙  recording → {wav}\n    speak, then run: voxpane stop")
    return 0


def _cmd_stop() -> int:
    import time

    from . import config, deliver, recorder, transcriber

    cfg = config.load()
    t0 = time.monotonic()

    try:
        wav = recorder.stop()
    except RuntimeError as exc:
        print(f"voxpane stop: {exc}", file=sys.stderr)
        return 1
    if wav is None:
        print("voxpane stop: nothing was recording", file=sys.stderr)
        return 1
    if not wav.exists() or wav.stat().st_size == 0:
        print(f"voxpane stop: no audio captured ({wav})", file=sys.stderr)
        return 1

    try:
        transcript = transcriber.transcribe_file(wav, cfg)
    except RuntimeError as exc:
        print(f"voxpane stop: {exc}", file=sys.stderr)
        return 1
    if not transcript:
        print("voxpane stop: empty transcript", file=sys.stderr)
        return 1

    copied = True
    try:
        deliver.to_clipboard(transcript)
    except (RuntimeError, OSError) as exc:
        copied = False
        print(f"voxpane stop: clipboard failed: {exc}", file=sys.stderr)

    elapsed = time.monotonic() - t0
    _log(f"stop->clipboard {elapsed:.2f}s {len(transcript)}chars copied={copied}")
    print(transcript)
    note = "copied, " if copied else "NOT copied, "
    print(f"\n[{note}{elapsed:.2f}s]", file=sys.stderr)
    return 0


_HANDLERS = {"doctor": lambda: doctor.main(), "start": _cmd_start, "stop": _cmd_stop}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0
    handler = _HANDLERS.get(args.command)
    if handler is not None:
        return handler()
    return _pending(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
