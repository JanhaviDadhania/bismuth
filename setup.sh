#!/bin/bash
set -e

echo "Setting up budee..."

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

# ─────────────────────────────────────────────
# Pulsar — disable welcome tabs on startup
# ─────────────────────────────────────────────

echo "Configuring Pulsar..."
PULSAR_CONFIG="$HOME/.pulsar/config.cson"
mkdir -p "$(dirname "$PULSAR_CONFIG")"

if [ ! -f "$PULSAR_CONFIG" ]; then
    cat > "$PULSAR_CONFIG" << 'EOF'
"*":
  welcome:
    showOnStartup: false
  "release-notes":
    showOnStartup: false
EOF
    echo "Pulsar config created."
elif grep -q "showOnStartup" "$PULSAR_CONFIG"; then
    echo "Pulsar welcome config already set, skipping."
else
    python3 - "$PULSAR_CONFIG" << 'PYEOF'
import sys
config_path = sys.argv[1]
with open(config_path, 'r') as f:
    content = f.read()
addition = '  welcome:\n    showOnStartup: false\n  "release-notes":\n    showOnStartup: false\n'
if '"*":' in content:
    content = content.replace('"*":\n', '"*":\n' + addition, 1)
else:
    content += '\n"*":\n' + addition
with open(config_path, 'w') as f:
    f.write(content)
print("Pulsar welcome config added.")
PYEOF
fi

echo ""
echo "Setup complete."
echo "Next: run ./login.sh to log into your social accounts."
