"""voxpane — a bidirectional voice layer for Claude Code.

Inbound:  push-to-talk -> local Whisper -> command-dictionary rewriting ->
          injected into a tmux pane running Claude Code.
Outbound: Claude Code lifecycle hooks -> activity ledger -> spoken summary on
          an Echo Dot when a turn completes.

Speech in is fully local (Whisper). Nothing about your audio leaves the machine.

See ``docs/plans/voxpane-plan.md`` for the full build spec and milestones, and
``docs/ARCHITECTURE.md`` for how the pieces fit together.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.2.0"
