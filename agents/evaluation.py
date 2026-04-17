"""
Evaluation Agent
Reads all tracking files and sends a weekly report to janhavi via Telegram.
Run manually once a week: python agents/evaluation.py
"""

import json
import sys
from pathlib import Path

import anthropic

# ─────────────────────────────────────────────
# Tool Imports
# ─────────────────────────────────────────────

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.telegram import TOOL_DESCRIPTIONS as _telegram_tools, run_tool as _telegram_run
from tools.terminal import TOOL_DESCRIPTIONS as _terminal_tools, run_tool as _terminal_run
from config import BASE_DIR, MEMORY_DIR

# ─────────────────────────────────────────────
# Tool Setup — read-only terminal + telegram send
# ─────────────────────────────────────────────

_ALLOWED = {
    "telegram": {"send_message"},
    "terminal": {"read_file", "grep"},
}

_RUNNERS = {}
for t in _telegram_tools:
    if t["name"] in _ALLOWED["telegram"]:
        _RUNNERS[t["name"]] = _telegram_run
for t in _terminal_tools:
    if t["name"] in _ALLOWED["terminal"]:
        _RUNNERS[t["name"]] = _terminal_run

_RAW_TOOLS = (
    [t for t in _telegram_tools if t["name"] in _ALLOWED["telegram"]] +
    [t for t in _terminal_tools  if t["name"] in _ALLOWED["terminal"]]
)


# ─────────────────────────────────────────────
# Convert tool descriptions to Anthropic format
# ─────────────────────────────────────────────

def _to_anthropic_tool(tool: dict) -> dict:
    params = tool.get("parameters", {})
    properties = {}
    required = []

    for name, spec in params.items():
        prop = {k: v for k, v in spec.items() if k != "default"}
        properties[name] = prop
        if "default" not in spec:
            required.append(name)

    return {
        "name": tool["name"],
        "description": tool["description"],
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


TOOLS = [_to_anthropic_tool(t) for t in _RAW_TOOLS]


# ─────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────

def run():
    prompt_path = BASE_DIR / "prompts" / "evaluation.md"
    system = prompt_path.read_text().replace("memory/", f"{MEMORY_DIR}/")

    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": "Generate and send the weekly report now."}]

    while True:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            system=system,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    if block.name in _RUNNERS:
                        result = _RUNNERS[block.name](block.name, block.input)
                    else:
                        result = {"success": False, "error": f"Unknown tool: {block.name}"}

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })

            messages.append({"role": "user", "content": tool_results})
        else:
            break


if __name__ == "__main__":
    print("Generating weekly report...")
    run()
    print("Done.")
