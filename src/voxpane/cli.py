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

# subcommand -> (milestone, description) for any not-yet-built command. Empty now
# that M0–M9 are implemented; kept as a graceful fallback.
_PENDING: dict[str, tuple[str, str]] = {}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voxpane",
        description="Talk to Claude Code; have your Echo Dot say what it did.",
        epilog="Run 'voxpane doctor' first. Full spec: docs/plans/voxpane-plan.md",
    )
    parser.add_argument("--version", action="version", version=f"voxpane {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("doctor", help="check the environment is ready (start here)")

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
    sub.add_parser("install-bindings",
                   help="install the SUPER ALT V keybind (Hyprland/Sway; prints steps elsewhere)")
    sub.add_parser(
        "install-listener",
        help="enable the always-on listener service (wake word works with no session)",
    )

    vocab = sub.add_parser("vocab", help="build a repo vocabulary prompt for whisper")
    vocab.add_argument("--from-repo", action="store_true")

    status = sub.add_parser("status", help="print recording/speaking state as waybar JSON")
    status.add_argument(
        "--field", choices=["state", "detail", "class", "text", "sprite", "tooltip", "running"],
        help="print just one field as plain text (for the eww overlay)",
    )
    status.add_argument(
        "--watch", action="store_true",
        help="stream status JSON on every change (one process, for eww deflisten)",
    )
    ovl = sub.add_parser("overlay", help="show the Siri-style on-screen overlay (eww)")
    ovl.add_argument("action", nargs="?", choices=["start", "stop"], default="start")
    chime = sub.add_parser("chime", help="alert on the Dot (Notification hook)")
    chime.add_argument("text", nargs="?", default="Claude needs your input")

    sub.add_parser("hush", help="stop the Dot speaking (bind to SUPER ALT S)")
    lst = sub.add_parser("listen", help="hands-free VAD listen mode")
    grp = lst.add_mutually_exclusive_group()
    grp.add_argument("--run", action="store_true", help="run the listen loop (foreground)")
    grp.add_argument("--ensure", action="store_true", help="register a session; start if needed")
    grp.add_argument("--release", action="store_true", help="unregister a session; stop if last")
    grp.add_argument("--stop", action="store_true", help="stop the listener now")
    grp.add_argument("--toggle", action="store_true", help="pause/resume listening (bind to a key)")
    grp.add_argument("--status", action="store_true", help="print listening/idle")

    return parser


def _pending(command: str) -> int:
    milestone, description = _PENDING.get(command, ("?", "not implemented"))
    print(
        f"voxpane {command}: not built yet — {description} ({milestone}). "
        "See docs/plans/voxpane-plan.md.",
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

    if result.kind == "manual":
        print("voxpane: this desktop has no keybind API voxpane can write to.")
        print("Add these two shortcuts in your system keyboard settings:")
        for line in result.instructions:
            print(f"  • {line}")
        from . import osutil
        if osutil.IS_WINDOWS:
            print("  On Windows, AutoHotkey is the easiest route — e.g. in a .ahk script:")
            print("    #!v::Run, voxpane toggle    ; Win+Alt+V  -> voxpane listen --toggle")
            print("    #!s::Run, voxpane hush       ; Win+Alt+S")
        return 0

    if result.status == "already":
        print(f"✓ voxpane binds already present in {result.path}")
        return 0
    print(f"✓ installed binds ({', '.join(result.added)}) in {result.path} ({result.kind})")
    if result.backup:
        print(f"  backed up to {result.backup}")
    if result.status == "created" and not result.sourced:
        if result.kind == "sway":
            print(f"  ! {result.path.name} is new — make sure your sway config has: "
                  f"include {result.path.parent}/*")
        else:
            print(f"  ! {result.path.name} is new — add to hyprland.conf: source = {result.path}")
    print(f"  reload: {'swaymsg reload' if result.kind == 'sway' else 'hyprctl reload'}")
    return 0


def _ensure_always_on() -> tuple[Path, bool]:
    """Ensure ``[listen] always_on = true`` in the user config. Returns (path, changed)."""
    from . import config as config_mod

    path = paths.config_dir() / "config.toml"
    if config_mod.load()["listen"].get("always_on", False):
        return path, False
    paths.ensure(paths.config_dir())
    lines = path.read_text().splitlines() if path.is_file() else []
    out: list[str] = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and line.strip() == "[listen]":
            out.append("always_on = true")
            inserted = True
    if not inserted:
        if out and out[-1].strip():
            out.append("")
        out += ["[listen]", "always_on = true"]
    path.write_text("\n".join(out) + "\n")
    return path, True


def _install_listener_windows() -> int:
    import shutil
    import subprocess

    if not shutil.which("schtasks"):
        print("schtasks not found — cannot register the listener service", file=sys.stderr)
        return 1
    exe = shutil.which("voxpane") or "voxpane"
    task = "voxpane-listen"
    try:
        subprocess.run(
            ["schtasks", "/Create", "/TN", task, "/TR", f'"{exe}" listen --run',
             "/SC", "ONLOGON", "/RL", "LIMITED", "/F"],
            check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"  ! could not register the scheduled task: {exc}", file=sys.stderr)
        return 1
    print(f"✓ registered scheduled task '{task}' (runs `voxpane listen --run` at logon)")
    cfg_path, changed = _ensure_always_on()
    print(f"✓ set always_on = true in {cfg_path}" if changed
          else f"✓ always_on already enabled ({cfg_path})")
    subprocess.run(["schtasks", "/Run", "/TN", task], capture_output=True)
    print('  set wake_word in config.toml, then say "voxpane ..." from anywhere')
    print(f"  remove later with:  schtasks /Delete /TN {task} /F")
    return 0


def _cmd_install_listener() -> int:
    from . import osutil
    if osutil.IS_WINDOWS:
        return _install_listener_windows()

    import shutil
    import subprocess

    # Prefer the durable tool install over whatever's first on PATH (a repo/venv
    # shim would break the service if that checkout moved).
    home_bin = Path.home() / ".local" / "bin" / "voxpane"
    exe = str(home_bin) if home_bin.exists() else (shutil.which("voxpane") or str(home_bin))
    unit = (
        "[Unit]\n"
        "Description=voxpane hands-free listener (always-on wake word)\n"
        "Documentation=https://github.com/GeekyRiolu/voxpane\n"
        "After=voxpaned.service pipewire.service\n"
        "Wants=voxpaned.service\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={exe} listen --run\n"
        "Restart=on-failure\n"
        "RestartSec=2\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / "voxpane-listen.service"
    unit_path.write_text(unit)
    print(f"✓ wrote {unit_path}")

    cfg_path, changed = _ensure_always_on()
    print(f"✓ set always_on = true in {cfg_path}" if changed
          else f"✓ always_on already enabled ({cfg_path})")

    if not shutil.which("systemctl"):
        print("  systemctl not found — enable it once systemd is available:")
        print("    systemctl --user daemon-reload && systemctl --user enable --now voxpane-listen")
        return 0
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", "voxpane-listen.service"], check=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"  ! could not start the service automatically: {exc}", file=sys.stderr)
        print("    run: systemctl --user enable --now voxpane-listen")
        return 1
    print("✓ voxpane-listen.service enabled and started")
    print('  set wake_word in config.toml, then say "voxpane ..." from anywhere')
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

    from . import gate, ledger, listen, overlay, speakers, summarize

    session = payload.get("session_id", "default")
    turn_facts = ledger.facts(ledger.read(session))
    turn_seconds = (time.time() - turn_facts["first_ts"]) if turn_facts.get("first_ts") else 0.0
    last_message = _last_message(payload)

    # Conversational mode (hands-free listening active): speak the response itself,
    # a bare question from Claude is worth hearing, and replies can be quick — so
    # relax the gate. Otherwise use the strict coding-assistant gate.
    conversational = listen.is_listening() and cfg["listen"].get("conversational", True)
    if conversational:
        if not last_message.strip():
            ledger.truncate(session)
            return 0
        gate_cfg = {**cfg["speak"]["gate"], "require_tool_use": False,
                    "skip_if_question": False, "min_turn_seconds": 0}
        has_tool_use = True
        summary_cfg = {**cfg, "summary": {**cfg["summary"], "mode": "llm"}}
    else:
        gate_cfg = cfg["speak"]["gate"]
        has_tool_use = turn_facts["n_tools"] > 0
        summary_cfg = cfg

    speak, reason = gate.should_speak(
        turn_seconds=turn_seconds,
        has_tool_use=has_tool_use,
        last_message=last_message,
        now=datetime.now().time(),
        gate_cfg=gate_cfg,
    )
    _log(f"speak gate {'PASS' if speak else 'skip'}: {reason} (turn {turn_seconds:.0f}s)")
    if not speak:
        ledger.truncate(session)
        return 0

    sentence = summarize.summarize(
        turn_facts, last_message, summary_cfg, project=_project_name(payload, cfg)
    )
    overlay.set_state("speaking", sentence)
    backend = speakers.speak_with_fallback(sentence, cfg)
    overlay.set_state("idle")
    _log(f"spoke via {backend}: {sentence}")
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
    from . import config, speakers

    cfg = config.load()
    if not cfg["speak"]["enabled"]:
        return 0
    if args.from_hook:
        return _speak_from_hook(_read_stdin_json(), cfg)
    if not args.text:
        print("voxpane speak: provide text, or --from-hook", file=sys.stderr)
        return 2
    backend = speakers.speak_with_fallback(args.text[: cfg["speak"]["max_chars"]], cfg)
    print(f"[{backend}] {args.text}")
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


def _cmd_vocab(args) -> int:
    from . import vocab

    addendum = vocab.from_repo()
    if not addendum:
        print("voxpane vocab: no git-tracked files here", file=sys.stderr)
        return 1
    print("# Append to whisper.initial_prompt in ~/.config/voxpane/config.toml:")
    print(addendum)
    return 0


def _status_fields() -> dict[str, str]:
    from . import listen, overlay, recorder

    current = overlay.read_state()
    state, detail = current["state"], current["text"]
    if state == "idle":  # fall back to live signals if the overlay file is idle
        if recorder.is_recording():
            state = "recording"
        elif paths.speaking_marker().exists():
            state = "speaking"
    icon, label = overlay.STATES.get(state, ("", "idle"))
    return {
        "text": icon,
        "class": state,
        "state": state,
        "detail": detail,
        "sprite": overlay.sprite_path(state),
        "tooltip": f"voxpane: {label}" + (f" — {detail}" if detail else ""),
        # "1" while the hands-free listener is alive — the pet reveals/hides on it.
        "running": "1" if listen.is_listening() else "0",
    }


def _cmd_status(args) -> int:
    # --watch: ONE long-running process that streams the status JSON only when it
    # changes, for eww's `deflisten`. This replaces per-field polling, which spawned
    # Python ~14x/second (~85% of a CPU core) just to keep the pet updated.
    if getattr(args, "watch", False):
        import time

        last = None
        try:
            while True:
                line = json.dumps(_status_fields())
                if line != last:
                    print(line, flush=True)
                    last = line
                time.sleep(0.25)
        except (KeyboardInterrupt, BrokenPipeError):
            return 0
    fields = _status_fields()
    if getattr(args, "field", None):
        print(fields.get(args.field, ""))
    else:
        print(json.dumps(fields))
    return 0


def _eww_config_dir() -> Path | None:
    here = Path(__file__).resolve()
    for candidate in (here.parents[2] / "ui" / "eww", here.parent / "data" / "ui" / "eww"):
        if (candidate / "eww.yuck").is_file():
            return candidate
    return None


def _kill_stray_eww(config_dir: str) -> None:
    """SIGKILL any lingering eww daemon started with our config, so the pet is
    single-instance (eww daemons have been seen to stack across restarts)."""
    import os
    import signal
    import subprocess

    try:
        out = subprocess.run(["pgrep", "-af", "eww"], capture_output=True, text=True).stdout
    except OSError:
        return
    for line in out.splitlines():
        pid, _, cmd = line.partition(" ")
        if pid.isdigit() and config_dir in cmd:
            try:
                os.kill(int(pid), signal.SIGKILL)
            except (OSError, ValueError):
                pass


def _cmd_overlay(args) -> int:
    import shutil
    import subprocess

    if not shutil.which("eww"):
        print(
            "voxpane overlay: eww not found — install it (e.g. yay -S eww), or use "
            "the waybar module (waybar/voxpane.jsonc).",
            file=sys.stderr,
        )
        return 1
    config_dir = _eww_config_dir()
    if config_dir is None:
        print("voxpane overlay: bundled eww config not found", file=sys.stderr)
        return 1
    import time

    eww = ["eww", "--config", str(config_dir)]
    if args.action == "stop":
        subprocess.run([*eww, "close", "voxpane"], capture_output=True)
        subprocess.run([*eww, "kill"], capture_output=True)
        print("voxpane overlay: closed")
        return 0
    from . import config, desktop
    if not desktop.overlay_supported(config.load()):
        print(
            "voxpane overlay: the pixel pet needs a wlroots compositor (Hyprland or "
            "Sway) for its layer-shell window — your desktop can't show it. Everything "
            "else (voice, dictation, spoken summaries) works regardless.",
            file=sys.stderr,
        )
        return 1
    # Single instance: kill any pet already up (eww daemons can stack) before
    # starting a fresh one — so only ever one remains open.
    subprocess.run([*eww, "kill"], capture_output=True)
    _kill_stray_eww(str(config_dir))
    time.sleep(0.3)  # let the old socket release
    # `eww daemon` blocks in the foreground, so start it DETACHED, then open.
    subprocess.Popen(
        [*eww, "daemon"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(0.7)  # let the daemon bind its socket
    result = subprocess.run([*eww, "open", "voxpane"], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"voxpane overlay: eww failed: {result.stderr.strip()}", file=sys.stderr)
        return 1
    print("voxpane overlay: pet is out. Stop with: voxpane overlay stop")
    return 0


def _cmd_chime(args) -> int:
    from . import config, speakers

    cfg = config.load()
    if cfg["speak"]["enabled"]:
        speakers.speak_with_fallback(args.text, cfg)
    return 0


def _cmd_hush(args) -> int:
    from . import hush

    print("hushed" if hush.hush() else "nothing playing")
    return 0


def _notify(body: str) -> None:
    """Best-effort desktop toast, so a toggle keypress gives visible feedback."""
    import shutil
    import subprocess

    if shutil.which("notify-send"):
        subprocess.run(
            ["notify-send", "-t", "1500", "-a", "voxpane", "voxpane", body],
            capture_output=True,
        )


def _ensure_overlay_running() -> None:
    """Start the eww pet if it isn't up — so SUPER ALT V restores it after a
    suspend/resume (or any crash) that took the overlay down with it."""
    import shutil
    import subprocess

    from . import config, desktop
    if not desktop.overlay_supported(config.load()):
        return  # no wlroots layer-shell here — nothing to restore
    if not shutil.which("eww") or not shutil.which("pgrep"):
        return
    if subprocess.run(["pgrep", "-x", "eww"], capture_output=True).returncode == 0:
        return  # already running
    exe = shutil.which("voxpane") or str(Path.home() / ".local" / "bin" / "voxpane")
    subprocess.Popen(
        [exe, "overlay"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _cmd_listen(args) -> int:
    from . import config, listen

    cfg = config.load()
    if args.run:
        return listen.run(cfg)
    if args.stop:
        listen.stop()
        return 0
    if args.status:
        print("listening" if listen.is_listening() else "off")
        return 0
    if args.toggle:
        running = listen.toggle_running()
        if running:
            _ensure_overlay_running()  # restore the pet too (e.g. after suspend)
        _notify("Listening on" if running else "Listening off")
        print("listening" if running else "off")
        return 0
    session = _read_stdin_json().get("session_id", "default")
    if args.release:
        listen.release(session)
    else:  # --ensure (the default; from the SessionStart hook)
        listen.ensure(session, cfg)
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
        "install-listener": _cmd_install_listener,
    }
    argful = {
        "speak": _cmd_speak,
        "install-hooks": _cmd_install_hooks,
        "ledger": _cmd_ledger,
        "vocab": _cmd_vocab,
        "status": _cmd_status,
        "overlay": _cmd_overlay,
        "chime": _cmd_chime,
        "hush": _cmd_hush,
        "listen": _cmd_listen,
    }
    if cmd in simple:
        return simple[cmd]()
    if cmd in argful:
        return argful[cmd](args)
    return _pending(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
