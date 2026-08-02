# voxpane architecture

voxpane is two independent pipelines that share one CLI and one config file:

- **inbound** — get spoken words into the Claude Code pane, fast and accurately;
- **outbound** — tell you what Claude did, only when it's worth saying.

They never talk to each other directly. Their only shared state is on disk (the
config, and the runtime directory). This document explains each path, where
state lives, and *why* each awkward-looking constraint exists — most of them are
scar tissue from a specific failure.

---

## 1. Inbound: voice → tmux

```
[SUPER ALT V]
     │ toggle (Hyprland keybind → `voxpane toggle`)
     ▼
 state.json  ── flips recording on/off
     │
     ├─ on  → recorder.start():  pw-record → /tmp/vp-<ts>.wav   (+ "🎙 Recording…")
     │
     └─ off → recorder.stop():   SIGINT pw-record               (+ "⏳ Transcribing…")
                    │
                    ▼
              transcriber:  daemon socket ─┐ (fast path, model in RAM)
                            whisper-cli  ──┘ (fallback, always works)
                    │
                    ▼
              postprocess:  command dictionary, filler strip, submit phrase
                    │
                    ▼
                deliver:  tmux send-keys -l  |  focus paste  |  clipboard
                              (Enter only if this utterance opted in)
```

### Components

| Module | Job |
| --- | --- |
| `cli.py` | argument parsing and dispatch; thin. |
| `paths.py` | every filesystem location, XDG-correct. |
| `config.py` | load defaults, deep-merge the user's config on top. |
| `recorder.py` | drive `pw-record`; own the record PID. |
| `transcriber.py` | WAV → text, via the daemon or a `whisper-cli` subprocess. |
| `postprocess.py` | rewrite the raw transcript into agent-ready text (pure). |
| `deliver.py` | put text into the pane/window/clipboard. |
| `daemon.py` | `voxpaned`: hold the model in RAM behind a unix socket. |
| `notify.py` | the recording/transcribing/preview toasts. |

### Why it's shaped this way

- **Toggle, not hold.** A key-*hold* push-to-talk means owning the keyboard grab.
  A toggle is a stateless keybind that just runs `voxpane toggle`, which flips a
  flag in `state.json`. Simpler, and it survives the compositor.
- **Stop with SIGINT, never SIGKILL.** `pw-record` finalises the WAV header on
  SIGINT. SIGKILL leaves a headerless, unreadable file. This one bites everybody
  once.
- **`tmux send-keys` needs `-l`.** Without literal mode, words like `Enter` and
  `Space` in your dictation get interpreted as key *names*. `-l` sends the text
  as-is.
- **Never auto-submit by default.** A mis-transcription submitted is worse than a
  wasted keystroke. Text lands in the input buffer; you press Enter. The
  "send it" trailing phrase opts a single utterance into auto-submit — it never
  changes global state.
- **The daemon is an optimisation, not a dependency.** `voxpaned` keeps a
  `faster-whisper` model resident so per-utterance cost is transcription only
  (target: p50 < 1.2 s for a 10 s clip). If the socket is absent, the CLI falls
  back to spawning `whisper-cli`. The tool never hard-fails because the daemon
  is down.

---

## 2. Outbound: turn end → Echo Dot

```
Claude Code turn
     │
     ├─ PostToolUse ──▶ hooks/voxpane-post-tool.sh
     │                     └─ jq append → ledger-<session_id>.jsonl
     │                        {"ts", "tool", "path"|"cmd", "exit"}
     │
     └─ Stop ─────────▶ hooks/voxpane-stop.sh
                           ├─ stop_hook_active? → exit 0   (loop guard)
                           ├─ print {"async": true}        (don't block Claude)
                           └─ voxpane speak --from-hook  (detached)
                                   │
                                   ▼
                             gate  ── real work? long enough? not a question?
                                   │        not quiet hours?
                                   │ pass
                                   ▼
                            summarize  ── ledger facts (+ optional LLM clause)
                                   │        → speech-safe, capped at max_chars
                                   ▼
                            speakers.speak_with_fallback  (under a lock)
                                   alexa → bluetooth → notify
                                   ▼
                                Echo Dot
```

### Components

