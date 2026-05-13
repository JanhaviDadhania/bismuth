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
if git -C "$BISMUTH_MEMORY_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  git -C "$BISMUTH_MEMORY_DIR" add -A
  if ! git -C "$BISMUTH_MEMORY_DIR" diff --cached --quiet; then
    git -C "$BISMUTH_MEMORY_DIR" commit -m "startup sync"
  fi
  git -C "$BISMUTH_MEMORY_DIR" pull --rebase
  git -C "$BISMUTH_MEMORY_DIR" push
else
  echo "Memory sync skipped (not a git repo)"
fi

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
  git -C "$BISMUTH_MEMORY_DIR" add -A || echo "[memory-sync] add failed"
  if ! git -C "$BISMUTH_MEMORY_DIR" diff --cached --quiet; then
    git -C "$BISMUTH_MEMORY_DIR" commit -m "periodic sync" || echo "[memory-sync] commit failed"
  fi
  git -C "$BISMUTH_MEMORY_DIR" pull --rebase || echo "[memory-sync] pull --rebase failed — local edits may not reach origin"
  git -C "$BISMUTH_MEMORY_DIR" push || echo "[memory-sync] push failed — local edits did NOT reach origin"
done) &
SYNC_PID=$!
echo "memory sync started (pid $SYNC_PID)"

# ─────────────────────────────────────────────
# Shutdown on Ctrl+C
# ─────────────────────────────────────────────

trap "echo 'Stopping...'; kill $CAPTURE_PID $CLARIFY_PID $SYNC_PID 2>/dev/null; exit 0" SIGINT SIGTERM

wait
