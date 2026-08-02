#!/usr/bin/env bash
# voxpane installer — system deps, Whisper model, the CLI, and config, in one go.
#
#   From a clone:   ./install.sh
#   One-liner:      curl -fsSL https://raw.githubusercontent.com/GeekyRiolu/voxpane/main/install.sh | bash
#
# Safe by default: nothing that touches your system (pacman, model download,
# CLI install) runs without a prompt. Pass --yes to accept all, --dry-run to see
# what it would do. See --help.
set -euo pipefail

REPO_URL="https://github.com/GeekyRiolu/voxpane.git"
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin"
MODEL_DIR="$HOME/.local/share/whisper-models"
MODEL_FILE="$MODEL_DIR/ggml-large-v3-turbo-q5_0.bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/voxpane"
SYSTEM_PKGS=(pipewire pipewire-pulse pipewire-audio wireplumber bluez bluez-utils \
             wl-clipboard wtype libnotify jq tmux uv sox)

ASSUME_YES=0
DRY_RUN=0
SKIP_SYSTEM=0
SKIP_MODEL=0
SKIP_WHISPER=0

# ---------------------------------------------------------------- pretty output
if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && [[ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]]; then
  BOLD=$(tput bold); DIM=$(tput dim); RED=$(tput setaf 1); GRN=$(tput setaf 2)
  YLW=$(tput setaf 3); BLU=$(tput setaf 4); RST=$(tput sgr0)
else
  BOLD=""; DIM=""; RED=""; GRN=""; YLW=""; BLU=""; RST=""
fi
section() { printf '\n%s==>%s %s%s%s\n' "$BLU" "$RST" "$BOLD" "$*" "$RST"; }
info()    { printf '    %s\n' "$*"; }
ok()      { printf '    %s✓%s %s\n' "$GRN" "$RST" "$*"; }
warn()    { printf '    %s!%s %s\n' "$YLW" "$RST" "$*"; }
err()     { printf '    %s✗%s %s\n' "$RED" "$RST" "$*" >&2; }

ask() {  # ask "question" -> 0 for yes. Honours --yes.
  [[ "$ASSUME_YES" -eq 1 ]] && return 0
  local reply
  printf '    %s?%s %s [y/N] ' "$YLW" "$RST" "$1"
  read -r reply </dev/tty || return 1
  [[ "$reply" =~ ^[Yy] ]]
}

run() {  # run a side-effecting command, or just print it under --dry-run
  if [[ "$DRY_RUN" -eq 1 ]]; then printf '    %s[dry-run]%s %s\n' "$DIM" "$RST" "$*"; return 0; fi
  printf '    %s$ %s%s\n' "$DIM" "$*" "$RST"
  "$@"
}

usage() {
  cat <<EOF
voxpane installer

Usage: ./install.sh [options]

Options:
  -y, --yes         accept all prompts (non-interactive)
      --dry-run     show what would happen, change nothing
      --skip-system skip system packages (pacman)
      --skip-whisper skip whisper.cpp
      --skip-model  skip the Whisper model download (~550 MB)
  -h, --help        this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes) ASSUME_YES=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --skip-system) SKIP_SYSTEM=1 ;;
    --skip-whisper) SKIP_WHISPER=1 ;;
    --skip-model) SKIP_MODEL=1 ;;
    -h|--help) usage; exit 0 ;;
    *) err "unknown option: $1"; usage; exit 2 ;;
  esac
  shift
done

# ------------------------------------------------------ locate or clone the repo
HERE=""
if [[ -n "${BASH_SOURCE[0]:-}" && -f "$(dirname "${BASH_SOURCE[0]}")/pyproject.toml" ]]; then
  HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [[ -z "$HERE" ]]; then
  section "Fetching voxpane"
  DEST="${VOXPANE_SRC:-$HOME/.local/share/voxpane/src}"
  if [[ -d "$DEST/.git" ]]; then
    info "Updating existing checkout at $DEST"
    run git -C "$DEST" pull --ff-only
  else
    command -v git >/dev/null 2>&1 || { err "git is required to bootstrap"; exit 1; }
    run mkdir -p "$(dirname "$DEST")"
    run git clone "$REPO_URL" "$DEST"
  fi
  HERE="$DEST"
  [[ "$DRY_RUN" -eq 1 ]] || exec bash "$HERE/install.sh" "$@"
fi
cd "$HERE"

printf '%s%svoxpane installer%s  %s%s%s\n' "$BOLD" "$BLU" "$RST" "$DIM" "$HERE" "$RST"

# ------------------------------------------------------------------- 1. distro
section "Checking your system"
if [[ "$(uname -s)" != "Linux" ]]; then
  err "voxpane targets Linux (Wayland/Hyprland). Aborting."; exit 1