| Module | Job |
| --- | --- |
| `ledger.py` | append / read / reduce-to-facts / truncate the activity log. |
| `summarize.py` | facts (+ LLM) → one spoken sentence, speech-safe (pure). |
| `speakers/base.py` | the `Speaker` interface + `SpeakerError`. |
| `speakers/alexa.py` | Alexa's real voice over WiFi, via `alexa-cli`. |
| `speakers/bluetooth.py` | Piper TTS → padded → the Dot as an A2DP sink. |
| `speakers/notify.py` | the floor: a desktop notification that can't fail. |
| `hooks/*.sh` | the two Claude Code hooks (shell, so they start instantly). |

### Facts beat prose (the ledger)

`last_assistant_message` is markdown — code fences, bullet lists, file paths.
Read verbatim it becomes *"backtick backtick backtick python."* So the summary is
built from **facts**, not prose. Every `PostToolUse` hook appends one line:

```json
{"ts": 1754130000, "tool": "Edit",  "path": "src/voxpane/cli.py"}
{"ts": 1754130012, "tool": "Bash",  "cmd": "uv run pytest", "exit": 0}
{"ts": 1754130044, "tool": "Write", "path": "tests/test_postprocess.py"}
```

"Four files changed in voxpane, tests ran clean" is derived deterministically
from that. The LLM pass (in `hybrid` mode) only adds a short clause of *intent* on
top, bounded by a timeout and falling back to facts-only. The ledger is
truncated at Stop, after the summary is built.

### The gate is the whole game

The Stop hook fires on **every** turn end — including when Claude just asked you
a clarifying question. Speaking every time is unbearable within ten minutes. A
turn is spoken only if it:

- did real work (`require_tool_use` — the ledger is non-empty), and
- ran long enough (`min_turn_seconds`), and
- didn't end in a question to you (`skip_if_question`), and
- isn't inside `quiet_hours`.

The gate is pure and unit-tested. It is where the annoyance lives, so it is where
the tests concentrate.

### The fallback chain never raises

Backends are tried in `speak.backends` order:

1. **alexa** — Alexa's real voice over WiFi. Preferred, but the endpoint is
   unofficial and *will* fail eventually (auth, network). Failure → next.
2. **bluetooth** — local Piper TTS to the Dot as an A2DP speaker. Always works
   when paired. (A2DP idles out, so clips are padded with ~800 ms of lead-in
   silence or the first word gets swallowed.)
3. **notify** — a desktop notification. The floor. Cannot fail.

A single lock (`speak.lock`) serialises utterances so two Claude Code panes
finishing at once don't talk over each other; when more than one session is
active, each utterance is prefixed with its project directory name.

### Don't block the agent

The Stop hook prints `{"async": true}` and runs the real work detached. Otherwise
you'd watch Claude Code hang while Piper synthesises audio. The hook is shell,
not Python, so there's no interpreter start-up on the turn's critical path.

---

## 3. State & files

| Location | Contents | Lifetime |
| --- | --- | --- |
| `~/.config/voxpane/` | `config.toml`, `commands.toml` | you own it |
| `~/.local/state/voxpane/` | `log` | persists |
| `$XDG_RUNTIME_DIR/voxpane/` | `state.json`, `record.pid`, `daemon.sock`, `ledger-<session_id>.jsonl`, `speak.lock` | wiped on logout |
| `/tmp/vp-<ts>.wav` | the in-flight recording | transient |

Runtime state is deliberately volatile — PIDs, sockets and per-session ledgers
have no business surviving a reboot. All paths come from `paths.py`; nothing
hard-codes them.

---

## 4. Extending

- **A new speaker backend** — subclass `speakers.base.Speaker`, implement
  `available()` and `speak()` (raise `SpeakerError` on failure), register it in
  `speakers.get_backend`, and add its name to `speak.backends`.
- **New voice commands** — edit `~/.config/voxpane/commands.toml`. No code.
- **Per-project vocabulary** — `voxpane vocab --from-repo` (M9) scans identifiers
  and extends `whisper.initial_prompt`, respecting the 224-token cap.

See [plans/voxpane-plan.md](plans/voxpane-plan.md) for the milestone-by-milestone
build spec and acceptance criteria.
