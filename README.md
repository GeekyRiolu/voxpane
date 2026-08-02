<div align="center">

# voxpane

**Talk to Claude Code, and have your Echo Dot tell you what it did.**

Press a key, speak a prompt, and it lands in your Claude Code pane. When Claude
finishes the turn, your Echo Dot reads out what it did.

Speech in is fully local (Whisper). Speech out goes to a real Echo Dot.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
![Platform](https://img.shields.io/badge/platform-Linux%20%C2%B7%20Wayland%2FHyprland-informational)
![Status](https://img.shields.io/badge/status-alpha-orange)
![STT](https://img.shields.io/badge/STT-100%25%20local-brightgreen)

</div>

---

## What it is

voxpane is a bidirectional voice layer around a terminal coding agent:

- **Inbound** — push-to-talk → local Whisper → command-dictionary rewriting →
  injected into a tmux pane running Claude Code. It never auto-submits: your
  words land in the input box and *you* press Enter.
- **Outbound** — Claude Code lifecycle hooks → an activity ledger → a short
  spoken summary on an Echo Dot when a turn completes. Gated hard, so it only
  speaks when something real happened.

It's the difference between babysitting a long agent run and walking away to make
coffee while the Dot tells you "four files changed in voxpane, tests ran clean."

> **Privacy:** audio never leaves your machine. STT is whisper.cpp / faster-whisper,
> local, always. The only network call is the *optional* spoken summary to your
> own Echo — and even that falls back to a local voice or a desktop notification.

## Architecture

```
INBOUND
  [SUPER ALT V]
       │ toggle
       ▼
  voxpane CLI ──unix socket──▶ voxpaned (Whisper model resident in RAM)
       │                            │
  pw-record → /tmp/vp-<ts>.wav ─────┘
                                    │ transcribe
                                    │ postprocess (command dictionary)
                                    ▼
                     tmux send-keys -l → Claude Code pane
                              (never auto-submits)

OUTBOUND
  Claude Code
       │
       ├─ PostToolUse hook ──▶ append to ledger.jsonl  (files touched, cmds run)
       │
       └─ Stop hook ─────────▶ voxpane speak --from-hook
                                    │
                              gate: did this turn do real work?
                                    │ yes
                              summarize: ledger facts + one-line LLM polish
                                    │
                              speaker backend chain:
                                 alexa → bluetooth → notify
                                    │
                                    ▼
                                 Echo Dot
```

Two independent paths share one CLI. The inbound path optimises for latency (a
resident model behind a socket); the outbound path optimises for *not being
annoying* (a deterministic ledger of facts, a strict gate, and a fallback chain
that can never hard-fail). See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**
for the full design and the reasoning behind each constraint.

## Requirements

- **Arch Linux** (or derivative) on a **Wayland / Hyprland** session. The inbound
  path uses `wtype` and `wl-copy`; X11 tools like `xdotool` do not work here.
- A working **microphone** (your laptop's built-in mic — the Echo can't be an
  input device over Bluetooth).
- **whisper.cpp** + a Whisper model (`large-v3-turbo`, ~550 MB).
- An **Echo Dot** *(optional)* for spoken output — otherwise summaries arrive as
  desktop notifications.
- Python **3.11+**.

## Quick start

```bash
git clone https://github.com/GeekyRiolu/voxpane.git
cd voxpane
./install.sh
```

Or, in one line:

```bash
curl -fsSL https://raw.githubusercontent.com/GeekyRiolu/voxpane/main/install.sh | bash
```

`install.sh` is safe by default — it prompts before installing system packages,
downloading the model, or installing the CLI (use `--yes` to accept all,
`--dry-run` to preview). It finishes by running `voxpane doctor`. Some steps
(the mic check, choosing your Echo output route) are worth doing by hand — see
**[docs/INSTALL.md](docs/INSTALL.md)**.

Then verify:

```bash
voxpane doctor
```

```
voxpane doctor

  ✓  pw-record      /usr/bin/pw-record
  ✓  whisper-cli    /usr/bin/whisper-cli
  ✓  wtype          /usr/bin/wtype
  ✓  wl-copy        /usr/bin/wl-copy
  ✓  tmux           /usr/bin/tmux
  ✓  notify-send    /usr/bin/notify-send
  ✓  jq             /usr/bin/jq
  ✓  whisper model  ggml-large-v3-turbo-q5_0.bin (547 MB)
  ✓  audio source   Volume: 0.75
  ✓  runtime dir    /run/user/1000/voxpane
  ✓  tmux target    session 'claude' exists

All checks passed.
```

## Usage

```bash
voxpane doctor              # verify the environment (start here)
voxpane install-bindings    # bind push-to-talk (suggests SUPER ALT V)
voxpane install-hooks       # wire spoken summaries into Claude Code
voxpane toggle              # start/stop recording (what the keybind calls)
voxpane speak "hello"       # test the outbound speaker chain
```

Day to day: start Claude Code in a tmux session named `claude`, press
**SUPER ALT V**, speak, press it again, read the transcript in the pane, hit
Enter. Walk away. The Dot tells you what happened.

## Configuration

`install.sh` seeds two files in `~/.config/voxpane/`:

- **`config.toml`** — audio, Whisper, delivery, the outbound gate, and speaker
  backends. Templated from [`config/config.default.toml`](config/config.default.toml).
- **`commands.toml`** — the voice command dictionary (slash commands, symbols,
  identifier-case transforms, Whisper fixups). Templated from
  [`config/commands.default.toml`](config/commands.default.toml).

The knobs you'll reach for first:

| Setting | What it does |
| --- | --- |
| `delivery.tmux_target` | which tmux pane dictation lands in (default `claude:0.0`) |
| `delivery.auto_submit` | press Enter for you (default `false` — leave it off) |
| `speak.backends` | fallback order, e.g. `["alexa", "bluetooth", "notify"]` |
| `speak.gate.min_turn_seconds` | stay silent for turns shorter than this |
| `speak.alexa.device` | your Echo's name, e.g. `"Office Dot"` |
| `summary.mode` | `facts` · `llm` · `hybrid` — how the summary is built |

## Project layout

```
voxpane/
├── install.sh              # one-command setup
├── pyproject.toml          # package (zero core deps; extras for the daemon)
├── bin/voxpane             # run from a clone without installing
├── src/voxpane/            # the package — see docs/ARCHITECTURE.md
│   ├── cli.py  config.py  doctor.py  paths.py  notify.py
│   ├── recorder.py  transcriber.py  postprocess.py  deliver.py
│   ├── ledger.py  summarize.py  daemon.py
│   └── speakers/           # alexa · bluetooth · notify (fallback chain)
├── config/                 # config.default.toml, commands.default.toml
├── hooks/                  # Claude Code PostToolUse + Stop hooks
├── hypr/bindings.snippet   # tracked keybinding source of truth
├── systemd/                # voxpaned.service (--user)
├── tests/
├── docs/
│   ├── ARCHITECTURE.md     # how it all fits together
│   ├── INSTALL.md          # manual setup (mic, model, Echo route)
│   ├── CONTRIBUTING.md
│   └── plans/voxpane-plan.md   # the full build spec & milestones
└── .claude/skills/voxpane/ # the skill that builds & sets up voxpane
```

## Roadmap

voxpane is built in milestones (full spec: [docs/plans/voxpane-plan.md](docs/plans/voxpane-plan.md)).

| | Milestone | Status |
| --- | --- | --- |
| **M0** | `voxpane doctor` — environment checks | ✅ done |
| **M1** | one-shot inbound (record → transcribe → clipboard) | ✅ done |
| M2 | toggle, keybind, recording notifications | ⏳ stubbed |
| M3 | delivery backends (tmux / focus / clipboard) | ⏳ stubbed |
| M4 | post-processing (command dictionary) | ⏳ stubbed |
| M5 | daemon (resident model, sub-1.2s latency) | ⏳ stubbed |
| M6 | outbound plumbing (ledger, hooks, the gate) | ⏳ stubbed |
| M7 | summarizer (facts / llm / hybrid) | ⏳ stubbed |
| M8 | Echo speaker backends + fallback chain | ⏳ stubbed |
| M9 | polish (waybar, repo vocab, VAD auto-stop) | ⏳ stubbed |

Each stubbed module carries its contract and milestone tag. The bundled skill
drives the build.

## The skill

This repo ships a Claude Code skill at
[`.claude/skills/voxpane/`](.claude/skills/voxpane/SKILL.md). Open the repo in
Claude Code and it activates automatically; it knows the plan, the milestone
order, and every hard-won constraint (SIGINT not SIGKILL, `send-keys -l`, gate
the Stop hook…). Ask it to *"implement the next milestone"* or *"help me set up
voxpane"* and it drives the work. Install it globally with:

```bash
mkdir -p ~/.claude/skills && cp -r .claude/skills/voxpane ~/.claude/skills/
```

## Non-goals

- No wake word, no always-on listening.
- No cloud STT. Ever. Audio does not leave the machine.
- Not a general voice-control system (that's [Talon](https://talonvoice.com)'s job).
- Not an Alexa Skill. Nothing here is published to Amazon.

## Contributing

Issues and PRs welcome — pick a stubbed milestone and go. See
**[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)** for the dev loop, testing rules,
and the constraints you must respect.

## License

[GPL-3.0-or-later](LICENSE).
