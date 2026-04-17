"""
Browser Tool
Web automation for GTD agents via silicon-browser CLI.
All commands run under the shared --profile budee so agents
reuse your logged-in sessions automatically.

Install: npm install -g silicon-browser && silicon-browser install
Login:   silicon-browser --profile budee open <url>  (do this once per site)
"""

import subprocess
import os

PROFILE = "budee"


# ─────────────────────────────────────────────
# Internal Runner
# ─────────────────────────────────────────────

def _run(*args, stdin: str = None) -> dict:
    cmd = ["silicon-browser", "--profile", PROFILE] + list(args)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            input=stdin,
            env=os.environ.copy()
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            return {"success": False, "error": result.stderr.strip() or output}
        return {"success": True, "output": output}
    except FileNotFoundError:
        return {"success": False, "error": "silicon-browser is not installed. Run: npm install -g silicon-browser"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────
# Tool Functions
# ─────────────────────────────────────────────

def open_url(url: str) -> dict:
    """Navigate to a URL."""
    return _run("open", url)


def snapshot() -> dict:
    """Get all interactive elements on the current page as @refs.
    Always call this after open_url or after any navigation to get fresh refs.
    Use the returned refs in click, fill, get_text, etc."""
    return _run("snapshot", "-i")


def click(ref: str) -> dict:
    """Click an element by its @ref from snapshot."""
    return _run("click", ref)


def fill(ref: str, text: str) -> dict:
    """Clear a field and type text into it. Use the @ref from snapshot."""
    return _run("fill", ref, text)


def get_text(ref: str) -> dict:
    """Get the visible text content of an element by its @ref."""
    return _run("get", "text", ref)


def get_page_content() -> dict:
    """Get the full visible text content of the current page."""
    js = "document.body.innerText"
    return _run("eval", "-b", _b64(js))


def scroll(direction: str, amount: int = 500) -> dict:
    """Scroll the page. direction is 'up' or 'down', amount is pixels."""
    return _run("scroll", direction, str(amount))


def wait_for(text: str) -> dict:
    """Wait until the given text appears on the page."""
    return _run("wait", "--text", text)


def wait_for_load() -> dict:
    """Wait for the page to fully load after navigation."""
    return _run("wait", "--load", "networkidle")


def screenshot(save_path: str) -> dict:
    """Take a screenshot of the current page and save it to save_path."""
    return _run("screenshot", save_path)


def go_back() -> dict:
    """Navigate back to the previous page."""
    return _run("back")


def get_url() -> dict:
    """Get the current page URL."""
    return _run("get", "url")


def get_title() -> dict:
    """Get the current page title."""
    return _run("get", "title")


def eval_js(code: str) -> dict:
    """Evaluate JavaScript on the current page and return the result.
    Use this for extracting structured data or checking page state."""
    return _run("eval", "--stdin", stdin=code)


def close() -> dict:
    """Close the browser. Call this when done to avoid leaked processes."""
    return _run("close")


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _b64(text: str) -> str:
    import base64
    return base64.b64encode(text.encode()).decode()


# ─────────────────────────────────────────────
# Tool Descriptions
# ─────────────────────────────────────────────

TOOL_DESCRIPTIONS = [
    {
        "name": "open_url",
        "description": "Navigate the browser to a URL. Always call snapshot after this to get interactive elements.",
        "parameters": {
            "url": {"type": "string", "description": "The URL to navigate to"}
        }
    },
    {
        "name": "snapshot",
        "description": "Get all interactive elements on the current page. Returns @refs like @e1, @e2 that you use in click, fill, get_text. Always call this after open_url or after any page navigation — refs are invalidated on navigation.",
        "parameters": {}
    },
    {
        "name": "click",
        "description": "Click an element. Get the @ref from snapshot first.",
        "parameters": {
            "ref": {"type": "string", "description": "Element ref from snapshot, e.g. @e1"}
        }
    },
    {
        "name": "fill",
        "description": "Clear a form field and type text into it. Get the @ref from snapshot first.",
        "parameters": {
            "ref": {"type": "string", "description": "Element ref from snapshot, e.g. @e2"},
            "text": {"type": "string", "description": "Text to type into the field"}
        }
    },
    {
        "name": "get_text",
        "description": "Get the visible text of a specific element by its @ref.",
        "parameters": {
            "ref": {"type": "string", "description": "Element ref from snapshot"}
        }
    },
    {
        "name": "get_page_content",
        "description": "Get the full visible text content of the current page. Use this to read articles, docs, or any page content.",
        "parameters": {}
    },
    {
        "name": "scroll",
        "description": "Scroll the page up or down.",
        "parameters": {
            "direction": {"type": "string", "description": "'up' or 'down'"},
            "amount": {"type": "integer", "description": "Pixels to scroll. Default is 500.", "default": 500}
        }
    },
    {
        "name": "wait_for",
        "description": "Wait until specific text appears on the page. Use after clicking buttons that trigger loading.",
        "parameters": {
            "text": {"type": "string", "description": "Text to wait for on the page"}
        }
    },
    {
        "name": "wait_for_load",
        "description": "Wait for the page to fully load. Call this after navigation or form submission.",
        "parameters": {}
    },
    {
        "name": "screenshot",
        "description": "Take a screenshot of the current page.",
        "parameters": {
            "save_path": {"type": "string", "description": "Local path to save the screenshot, e.g. memory/screenshot.png"}
        }
    },
    {
        "name": "go_back",
        "description": "Navigate back to the previous page.",
        "parameters": {}
    },
    {
        "name": "get_url",
        "description": "Get the current page URL.",
        "parameters": {}
    },
    {
        "name": "get_title",
        "description": "Get the current page title.",
        "parameters": {}
    },
    {
        "name": "eval_js",
        "description": "Run JavaScript on the current page and return the result. Use this to extract structured data that isn't accessible via snapshot.",
        "parameters": {
            "code": {"type": "string", "description": "JavaScript code to evaluate"}
        }
    },
    {
        "name": "close",
        "description": "Close the browser when done. Always call this at the end of a browsing task.",
        "parameters": {}
    }
]


# ─────────────────────────────────────────────
# Tool Router
# ─────────────────────────────────────────────

TOOLS = {
    "open_url": open_url,
    "snapshot": snapshot,
    "click": click,
    "fill": fill,
    "get_text": get_text,
    "get_page_content": get_page_content,
    "scroll": scroll,
    "wait_for": wait_for,
    "wait_for_load": wait_for_load,
    "screenshot": screenshot,
    "go_back": go_back,
    "get_url": get_url,
    "get_title": get_title,
    "eval_js": eval_js,
    "close": close,
}


def run_tool(tool_name: str, arguments: dict) -> dict:
    """Call a tool by name with the given arguments."""
    if tool_name not in TOOLS:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}
    return TOOLS[tool_name](**arguments)
