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
    "daemon": ("M5", "run voxpaned with the model resident in RAM"),
    "speak": ("M8", "summarise a turn and speak it on the Echo Dot"),
    "ledger": ("M6", "append to / show / prune the activity ledger"),
    "install-hooks": ("M6", "merge voxpane hooks into ~/.claude/settings.json"),
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
    sub.add_parser("toggle", help="toggle recording on/off — bind this to a key")
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
    sub.add_parser("install-bindings", help="install the Hyprland keybind (SUPER ALT V)")

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


def _preview(text: str, max_chars: int = 120) -> str:
    """A compact one/two-line preview for a notification body."""
    collapsed = " ".join(text.split())
    if len(collapsed) > max_chars:
        collapsed = collapsed[: max_chars - 1].rstrip() + "…"
    return collapsed


def _start_recording(cfg) -> int:
    from . import notify, recorder

    try:
        wav = recorder.start(cfg)
    except RuntimeError as exc:
        notify.notify("voxpane", str(exc), replace_id=notify.RECORDING_ID, urgency="critical")
        print(f"voxpane: {exc}", file=sys.stderr)
        return 1
    notify.notify(
        "🎙  Recording…",
        "Speak, then trigger voxpane again.",
        replace_id=notify.RECORDING_ID,
        expire_ms=0,  # persistent until replaced
    )
    print(f"🎙  recording → {wav}\n    speak, then run: voxpane stop")
    return 0


def _stop_and_deliver(cfg) -> int:
    import time

    from . import deliver, notify, recorder, transcriber

    t0 = time.monotonic()

    def fail(msg: str, *, critical: bool = False) -> int:
        notify.notify(
            "voxpane",
            msg,
            replace_id=notify.RECORDING_ID,
            urgency="critical" if critical else "normal",
        )
        print(f"voxpane: {msg}", file=sys.stderr)
        return 1

    try:
        wav = recorder.stop()
    except RuntimeError as exc:
        return fail(str(exc), critical=True)
    if wav is None:
        return fail("nothing was recording")
    if not wav.exists() or wav.stat().st_size == 0:
        return fail(f"no audio captured ({wav})", critical=True)

    notify.notify("⏳  Transcribing…", "", replace_id=notify.RECORDING_ID, expire_ms=0)
    try:
        transcript = transcriber.transcribe_file(wav, cfg)
    except RuntimeError as exc:
        return fail(str(exc), critical=True)
    if not transcript:
        return fail("empty transcript")

    ok = True
    try:
        status = deliver.deliver(transcript, cfg, submit=cfg["delivery"]["auto_submit"])
    except (RuntimeError, OSError) as exc:
        ok = False
        status = f"delivery failed: {exc}"
        print(f"voxpane: {status}", file=sys.stderr)

    elapsed = time.monotonic() - t0
    _log(f"stop->deliver {elapsed:.2f}s {len(transcript)}chars {status}")
    notify.notify(
        f"voxpane — {status}" if ok else "voxpane — delivery failed",
        _preview(transcript),
        replace_id=notify.RECORDING_ID,
        expire_ms=6000,
        urgency="normal" if ok else "critical",
    )
    print(transcript)
    print(f"\n[{status}, {elapsed:.2f}s]", file=sys.stderr)
    return 0


def _cmd_start() -> int:
    from . import config

    return _start_recording(config.load())


def _cmd_stop() -> int:
    from . import config

    return _stop_and_deliver(config.load())


def _cmd_toggle() -> int:
    from . import config, recorder

    cfg = config.load()
    return _stop_and_deliver(cfg) if recorder.is_recording() else _start_recording(cfg)


def _cmd_install_bindings() -> int:
    from . import bindings

    try:
        result = bindings.install()
    except RuntimeError as exc:
        print(f"voxpane install-bindings: {exc}", file=sys.stderr)
        return 1

    if result.status == "already":
        print(f"✓ voxpane binding already present in {result.path}")
        return 0
    print(f"✓ bound {bindings.MODS} {bindings.KEY} → {bindings.CMD}")
    print(f"  in {result.path} ({result.kind})")
    if result.backup:
        print(f"  backed up to {result.backup}")
    if result.status == "created" and not result.sourced:
        print(f"  ! {result.path.name} is new — add to hyprland.conf: source = {result.path}")
    print("  reload Hyprland: hyprctl reload")
    return 0


_HANDLERS = {
    "doctor": lambda: doctor.main(),
    "start": _cmd_start,
    "stop": _cmd_stop,
    "toggle": _cmd_toggle,
    "install-bindings": _cmd_install_bindings,
}


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
