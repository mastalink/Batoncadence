#!/usr/bin/env bash
# ============================================================================
# BatonCadence — bootstrap installer
# ============================================================================
# Usage:
#   curl -sSf https://batoncadence.com/install.sh | bash
#   # or, if stdin acts up:
#   bash <(curl -sSf https://batoncadence.com/install.sh)
#
# What this does:
#   1. Clones the repo to ~/BatonCadence (or pulls updates if it exists)
#   2. Hands off to scripts/install.sh for the real setup
# ============================================================================
set -euo pipefail

GRN='\033[0;32m'; CYN='\033[0;36m'; YLW='\033[0;33m'; RED='\033[0;31m'; NC='\033[0m'

REPO="https://github.com/mastalink/Batoncadence"
DEST="${BATONCADENCE_INSTALL_DIR:-$HOME/BatonCadence}"

echo ""
echo -e "${CYN}  BatonCadence installer${NC}"
echo -e "${CYN}  =======================${NC}"
echo ""

# Restore terminal stdin if we were piped through curl
if [ ! -t 0 ]; then
    exec </dev/tty
fi

if [ -d "$DEST/.git" ]; then
    echo -e "${CYN}->  Found existing install at $DEST — pulling updates...${NC}"
    git -C "$DEST" pull --ff-only origin main 2>/dev/null || {
        echo -e "${YLW}[!]  Could not pull (offline or local changes). Continuing with current version.${NC}"
    }
else
    if [ -d "$DEST" ] && [ "$(ls -A "$DEST" 2>/dev/null)" ]; then
        echo -e "${RED}[X]  $DEST exists and is not empty. Move it or set BATONCADENCE_INSTALL_DIR.${NC}"
        exit 1
    fi

    if ! command -v git &>/dev/null; then
        echo -e "${RED}[X]  git is required. Install it and retry.${NC}"
        exit 1
    fi

    echo -e "${CYN}->  Cloning BatonCadence to $DEST...${NC}"
    git clone --depth 1 "$REPO" "$DEST"
fi

echo -e "${GRN}[OK] Repository ready at $DEST${NC}"
echo ""

exec bash "$DEST/scripts/install.sh" "$@"
