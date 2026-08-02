# Contributing to voxpane

Thanks for helping build voxpane. The fastest way in: pick a stubbed milestone,
implement it against its acceptance criteria, keep the pure modules pure and
tested.

## Dev setup

```bash
git clone https://github.com/GeekyRiolu/voxpane.git
cd voxpane
make dev            # editable install with dev + daemon extras (uv, pip fallback)
make test           # pytest
make lint           # ruff
```

No install needed to hack: `./bin/voxpane <cmd>` runs straight from the tree, and
`pytest` finds the package via `pythonpath = ["src"]`.

## How the code is organised

`src/voxpane/` is one package with two pipelines (inbound, outbound) that share
`cli.py`, `config.py` and `paths.py`. Read **[ARCHITECTURE.md](ARCHITECTURE.md)**
first, then the module docstring for whatever you're touching — each stub states
its contract, its signatures, and its milestone.

## The milestones

The build order and per-milestone acceptance tests live in
**[plans/voxpane-plan.md](plans/voxpane-plan.md)**. Implement in order; each stub
is tagged (`# milestone M4`) and `voxpane <cmd>` tells you which milestone owns an
unbuilt command. M0 (`doctor`) is done and is the reference for the code style:
small pure-ish functions, a thin renderer, simple return values.

## Rules that aren't negotiable

These are encoded as constraints in the plan because each one is a real bug that
bit someone. Respect them:

- **Wayland only.** `wtype` / `wl-copy`, never `xdotool` / `xclip`.
- **SIGINT `pw-record`, never SIGKILL** — SIGKILL corrupts the WAV header.
- **`tmux send-keys -l`** for literal text.
- **Never auto-submit by default.** Only the per-utterance "send it" phrase opts
  in, and only for that utterance.
- **Guard the Stop hook on `stop_hook_active`** or you get a hook loop.
- **The Stop hook must not block Claude Code** — `{"async": true}`, then detach.
- **`last_assistant_message` is markdown** — never speak it verbatim.
- **The `notify` speaker backend must never raise.** It's the floor of the chain.
- **Cap spoken text at `max_chars`** on a sentence boundary.

## Testing

- `postprocess.py`, `summarize.py`, and the gate are **pure and must be fully
  unit-tested** — that's where the bugs and the annoyance live.
- Mock every subprocess (`whisper-cli`, `alexa`, `piper`, `pw-play`, `tmux`).
- Keep integration tests behind `VOXPANE_INTEGRATION=1`.
- Fixtures: recorded WAVs in `tests/fixtures/audio/`, captured hook stdin payloads
  in `tests/fixtures/hooks/`, so transcription and the outbound path are
  regression-testable without a mic or a live Echo.

## Commits & PRs

- Conventional-ish commit subjects (`feat:`, `fix:`, `docs:`, `test:`…).
- One milestone (or one coherent slice) per PR; note which acceptance criteria
  you met.
- `make lint test` green before you push.

## Using the skill

The repo's own skill (`.claude/skills/voxpane/`) knows all of the above. In
Claude Code, *"implement milestone M3"* will scaffold the work with these
constraints already in mind — a good starting point to review rather than a
finish line.
