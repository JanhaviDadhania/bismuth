#!/bin/bash
set -e

echo "Setting up bismuth..."

# ─────────────────────────────────────────────
# Python dependencies
# ─────────────────────────────────────────────

echo "Installing Python dependencies..."
pip3 install -r requirements.txt

# ─────────────────────────────────────────────
# Silicon browser
# ─────────────────────────────────────────────

echo "Installing silicon-browser..."
npm install -g silicon-browser
silicon-browser install

# ─────────────────────────────────────────────
# Claude CLI
# ─────────────────────────────────────────────

if ! command -v claude &> /dev/null; then
    echo "Claude CLI not found. Install it from: https://claude.ai/code"
    exit 1
fi

echo ""
echo "Setup complete."
echo "Next: run ./login.sh to log into your social accounts."
