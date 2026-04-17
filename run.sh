#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

# ─────────────────────────────────────────────
# Load env from config.yaml
# ─────────────────────────────────────────────

export TELEGRAM_BOT_TOKEN=$(python3 -c "import yaml; c=yaml.safe_load(open('$DIR/config.yaml')); print(c['env']['TELEGRAM_BOT_TOKEN'])")
export TELEGRAM_CHAT_ID=$(python3 -c "import yaml; c=yaml.safe_load(open('$DIR/config.yaml')); print(c['env']['TELEGRAM_CHAT_ID'])")
export BISMUTH_MEMORY_DIR=$(python3 -c "import yaml, os; c=yaml.safe_load(open('$DIR/config.yaml')); print(os.path.expanduser(c.get('memory_path', '$DIR/memory')))")

# ─────────────────────────────────────────────
# Sync memory repo before starting
# ─────────────────────────────────────────────

echo "Syncing memory from $BISMUTH_MEMORY_DIR..."
git -C "$BISMUTH_MEMORY_DIR" pull --rebase 2>/dev/null || echo "Memory sync skipped (not a git repo or no remote)"

# ─────────────────────────────────────────────
# Spawn agents
# ─────────────────────────────────────────────

echo "Starting bismuth..."

python3 "$DIR/agents/capture.py" &
CAPTURE_PID=$!
echo "capture started (pid $CAPTURE_PID)"

python3 "$DIR/agents/clarify.py" &
CLARIFY_PID=$!
echo "clarify started (pid $CLARIFY_PID)"

echo "All agents running. Press Ctrl+C to stop."

# ─────────────────────────────────────────────
# Periodic memory sync (every 15 minutes)
# ─────────────────────────────────────────────

(while true; do
  sleep 900
  git -C "$BISMUTH_MEMORY_DIR" add . && \
    git -C "$BISMUTH_MEMORY_DIR" commit -m "periodic sync" && \
    git -C "$BISMUTH_MEMORY_DIR" push 2>/dev/null || true
done) &
SYNC_PID=$!
echo "memory sync started (pid $SYNC_PID)"

# ─────────────────────────────────────────────
# Shutdown on Ctrl+C
# ─────────────────────────────────────────────

trap "echo 'Stopping...'; kill $CAPTURE_PID $CLARIFY_PID $SYNC_PID 2>/dev/null; exit 0" SIGINT SIGTERM

wait
