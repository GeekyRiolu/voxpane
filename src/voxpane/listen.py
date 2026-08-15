"""Hands-free listen mode — a continuous VAD loop.

Auto-started per Claude session (SessionStart/End hooks). Captures the mic
continuously, detects speech with webrtcvad, and when you stop talking for
``endpoint_silence_ms`` it transcribes the utterance (via the daemon),
post-processes it, delivers it to the focused window, and auto-submits — no
push-to-talk.

Anti-feedback: the loop ignores the mic while the Dot is speaking (the speaking
marker) plus a short guard, so it never transcribes its own voice. Say one of the
``stop_words`` and it hushes the Dot instead of sending text.

The endpointing state machine (:class:`Endpointer`) is pure and unit-tested; the
live capture/transcribe glue needs a real mic to validate.
"""

from __future__ import annotations

import array
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from . import desktop, osutil, paths

FRAME_MS = 20
RATE = 16000
_BYTES_PER_FRAME = int(RATE * FRAME_MS / 1000) * 2  # 640: s16 mono, 20 ms


class Endpointer:
    """Turn a stream of (frame, is_speech) into complete utterances.

    Emits the buffered PCM once the speaker has been silent for ``silence_ms``
    (or the utterance hits ``max_ms``); drops anything shorter than
    ``min_speech_ms`` (coughs, clicks).
    """

    def __init__(self, frame_ms: int, silence_ms: int, min_speech_ms: int, max_ms: int):
        self.silence_frames = max(1, silence_ms // frame_ms)
        self.min_speech_frames = max(1, min_speech_ms // frame_ms)
        self.max_frames = max(1, max_ms // frame_ms)
        self.reset()

    def reset(self) -> None:
        self._buf: list[bytes] = []
        self._voiced = 0
        self._trailing_silence = 0
        self.active = False

    def process(self, frame: bytes, is_speech: bool) -> bytes | None:
        if not self.active:
            if is_speech:
                self.active = True
                self._buf = [frame]
                self._voiced = 1
                self._trailing_silence = 0
            return None

        self._buf.append(frame)
        if is_speech:
            self._voiced += 1
            self._trailing_silence = 0
        else:
            self._trailing_silence += 1

        if self._trailing_silence >= self.silence_frames or len(self._buf) >= self.max_frames:
            audio = b"".join(self._buf)
            enough = self._voiced >= self.min_speech_frames
            self.reset()
            return audio if enough else None
        return None


# --------------------------------------------------- listener process & ref-count

def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _alive(pid: int) -> bool:
    return osutil.pid_alive(pid)


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def is_listening() -> bool:
    pid = _read_pid(paths.listener_pid_file())
    return pid is not None and _alive(pid)


def toggle_running() -> bool:
    """Start the listener, or fully stop it. Returns True if it's now RUNNING.

    A real start/stop (not a pause) bound to a key: while off, no process runs and
    nothing is transcribed, so it costs zero CPU. Turning it on captures the
    terminal it was toggled from (if any) so dictation targets it precisely.
    """
    if is_listening() or _all_listener_pids():  # running (tracked) or an orphan alive
        stop()
        return False
    window = _active_window()
    if window and window.get("id") and _is_terminal_window(window):
        _save_windows({"toggle": window})
    _spawn_listener()
    return True


def _sessions() -> set[str]:
    try:
        return {s for s in paths.listen_sessions_file().read_text().split() if s}
    except OSError:
        return set()


def _write_sessions(sessions: set[str]) -> None:
    paths.ensure(paths.runtime_dir())
    paths.listen_sessions_file().write_text(" ".join(sorted(sessions)))


# --------------------------------------------------- focus gate (desktop-agnostic)

def _active_window(cfg: dict[str, Any] | None = None) -> dict[str, str] | None:
    """The focused window as ``{class, title, id}`` via the detected desktop backend
    (Hyprland/Sway/X11; None on GNOME/KDE-Wayland). Thin wrapper so callers — and
    tests — have one seam to mock."""
    return desktop.active_window(cfg)


def _load_windows() -> dict[str, dict[str, str]]:
    try:
        return json.loads(paths.listen_windows_file().read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_windows(windows: dict[str, dict[str, str]]) -> None:
    paths.ensure(paths.runtime_dir())
    paths.listen_windows_file().write_text(json.dumps(windows))


# Window classes that host a Claude Code session (it always runs in a terminal).
# Used to gate window capture + wake delivery so a browser/other app is never
# treated as "the Claude window" and a request is never misrouted into it.
_TERMINAL_CLASSES = (
    "alacritty", "kitty", "foot", "ghostty", "wezterm", "xterm",
    "konsole", "terminal", "termite", "urxvt", "rxvt", "tilix",
    "org.wezfurlong", "com.mitchellh.ghostty", "kgx",
    "iterm",  # macOS: active_window reports the app name (Terminal / iTerm2 / …)
)


def _is_terminal_window(window: dict[str, str] | None) -> bool:
    """True if ``window`` looks like a terminal (or a Claude session by title)."""
    if not window:
        return False
    cls = (window.get("class") or "").lower()
    title = (window.get("title") or "").lower()
    return "claude" in title or any(t in cls for t in _TERMINAL_CLASSES)


def _capture_window(session_id: str) -> None:
    window = _active_window()
    # Only remember terminal windows: Claude Code runs in a terminal, so a browser
    # focused when the session registers must not become "the Claude window" (it
    # would gate the mic to that app and misroute wake requests into it).
    if window and window.get("id") and _is_terminal_window(window):
        windows = _load_windows()
        windows[session_id] = window
        _save_windows(windows)


def _release_window(session_id: str) -> None:
    windows = _load_windows()
    if windows.pop(session_id, None) is not None:
        _save_windows(windows)


def focus_ok(cfg: dict[str, Any]) -> bool:
    """True if the listener should be active given the currently-focused window."""
    listen_cfg = cfg["listen"]
    if not listen_cfg.get("focus_only", True):
        return True
    active = _active_window(cfg)
    if active is None:  # can't detect focus (no backend CLI) — don't block
        return True
    match = (listen_cfg.get("focus_match") or "").strip()
    if match:
        pattern = re.compile(match, re.IGNORECASE)
        return bool(pattern.search(active["class"]) or pattern.search(active["title"]))
    ids = {w.get("id") for w in _load_windows().values() if w.get("id")}
    if not ids:  # nothing captured to gate against — don't block
        return True
    return active["id"] in ids


def _dictation_target_focused(cfg: dict[str, Any]) -> bool:
    """True if free dictation should go to the focused window: any terminal (Claude
    Code runs in one), or a ``focus_match`` class/title regex if configured.

    Kept simple on purpose — matching against a *captured* window address was fragile
    (a stale capture silently swallowed your words). This splits free dictation
    (focused on a terminal) from wake-word delivery (focused on a browser / nothing).
    """
    active = _active_window(cfg)
    if active is None:
        return False
    match = (cfg["listen"].get("focus_match") or "").strip()
    if match:
        pattern = re.compile(match, re.IGNORECASE)
        cls, title = active.get("class", ""), active.get("title", "")
        return bool(pattern.search(cls) or pattern.search(title))
    return _is_terminal_window(active)


def ensure(session_id: str, cfg: dict[str, Any]) -> None:
    """A Claude session started: register it and start the listener if needed."""
    if not cfg.get("listen", {}).get("enabled", False):
        return
    sessions = _sessions()
    sessions.add(session_id)
    _write_sessions(sessions)
    _capture_window(session_id)  # remember the Claude terminal to gate on focus
    if not is_listening():
        _spawn_listener()


def release(session_id: str) -> None:
    """A Claude session ended: unregister it and stop the listener if it was last.

    With ``[listen] always_on`` the listener is a standalone service that outlives
    every session, so a session ending must not stop it.
    """
    from . import config as config_mod

    sessions = _sessions()
    sessions.discard(session_id)
    _write_sessions(sessions)
    _release_window(session_id)
    always_on = config_mod.load()["listen"].get("always_on", False)
    if not sessions and not always_on:
        stop()


def _all_listener_pids() -> list[int]:
    """Pids of every live `voxpane listen --run` process — catches orphans the pid
    file has lost track of (after a crash/race), so a stray listener can't survive a
    stop or make the toggle misfire."""
    if not shutil.which("pgrep"):
        pid = _read_pid(paths.listener_pid_file())
        return [pid] if pid and _alive(pid) else []
    out = subprocess.run(
        ["pgrep", "-f", "voxpane listen --run"], capture_output=True, text=True
    )
    return [int(p) for p in out.stdout.split() if p.isdigit() and int(p) != os.getpid()]


def stop() -> None:
    pid = _read_pid(paths.listener_pid_file())
    targets = set(_all_listener_pids())  # the tracked listener PLUS any orphans
    if pid:
        targets.add(pid)
    for target in targets:
        if _alive(target):
            osutil.terminate(target)
    # Only remove the pid file if it still names the listener we signalled — a
    # freshly-spawned listener may have already claimed it (rapid restart), and
    # clobbering its pid file would make it invisible to is_listening().
    if _read_pid(paths.listener_pid_file()) == pid:
        _unlink(paths.listener_pid_file())


def _spawn_listener() -> None:
    # Spawn with the ENV's python (sys.prefix/bin/python), not sys.executable: uv
    # venvs symlink the interpreter to the base python, so sys.executable can point
    # outside the venv (no voxpane/webrtcvad). sys.prefix keeps the venv packages.
    # Capture the child's stderr to a log so a silent early exit is diagnosable.
    if osutil.IS_WINDOWS:
        env_python = os.path.join(sys.prefix, "Scripts", "python.exe")
    else:
        env_python = os.path.join(sys.prefix, "bin", "python")
    python = env_python if os.path.exists(env_python) else sys.executable
    try:
        paths.ensure(paths.state_dir())
        err = open(paths.state_dir() / "listen.log", "ab")  # noqa: SIM115
    except OSError:
        err = subprocess.DEVNULL
    subprocess.Popen(
        [python, "-m", "voxpane", "listen", "--run"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=err,
        **osutil.detached_kwargs(),  # outlive the hook process
    )


# ---------------------------------------------------------------- the live loop

def _audio_command(cfg: dict[str, Any]) -> list[str]:
    # Capture from audio.source; point it at a PipeWire echo-cancel source to strip
    # speaker output (YouTube, the Dot) from the mic entirely.
    source = str(cfg.get("audio", {}).get("source", "default"))
    if shutil.which("pw-cat"):
        cmd = ["pw-cat", "--record", "--rate", str(RATE), "--channels", "1",
               "--format", "s16", "--raw", "-"]
        if source and source != "default":
            cmd += ["--target", source]
        return cmd
    cmd = ["parec", f"--rate={RATE}", "--channels=1", "--format=s16le"]
    if source and source != "default":
        cmd += [f"--device={source}"]
    return cmd


def _media_playing() -> bool:
    """True if audio is actively playing — a RUNNING sink or an uncorked
    sink-input (e.g. a YouTube video). Lets the listener ignore the mic then."""
    if not shutil.which("pactl"):
        return False
    try:
        sinks = subprocess.run(
            ["pactl", "list", "sinks"], capture_output=True, text=True, timeout=2
        )
        inputs = subprocess.run(
            ["pactl", "list", "sink-inputs"], capture_output=True, text=True, timeout=2
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "State: RUNNING" in sinks.stdout or "Corked: no" in inputs.stdout


class _MicSource:
    """A stream of fixed-size (``_BYTES_PER_FRAME``) s16-mono frames from the mic,
    with a clean ``close()``. POSIX pipes ``pw-cat``/``parec``; Windows reads a
    ``sounddevice`` RawInputStream (there is no such capture subprocess there)."""

    def frames(self) -> Iterator[bytes]:  # pragma: no cover - overridden
        raise NotImplementedError

    def close(self) -> None:
        pass


class _SubprocessMic(_MicSource):
    def __init__(self, cfg: dict[str, Any]) -> None:
        self._proc = subprocess.Popen(
            _audio_command(cfg), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )

    def frames(self) -> Iterator[bytes]:
        assert self._proc.stdout is not None
        while True:
            frame = self._proc.stdout.read(_BYTES_PER_FRAME)
            if not frame or len(frame) < _BYTES_PER_FRAME:
                break
            yield frame

    def close(self) -> None:
        self._proc.terminate()


class _SoundDeviceMic(_MicSource):
    def __init__(self, cfg: dict[str, Any]) -> None:
        import sounddevice as sd

        source = str(cfg.get("audio", {}).get("source", "default"))
        device = source if source and source != "default" else None
        self._n = _BYTES_PER_FRAME // 2  # samples per frame (s16 = 2 bytes)
        self._stream = sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16",
                                         device=device)
        self._stream.start()

    def frames(self) -> Iterator[bytes]:
        while True:
            data, _overflowed = self._stream.read(self._n)
            frame = bytes(data)
            if len(frame) < _BYTES_PER_FRAME:
                break
            yield frame

    def close(self) -> None:
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass


def _open_mic(cfg: dict[str, Any]) -> _MicSource:
    # sounddevice on macOS/Windows (no pw-cat/parec); the subprocess pipe on Linux.
    if osutil.IS_WINDOWS or osutil.IS_MACOS:
        return _SoundDeviceMic(cfg)
    return _SubprocessMic(cfg)


def _utterance_rms(pcm: bytes) -> float:
    """Root-mean-square amplitude of s16 mono PCM (0..~32768).

    Near-silence sits well under ~150; speech is several hundred+. Whisper
    hallucinates ("Thank you for watching") on quiet/near-silent audio, so we use
    this to skip transcription entirely below ``min_rms``.
    """
    usable = len(pcm) - (len(pcm) % 2)
    if usable <= 0:
        return 0.0
    samples = array.array("h")
    samples.frombytes(pcm[:usable])
    if not samples:
        return 0.0
    return (sum(s * s for s in samples) / len(samples)) ** 0.5


def _pcm_to_wav(pcm: bytes, path: Path) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(pcm)


def is_stop_word(text: str, cfg: dict[str, Any]) -> bool:
    cleaned = text.strip().lower().strip(".!?,")
    return cleaned in {w.lower() for w in cfg["listen"].get("stop_words", [])}


# ---------------------------------------------------- wake word (Alexa-style)

_TERMINAL_EXEC = {
    "ghostty": ["ghostty", "-e"],
    "kitty": ["kitty"],  # runs `kitty <cmd>` directly (no -e)
    "alacritty": ["alacritty", "-e"],
    "foot": ["foot", "-e"],
    "wezterm": ["wezterm", "start", "--"],
    "xterm": ["xterm", "-e"],
}

# Windows terminals to try, best first: Windows Terminal, then PowerShell, then cmd.
_WINDOWS_TERMINALS = ("wt", "pwsh", "powershell", "cmd")


def _normalize(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace — for phrase matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.lower())).strip()


# Whisper hallucinates these on silence / music / a video's outro — it emits
# "Thanks for watching, I'll see you in the next video!" from near-silent frames.
# Dictation auto-submits, so without this an idle mic quietly types junk into
# Claude. These are FRAGMENTS: an utterance is dropped only if it tiles ENTIRELY
# into them (see _is_ignorable), so a real request with a content word survives.
_HALLUCINATION_FRAGMENTS = [
    "thank you for watching", "thanks for watching everyone", "thanks for watching",
    "thank you very much", "thank you so much", "thanks so much",
    "i ll see you in the next video", "i ll see you next time", "i ll see you",
    "see you in the next video", "see you in the next one", "see you next time",
    "see you next video", "in the next video", "in the next one",
    "don t forget to subscribe", "subscribe to my channel", "like and subscribe",
    "please subscribe", "for watching", "this video", "my channel", "this channel",
    "thank you", "see you", "subscribe", "everyone", "so much", "thanks",
    "watching", "video", "channel", "today", "this", "bye bye", "please",
    "guys", "okay", "bye", "you", "and", "so", "the",
]

# Precomputed word-lists, longest first (greedy tiling matches the longest run).
_FRAG_WORDS = sorted(
    (_normalize(f).split() for f in _HALLUCINATION_FRAGMENTS), key=len, reverse=True
)


def _is_ignorable(text: str, cfg: dict[str, Any]) -> bool:
    """True if the whole utterance is a Whisper hallucination (stock outro junk).

    Empty transcript, an exact user-listed ``ignore_phrases`` entry, or a string
    that tiles entirely into ``_HALLUCINATION_FRAGMENTS`` (so compound outros like
    "thanks for watching, I'll see you in the next video" are caught, but any
    utterance with a real content word is kept).
    """
    norm = _normalize(text)
    if not norm:
        return True
    if norm in {_normalize(p) for p in cfg["listen"].get("ignore_phrases", [])}:
        return True
    words = norm.split()
    i = 0
    while i < len(words):
        for frag in _FRAG_WORDS:
            if words[i:i + len(frag)] == frag:
                i += len(frag)
                break
        else:
            return False  # a word that isn't outro junk -> real speech, keep it
    return True


def _wake_variants(wake_word: str, aliases: list[str]) -> list[str]:
    variants = {wake_word.lower().strip(), *(a.lower().strip() for a in aliases if a.strip())}
    return sorted((v for v in variants if v), key=len, reverse=True)


def strip_wake_word(text: str, wake_word: str, aliases: list[str] | None = None) -> str | None:
    """If ``text`` starts with the wake word (or an alias), return the request that
    follows (possibly ""); else None. No wake word configured -> passthrough."""
    if not wake_word:
        return text
    original = text.strip()
    normalized = _normalize(original)
    for variant in _wake_variants(wake_word, aliases or []):
        if normalized == variant:
            return ""
        if normalized.startswith(variant + " "):
            request = " ".join(original.split()[len(variant.split()):])
            return request.lstrip(" ,.:—-").strip()
    return None


def _pause_media() -> None:
    if shutil.which("playerctl"):
        subprocess.run(["playerctl", "--all-players", "pause"], capture_output=True)


def _detect_terminal(cfg: dict[str, Any]) -> list[str] | None:
    configured = (cfg["listen"].get("terminal") or "").strip()
    if configured:
        return shlex.split(configured)  # full prefix, incl. any exec flag
    if osutil.IS_WINDOWS:
        return next(([t] for t in _WINDOWS_TERMINALS if shutil.which(t)), None)
    for term, prefix in _TERMINAL_EXEC.items():
        if shutil.which(term):
            return prefix
    return None


def _wake_argv(terminal: list[str], folder: str, command: str) -> list[str]:
    """Build the terminal launch argv: ``cd <folder> && <command>`` in a fresh window,
    per-terminal. POSIX runs it under ``sh -lc``; Windows uses wt/pwsh/cmd syntax."""
    if not osutil.IS_WINDOWS:
        return [*terminal, "sh", "-lc", f"cd {shlex.quote(folder)} && {command}"]
    head = os.path.basename(terminal[0]).lower()
    if head.startswith("wt"):  # Windows Terminal: -d sets the working directory
        return [*terminal, "-d", folder, *shlex.split(command)]
    if head.startswith("cmd"):
        return [*terminal, "/c", f'cd /d "{folder}" && {command}']
    safe = folder.replace("'", "''")  # pwsh / powershell
    return [*terminal, "-NoProfile", "-Command", f"Set-Location -LiteralPath '{safe}'; {command}"]


def _resolve_folder(request: str, base: str) -> str:
    """Resolve a spoken folder name to an absolute path under ``base`` (default
    ~/Work). Empty request or no match -> ``base`` itself; matching is fuzzy so
    imperfect transcription still lands on the right repo."""
    import difflib

    base = os.path.expanduser(base or "~")
    if not os.path.isdir(base):
        base = os.path.expanduser("~")
    req = _normalize(request)
    try:
        subdirs = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))]
    except OSError:
        return base
    if not req or not subdirs:
        return base
    norm = {_normalize(d): d for d in subdirs}
    if req in norm:                                    # exact (normalized) match
        return os.path.join(base, norm[req])
    for nd, d in norm.items():                         # substring either way
        if req in nd or nd in req:
            return os.path.join(base, d)
    last = req.split()[-1]                             # last spoken word ~ repo name
    for nd, d in norm.items():
        if last and (last in nd.split() or last in nd):
            return os.path.join(base, d)
    match = difflib.get_close_matches(req, list(norm), n=1, cutoff=0.6)
    return os.path.join(base, norm[match[0]]) if match else base


def _wake_open_session(request: str, cfg: dict[str, Any]) -> None:
    """Open a NEW terminal running Claude, cd'd into the folder named in ``request``
    (resolved under ``wake_base_dir``). Always a fresh session, per request."""
    terminal = _detect_terminal(cfg)
    if terminal is None:
        return
    lc = cfg["listen"]
    command = lc.get("wake_open_command", "claude --dangerously-skip-permissions --model opus")
    folder = _resolve_folder(request, lc.get("wake_base_dir", "~/Work"))
    subprocess.Popen(
        _wake_argv(terminal, folder, command),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **osutil.detached_kwargs(),
    )


def handle_utterance(pcm: bytes, cfg: dict[str, Any]) -> str | None:
    """Transcribe and act on one utterance. Returns the delivered text, or None."""
    from . import config as config_mod
    from . import deliver, hush, overlay, postprocess, transcriber

    # Source-side anti-hallucination: don't even ask Whisper about near-silent
    # audio (a VAD misfire on room noise) — it invents "Thank you for watching".
    if _utterance_rms(pcm) < cfg["listen"].get("min_rms", 150):
        return None

    wav = paths.runtime_dir() / "listen-utt.wav"
    _pcm_to_wav(pcm, wav)
    try:
        text = transcriber.transcribe(wav, cfg)
    except RuntimeError:
        return None
    finally:
        _unlink(wav)
    if not text:
        return None
    if _is_ignorable(text, cfg):
        return None  # Whisper hallucination on silence/music — never deliver it

    lc = cfg["listen"]
    wake = lc.get("wake_word", "").strip()

    # The wake word is an explicit command that ALWAYS opens a fresh Claude session,
    # regardless of what's focused: say "voxpane <folder>" and we open a new terminal
    # + Claude in that repo under wake_base_dir (~/Work). Checked before dictation so
    # it works even while you're focused on an existing Claude terminal.
    if wake:
        request = strip_wake_word(text, wake, lc.get("wake_aliases", []))
        if request is not None:  # addressed to voxpane
            if lc.get("pause_media_on_wake", True):
                _pause_media()
            overlay.set_state("thinking", request or "new session")
            _wake_open_session(request, cfg)
            return request or "(opened Claude session)"

    # No wake word: free dictation, but only into a focused Claude terminal.
    if _dictation_target_focused(cfg):
        if lc.get("pause_on_playback", True) and _media_playing():
            return None  # don't dictate over a video
        if is_stop_word(text, cfg):
            hush.hush()
            return None
        overlay.set_state("thinking", text)
        rewritten = postprocess.apply(text, config_mod.load_commands(), cfg)
        submit = lc.get("auto_submit", True) or rewritten.submit
        deliver.deliver(rewritten.text, cfg, submit=submit)
        return rewritten.text

    return None  # not addressed to voxpane and not focused on a Claude terminal


def run(cfg: dict[str, Any] | None = None) -> int:
    from . import config as config_mod
    from . import overlay

    try:
        import webrtcvad
    except ImportError:
        print(
            "voxpane listen: webrtcvad not installed — "
            "uv tool install --force 'voxpane[daemon,listen]'",
            file=sys.stderr,
        )
        return 1

    cfg = cfg or config_mod.load()

    # Single instance: the always-on service and a session hook can both try to
    # start a listener. If one already owns the pid file, defer to it.
    existing = _read_pid(paths.listener_pid_file())
    if existing and existing != os.getpid() and _alive(existing):
        print(f"voxpane listen: already running (pid {existing})", file=sys.stderr)
        return 0

    lc = cfg["listen"]
    vad = webrtcvad.Vad(int(lc.get("vad_aggressiveness", 2)))
    endpointer = Endpointer(
        FRAME_MS,
        int(lc["endpoint_silence_ms"]),
        int(lc["min_speech_ms"]),
        int(lc["max_utterance_seconds"]) * 1000,
    )
    guard = lc.get("post_speak_guard_ms", 700) / 1000
    poll = lc.get("focus_poll_ms", 250) / 1000
    wake = lc.get("wake_word", "").strip()

    paths.ensure(paths.runtime_dir())
    paths.listener_pid_file().write_text(str(os.getpid()))
    stop_requested = {"v": False}
    if not osutil.IS_WINDOWS:  # Windows can't usefully catch SIGTERM (taskkill is hard)
        signal.signal(signal.SIGTERM, lambda *_: stop_requested.__setitem__("v", True))
    last_speak = 0.0
    last_check = 0.0
    active = True
    shown = ""
    mic: _MicSource | None = None

    def _overlay(state: str) -> None:
        nonlocal shown
        if state != shown:
            overlay.set_state(state)
            shown = state

    try:
        # Reconnect loop: if the mic stream ends (the device drops on suspend/
        # resume), reopen it rather than exiting — the listener survives sleep.
        while not stop_requested["v"]:
            mic = _open_mic(cfg)
            for frame in mic.frames():
                if stop_requested["v"]:
                    break
                now = time.monotonic()
                if now - last_check >= poll:
                    # Capture whenever the wake word is armed (heard everywhere) or a
                    # dictation target is focused; handle_utterance decides per
                    # utterance whether to open a session, dictate, or ignore.
                    active = wake != "" or focus_ok(cfg)
                    last_check = now
                if not active:
                    _overlay("idle")
                    endpointer.reset()
                    continue
                # Anti-feedback: don't listen to the Dot, or its echo tail.
                if paths.speaking_marker().exists():
                    last_speak = now
                    endpointer.reset()
                    continue
                if now - last_speak < guard:
                    endpointer.reset()
                    continue
                is_speech = vad.is_speech(frame, RATE)
                utterance = endpointer.process(frame, is_speech)
                if utterance is not None:
                    handle_utterance(utterance, cfg)  # sets "thinking" while it works
                    shown = "thinking"
                # Rest calmly as "idle" (the pet sleeps); perk to "listening" only
                # while actually capturing speech, so it isn't constantly twitching.
                _overlay("listening" if endpointer.active or is_speech else "idle")
            mic.close()
            mic = None
            if stop_requested["v"]:
                break
            _overlay("idle")
            endpointer.reset()
            time.sleep(1.0)  # mic stream ended (suspend?) — pause, then reopen it
    finally:
        if mic is not None:
            mic.close()
        # Don't clobber a newer listener's pid file on a rapid restart: only clear
        # the file if it still names us.
        if _read_pid(paths.listener_pid_file()) == os.getpid():
            _unlink(paths.listener_pid_file())
        overlay.clear()
    return 0
