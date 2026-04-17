#!/bin/bash
# One-time login script. Run this once per machine.
# Logs into each social platform under the shared 'budee' silicon-browser profile.
# Once logged in, close the browser — the session is saved automatically.

PROFILE="budee"

echo "Opening social platforms for login. Log in to each, then close the browser."
echo "Your sessions will be saved to the '$PROFILE' profile and reused by agents."
echo ""

sites=(
    "https://twitter.com"
    "https://linkedin.com"
    "https://instagram.com"
    "https://reddit.com"
)

for site in "${sites[@]}"; do
    echo "Opening $site — log in, then close the browser window."
    silicon-browser --profile $PROFILE open "$site"
    read -p "Press Enter when done with $site..."
    echo ""
done

echo "Login complete. Agents will reuse these sessions automatically."