fi
HAS_PACMAN=0; command -v pacman >/dev/null 2>&1 && HAS_PACMAN=1
if [[ "$HAS_PACMAN" -eq 1 ]]; then ok "Arch-based system detected"; else
  warn "Not an Arch-based distro — install these yourself: ${SYSTEM_PKGS[*]}"
fi
[[ "${WAYLAND_DISPLAY:-}" ]] && ok "Wayland session" || warn "No \$WAYLAND_DISPLAY — voxpane needs Wayland at runtime"

# --------------------------------------------------------- 2. system packages
if [[ "$SKIP_SYSTEM" -eq 0 && "$HAS_PACMAN" -eq 1 ]]; then
  section "System packages"
  missing=()
  for p in "${SYSTEM_PKGS[@]}"; do pacman -Qq "$p" >/dev/null 2>&1 || missing+=("$p"); done
  if [[ "${#missing[@]}" -eq 0 ]]; then ok "all present"; else
    info "Missing: ${missing[*]}"
    if ask "Install them with sudo pacman -S --needed?"; then
      run sudo pacman -S --needed "${missing[@]}"
    else warn "skipped — install manually or voxpane doctor will flag them"; fi
  fi
fi

# ------------------------------------------------------------- 3. whisper.cpp
if [[ "$SKIP_WHISPER" -eq 0 ]] && ! command -v whisper-cli >/dev/null 2>&1; then
  section "whisper.cpp"
  if command -v yay >/dev/null 2>&1; then
    ask "Install whisper.cpp from the AUR (yay -S whisper.cpp)?" && run yay -S whisper.cpp \
      || warn "skipped — build it yourself (docs/INSTALL.md §1.3)"
  else
    warn "no AUR helper; build whisper.cpp yourself (docs/INSTALL.md §1.3)"
  fi
fi

# ------------------------------------------------------------------- 4. model
if [[ "$SKIP_MODEL" -eq 0 && ! -f "$MODEL_FILE" ]]; then
  section "Whisper model (large-v3-turbo, ~550 MB)"
  if ask "Download the model to $MODEL_DIR?"; then
    run mkdir -p "$MODEL_DIR"
    if command -v curl >/dev/null 2>&1; then run curl -fL# -o "$MODEL_FILE" "$MODEL_URL"
    elif command -v wget >/dev/null 2>&1; then run wget -O "$MODEL_FILE" "$MODEL_URL"
    else err "need curl or wget"; fi
  else warn "skipped — download later (docs/INSTALL.md §1.4)"; fi
elif [[ -f "$MODEL_FILE" ]]; then
  ok "model already present"
fi

# ----------------------------------------------------------- 5. the voxpane CLI
section "Installing the voxpane CLI"
if command -v uv >/dev/null 2>&1; then
  run uv tool install --from "$HERE" --force voxpane
elif command -v pipx >/dev/null 2>&1; then
  run pipx install --force "$HERE"
else
  warn "no uv or pipx found."
  info "Install one, then re-run — Arch's Python is externally managed, so a"
  info "plain 'pip install' will refuse. 'pacman -S uv' is the quickest fix."
fi

# ------------------------------------------------------------------ 6. config
section "Config"
run mkdir -p "$CONFIG_DIR"
for f in config commands; do
  src="$HERE/config/$f.default.toml"; dst="$CONFIG_DIR/$f.toml"
  if [[ -f "$dst" ]]; then ok "$f.toml exists (left untouched)"
  else run cp "$src" "$dst"; ok "wrote $dst"; fi
done

# --------------------------------------------------------------- 7. PATH hint
case ":$PATH:" in
  *":$HOME/.local/bin:"*) : ;;
  *) warn "Add ~/.local/bin to your PATH so 'voxpane' is found:"
     info "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc" ;;
esac

# ----------------------------------------------------------------- 8. doctor
section "Verifying (voxpane doctor)"
if [[ "$DRY_RUN" -eq 1 ]]; then
  info "[dry-run] would run: voxpane doctor"
elif command -v voxpane >/dev/null 2>&1; then
  voxpane doctor || true
else
  "$HERE/bin/voxpane" doctor || true
fi

# --------------------------------------------------------------- next steps
section "Next steps"
cat <<EOF
    1. Fix anything red above (mostly one-off pacman/model steps).
    2. Bind push-to-talk:       voxpane install-bindings     (suggests SUPER ALT V)
    3. Wire up spoken summaries: voxpane install-hooks
    4. Start a Claude Code tmux session named 'claude':
           tmux new-session -s claude   # then run: claude
    5. Read the plan & architecture:  docs/plans/voxpane-plan.md, docs/ARCHITECTURE.md

    ${DIM}Note: milestones M1–M9 are stubbed. 'voxpane doctor' works today; the
    voice pipeline is built out per docs/plans/voxpane-plan.md.${RST}
EOF
