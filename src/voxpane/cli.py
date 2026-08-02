"""voxpane command-line interface.

``doctor`` is fully implemented (milestone M0). The remaining subcommands are
declared here so the CLI is self-documenting, and each is wired to its module as
its milestone lands. Until then they print which milestone owns them and exit
non-zero — see ``docs/plans/voxpane-plan.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__, doctor, paths

# subcommand -> (milestone, what it will do). Keeps the "not yet built" surface
# honest and points contributors at the right part of the plan.
_PENDING: dict[str, tuple[str, str]] = {
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
    sub.add_parser("daemon", help="run the resident STT daemon (voxpaned)")

    speak = sub.add_parser("speak", help="speak/notify a turn summary")
    speak.add_argument("text", nargs="?", help="text to speak")
    speak.add_argument("--from-hook", action="store_true", help="read Stop payload from stdin")

    ledger = sub.add_parser("ledger", help="append/show/prune the activity ledger")
    ledger.add_argument("action", nargs="?", choices=["append", "show", "prune"], default="show")
    ledger.add_argument(
        "--from-hook", action="store_true", help="read PostToolUse payload from stdin"
    )

    sub.add_parser("install-hooks", help="install Claude Code hooks (ledger + speak)")
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

    from . import config, deliver, notify, postprocess, recorder, transcriber

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
        transcript = transcriber.transcribe(wav, cfg)
    except RuntimeError as exc:
        return fail(str(exc), critical=True)
    if not transcript:
        return fail("empty transcript")

    rewritten = postprocess.apply(transcript, config.load_commands(), cfg)
    text = rewritten.text
    submit = rewritten.submit or cfg["delivery"]["auto_submit"]

    ok = True
    try:
        status = deliver.deliver(text, cfg, submit=submit)
    except (RuntimeError, OSError) as exc:
        ok = False
        status = f"delivery failed: {exc}"
        print(f"voxpane: {status}", file=sys.stderr)

    elapsed = time.monotonic() - t0
    _log(f"stop->deliver {elapsed:.2f}s {len(text)}chars submit={submit} {status}")
    notify.notify(
        f"voxpane — {status}" if ok else "voxpane — delivery failed",
        _preview(text),
        replace_id=notify.RECORDING_ID,
        expire_ms=6000,
        urgency="normal" if ok else "critical",
    )
    print(text)
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


def _cmd_daemon() -> int:
    from . import daemon

    return daemon.serve()


def _project_name(payload: dict, cfg: dict) -> str | None:
    from . import ledger

    mode = cfg["speak"].get("prefix_project", "auto")
    if mode == "never":
        return None
    cwd = payload.get("cwd") or ""
    name = (Path(cwd).name or None) if cwd else None
    if mode == "always":
        return name
    return name if ledger.active_sessions() > 1 else None  # auto: only when concurrent


def _last_message(payload: dict) -> str:
    message = payload.get("last_assistant_message")
    if message:
        return message
    transcript = payload.get("transcript_path")
    if not transcript or not Path(transcript).is_file():
        return ""
    last = ""
    try:
        for line in Path(transcript).read_text().splitlines():
            obj = json.loads(line)
            if obj.get("type") != "assistant" and obj.get("role") != "assistant":
                continue
            content = obj.get("message", {}).get("content", obj.get("content"))
            if isinstance(content, str):
                last = content
            elif isinstance(content, list):
                texts = [c.get("text", "") for c in content if isinstance(c, dict)]
                last = " ".join(t for t in texts if t) or last
    except (OSError, json.JSONDecodeError):
        return last
    return last


def _speak_from_hook(payload: dict, cfg: dict) -> int:
    import time
    from datetime import datetime

    from . import gate, ledger, notify, summarize

    session = payload.get("session_id", "default")
    turn_facts = ledger.facts(ledger.read(session))
    turn_seconds = (time.time() - turn_facts["first_ts"]) if turn_facts.get("first_ts") else 0.0
    last_message = _last_message(payload)

    speak, reason = gate.should_speak(
        turn_seconds=turn_seconds,
        has_tool_use=turn_facts["n_tools"] > 0,
        last_message=last_message,
        now=datetime.now().time(),
        gate_cfg=cfg["speak"]["gate"],
    )
    _log(f"speak gate {'PASS' if speak else 'skip'}: {reason} (turn {turn_seconds:.0f}s)")
    if not speak:
        ledger.truncate(session)
        return 0

    sentence = summarize.summarize(
        turn_facts, last_message, cfg, project=_project_name(payload, cfg)
    )
    notify.notify("voxpane", sentence, icon="audio-speakers")  # M6: notify only (M8 adds Echo)
    ledger.truncate(session)
    print(sentence)
    return 0


def _read_stdin_json() -> dict:
    try:
        raw = sys.stdin.read()
    except OSError:
        return {}
    try:
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}


def _cmd_speak(args) -> int:
    from . import config, notify

    cfg = config.load()
    if not cfg["speak"]["enabled"]:
        return 0
    if args.from_hook:
        return _speak_from_hook(_read_stdin_json(), cfg)
    if not args.text:
        print("voxpane speak: provide text, or --from-hook", file=sys.stderr)
        return 2
    notify.notify("voxpane", args.text[: cfg["speak"]["max_chars"]], icon="audio-speakers")
    print(args.text)
    return 0


def _cmd_install_hooks(args) -> int:
    from . import hooks

    try:
        result = hooks.install_hooks()
    except (RuntimeError, OSError) as exc:
        print(f"voxpane install-hooks: {exc}", file=sys.stderr)
        return 1
    if not result["added"]:
        print(f"✓ voxpane hooks already present in {result['settings']}")
    else:
        print(f"✓ installed hooks ({', '.join(result['added'])}) in {result['settings']}")
        print(f"  scripts: {result['hooks_dir']}")
        if result["backup"]:
            print(f"  backed up to {result['backup']}")
    print("  start a new Claude Code session to pick them up")
    return 0


def _all_sessions() -> list[str]:
    rt = paths.runtime_dir()
    if not rt.is_dir():
        return []
    return [p.stem.removeprefix("ledger-") for p in rt.glob("ledger-*.jsonl")]


def _cmd_ledger(args) -> int:
    from . import ledger

    if args.from_hook or args.action == "append":
        ledger.append_from_payload(_read_stdin_json())
        return 0
    if args.action == "prune":
        for session in _all_sessions():
            ledger.truncate(session)
        print("pruned all session ledgers")
        return 0
    sessions = _all_sessions()
    if not sessions:
        print("no active ledgers")
        return 0
    for session in sessions:
        f = ledger.facts(ledger.read(session))
        print(f"{session}: {f['n_tools']} tools, {f['n_files']} files, {f['tests_ran']} tests")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    cmd = args.command
    if cmd is None:
        parser.print_help()
        return 0
    simple = {
        "doctor": lambda: doctor.main(),
        "start": _cmd_start,
        "stop": _cmd_stop,
        "toggle": _cmd_toggle,
        "daemon": _cmd_daemon,
        "install-bindings": _cmd_install_bindings,
    }
    if cmd in simple:
        return simple[cmd]()
    if cmd == "speak":
        return _cmd_speak(args)
    if cmd == "install-hooks":
        return _cmd_install_hooks(args)
    if cmd == "ledger":
        return _cmd_ledger(args)
    return _pending(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
