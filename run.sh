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
# Periodic memory sync (every 15 minutes)
# After 3 consecutive failures, alert the agent via the synthetic inbox
# (once per failure streak) so janhavi hears about it on Telegram.
# ─────────────────────────────────────────────

notify_sync_failure() {
  local inbox="$BISMUTH_MEMORY_DIR/.harness/synthetic_inbox"
  mkdir -p "$inbox"
  local name="memory_sync_failure_$(date +%s).txt"
  printf '%s' "[memory-sync: git sync has failed $1 times in a row — local edits may not be reaching origin. Check network or rebase conflicts in $BISMUTH_MEMORY_DIR, and tell janhavi.]" > "$inbox/$name.tmp"
  mv "$inbox/$name.tmp" "$inbox/$name"
}

(SYNC_FAILS=0; SYNC_NOTIFIED=0
while true; do
  sleep 900
  ok=1
  git -C "$BISMUTH_MEMORY_DIR" add -A || { echo "[memory-sync] add failed"; ok=0; }
  if ! git -C "$BISMUTH_MEMORY_DIR" diff --cached --quiet; then
    git -C "$BISMUTH_MEMORY_DIR" commit -m "periodic sync" || { echo "[memory-sync] commit failed"; ok=0; }
  fi
  git -C "$BISMUTH_MEMORY_DIR" pull --rebase || { echo "[memory-sync] pull --rebase failed — local edits may not reach origin"; ok=0; }
  git -C "$BISMUTH_MEMORY_DIR" push || { echo "[memory-sync] push failed — local edits did NOT reach origin"; ok=0; }
  if [ "$ok" -eq 1 ]; then
    SYNC_FAILS=0; SYNC_NOTIFIED=0
  else
    SYNC_FAILS=$((SYNC_FAILS + 1))
    if [ "$SYNC_FAILS" -ge 3 ] && [ "$SYNC_NOTIFIED" -eq 0 ]; then
      notify_sync_failure "$SYNC_FAILS"
      SYNC_NOTIFIED=1
    fi
  fi
done) &
SYNC_PID=$!
echo "memory sync started (pid $SYNC_PID)"

# ─────────────────────────────────────────────
# Shutdown on Ctrl+C
# ─────────────────────────────────────────────

trap "echo 'Stopping...'; kill $SYNC_PID 2>/dev/null; exit 0" SIGINT SIGTERM

# ─────────────────────────────────────────────
# Run harness (foreground; Ctrl+C stops both this and the sync loop)
# ─────────────────────────────────────────────

echo "Starting bismuth harness..."
python3 "$DIR/harness.py"
