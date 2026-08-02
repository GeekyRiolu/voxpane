---
name: voxpane
description: >-
  Build, set up, configure, or debug voxpane — the local voice layer for Claude
  Code (push-to-talk Whisper dictation in, spoken Echo Dot summaries out). Use
  when working in the voxpane repo: implementing its milestones (M0–M9), running
  or extending `voxpane doctor`, wiring the tmux delivery / PostToolUse+Stop
  hooks / Alexa+Bluetooth speaker fallback chain, editing the command dictionary,
  or fixing its audio, recording, transcription, gating, or summarization
  pipeline.
---

# voxpane

voxpane is a bidirectional voice layer around Claude Code. **Inbound:**
push-to-talk → local Whisper → command-dictionary rewriting → injected into a
tmux pane (never auto-submits). **Outbound:** Claude Code hooks → an activity
ledger → a gated, spoken summary on an Echo Dot when a turn does real work.

## Sources of truth — read before acting

- **`docs/plans/voxpane-plan.md`** — the full build spec: milestones M0–M9, each
  with acceptance criteria, plus the config schema and command dictionary. This
  is authoritative; when in doubt, follow it.
- **`docs/ARCHITECTURE.md`** — how the two pipelines fit together and *why* each
  constraint exists.
- **The module you're touching** — every stub in `src/voxpane/` opens with its
  contract, signatures, and milestone tag.

Do not duplicate the plan into code comments or chat; cite it.

## You'll be asked to do one of two things

### A) Implement the next milestone (building voxpane)

The loop, once per milestone:

1. **Read** the milestone in `docs/plans/voxpane-plan.md` and its acceptance
   criteria. `M0` (`doctor`, in `src/voxpane/doctor.py`) is the reference for
   code style — mirror it.
2. **Check status:** `voxpane <cmd>` prints which milestone owns an unbuilt
   command; stubs raise `NotImplementedError("… — milestone Mx")`.
3. **Implement** the milestone's module(s) only. Keep `config.py`/`paths.py`
   usage; don't re-derive paths or defaults.
4. **Test** against the acceptance criteria — add/extend tests under `tests/`.
   `postprocess.py`, `summarize.py`, and the gate are pure and must be fully
   unit-tested. Mock every subprocess (`whisper-cli`, `alexa`, `piper`,
   `pw-play`, `tmux`).
5. **Verify & stop.** Run `make test` and, where relevant, exercise it by hand.
   Then report what you built and exactly how to test it. **Do not skip ahead**
   to a later milestone in the same pass.

| M | Owns | Key files |
| --- | --- | --- |
| M0 ✅ | environment checks | `doctor.py` |
| M1 | one-shot record→transcribe→clipboard | `recorder.py`, `transcriber.py` |
| M2 | toggle, keybind, notifications | `cli.py`, `notify.py`, `hypr/` |
| M3 | delivery (tmux/focus/clipboard) | `deliver.py` |
| M4 | command dictionary | `postprocess.py` |
| M5 | resident STT daemon | `daemon.py`, `systemd/` |
| M6 | ledger, hooks, the gate | `ledger.py`, `hooks/` |
| M7 | summarizer (facts/llm/hybrid) | `summarize.py` |
| M8 | Echo speaker backends + fallback | `speakers/` |
| M9 | polish (waybar, repo vocab, VAD) | — |

Ask before installing anything with `pacman`/`yay`.

### B) Set up or configure voxpane (using it)

1. `./install.sh` (or `--dry-run` to preview) — system deps, model, CLI, config.
2. `voxpane doctor` — fix every red row; hints tell you how. `docs/INSTALL.md`
   has the manual steps (mic check, whisper.cpp, choosing the Echo route).
3. Config lives in `~/.config/voxpane/{config,commands}.toml`. First knobs:
   `delivery.tmux_target`, `speak.alexa.device`, `speak.gate.*`, `summary.mode`.
4. `voxpane install-bindings` (keybind) and `voxpane install-hooks` (spoken
   summaries) — both must be idempotent and back up before editing.

## Non-negotiable constraints (each is a real bug)

- **Wayland only** — `wtype`/`wl-copy`, never `xdotool`/`xclip`.
- **Stop `pw-record` with SIGINT, not SIGKILL** — SIGKILL corrupts the WAV header.
- **`tmux send-keys -l`** for literal text, or `Enter`/`Space` become key names.
- **Never auto-submit by default** — only the per-utterance "send it" phrase, and
  only for that utterance; never mutate global config.
- **Guard the Stop hook on `stop_hook_active`** (exit 0) or you get a hook loop.
- **The Stop hook must not block Claude Code** — print `{"async": true}`, detach.
- **`last_assistant_message` is markdown** — reduce to spoken prose, never verbatim.
- **The gate is not optional** — speak only if the turn did real work, ran long
  enough, didn't end in a question, and isn't in quiet hours.
- **The `notify` speaker backend must never raise** — it's the floor of the chain.
- **Cap spoken text at `speak.max_chars`** on a sentence boundary.
- **Omarchy** overwrites `~/.config/hypr/bindings.conf` on update, and its binding
  format varies (`bindings.lua` `o.bind` vs `bindings.conf` `bindd`). Detect which
  exists; keep the repo snippet the source of truth; re-apply idempotently.

## Conventions

- Match the M0 `doctor.py` style: small pure-ish functions, a thin renderer,
  simple return values, per-row remediation hints, non-zero exit on failure.
- All filesystem locations come from `paths.py`; all config from `config.py`
  (deep-merge over defaults). Never hard-code a path or a default.
- Core stays dependency-free (stdlib); heavy deps (e.g. `faster-whisper`) are
  extras behind graceful fallback, so the tool never hard-fails.
- Commit per milestone with a clear message; `make lint test` green first.
