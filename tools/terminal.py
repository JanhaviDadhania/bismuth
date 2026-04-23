"""
Terminal Tool
A set of file and command utilities for GTD agents.
Each function is a tool the LLM can call.
"""

import subprocess
import os


def _git_sync():
    """Auto-commit and push the memory repo. Fire-and-forget — never blocks on failure."""
    memory_dir = os.environ.get("BISMUTH_MEMORY_DIR", "")
    if not memory_dir:
        return
    try:
        subprocess.run(
            f'git -C "{memory_dir}" add . && git -C "{memory_dir}" commit -m "auto" && git -C "{memory_dir}" push',
            shell=True,
            capture_output=True,
            timeout=30,
        )
    except Exception:
        pass


# ─────────────────────────────────────────────
# Tool Functions
# ─────────────────────────────────────────────

def read_file(file_path: str) -> dict:
    """Read the contents of a file."""
    try:
        with open(file_path, "r") as f:
            content = f.read()
        return {"success": True, "content": content}
    except FileNotFoundError:
        return {"success": False, "error": f"File not found: {file_path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def write_file(file_path: str, content: str) -> dict:
    """Create or overwrite a file with the given content."""
    try:
        # create parent folders if they don't exist
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w") as f:
            f.write(content)
        _git_sync()
        return {"success": True, "message": f"Written to {file_path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def append_to_file(file_path: str, content: str) -> dict:
    """Append content to the end of a file. Creates the file if it doesn't exist."""
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "a") as f:
            f.write(content + "\n")
        _git_sync()
        return {"success": True, "message": f"Appended to {file_path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_python(file_path: str, timeout: int = 120) -> dict:
    """Run a Python file and return its output."""
    try:
        result = subprocess.run(
            ["python3", file_path],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Script timed out after {timeout} seconds"}
    except FileNotFoundError:
        return {"success": False, "error": f"File not found: {file_path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def grep(search_term: str, path: str) -> dict:
    """Search for a term in a file or recursively in a folder. Returns matching lines with file names."""
    try:
        if os.path.isfile(path):
            cmd = ["grep", "-n", search_term, path]
        elif os.path.isdir(path):
            cmd = ["grep", "-rn", search_term, path]
        else:
            return {"success": False, "error": f"Path not found: {path}"}

        result = subprocess.run(cmd, capture_output=True, text=True)
        matches = result.stdout.strip()

        if not matches:
            return {"success": True, "matches": [], "message": "No matches found"}

        return {"success": True, "matches": matches.split("\n")}
    except Exception as e:
        return {"success": False, "error": str(e)}


def create_folder(folder_path: str) -> dict:
    """Create a folder, including any parent folders if needed."""
    try:
        os.makedirs(folder_path, exist_ok=True)
        return {"success": True, "message": f"Created {folder_path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_command(command: str, timeout: int = 600) -> dict:
    """Run any shell command and return its output. Use this to spawn subagents
    via the claude CLI or run any other shell command."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Command timed out after {timeout} seconds"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────
# Tool Descriptions (pass these to your LLM)
# ─────────────────────────────────────────────

TOOL_DESCRIPTIONS = [
    {
        "name": "read_file",
        "description": "Read the contents of a file. Use this to check what's in any GTD file like capture.md, nexttodo.md, tracking.md, or any project file.",
        "parameters": {
            "file_path": {
                "type": "string",
                "description": "Absolute or relative path to the file to read"
            }
        }
    },
    {
        "name": "write_file",
        "description": "Create a new file or overwrite an existing file with content. Use this when you need to replace the entire contents of a file. Automatically creates parent folders if they don't exist.",
        "parameters": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to create or overwrite"
            },
            "content": {
                "type": "string",
                "description": "The full content to write to the file"
            }
        }
    },
    {
        "name": "append_to_file",
        "description": "Add content to the end of a file without changing existing content. Creates the file if it doesn't exist. Use this for adding new items to capture.md, nexttodo.md, tracking.md, etc.",
        "parameters": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to append to"
            },
            "content": {
                "type": "string",
                "description": "The content to add at the end of the file"
            }
        }
    },
    {
        "name": "run_python",
        "description": "Execute a Python file and return its output. Use this when a task requires running a script, such as data analysis, hypothesis testing, or generating reports.",
        "parameters": {
            "file_path": {
                "type": "string",
                "description": "Path to the Python file to run"
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum seconds to wait before killing the script. Default is 120.",
                "default": 120
            }
        }
    },
    {
        "name": "grep",
        "description": "Search for a term inside a file or recursively inside a folder. Returns matching lines with line numbers and file names. Use this to find items across GTD files, search reference material, or locate specific tasks.",
        "parameters": {
            "search_term": {
                "type": "string",
                "description": "The text to search for"
            },
            "path": {
                "type": "string",
                "description": "Path to a file or folder to search in"
            }
        }
    },
    {
        "name": "create_folder",
        "description": "Create a folder, including any parent folders. Use this when setting up a new project folder structure.",
        "parameters": {
            "folder_path": {
                "type": "string",
                "description": "Path to the folder to create"
            }
        }
    },
    {
        "name": "run_command",
        "description": "Run any shell command and return its output. Use this to spawn claude CLI subagents or run any other shell command. For spawning a subagent: run_command('claude --print \"your prompt here\"'). Default timeout is 600 seconds (10 minutes) — increase for long-running subagents.",
        "parameters": {
            "command": {
                "type": "string",
                "description": "The shell command to run"
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum seconds to wait. Default is 600.",
                "default": 600
            }
        }
    }
]


# ─────────────────────────────────────────────
# Tool Router (maps tool name to function)
# ─────────────────────────────────────────────

TOOLS = {
    "read_file": read_file,
    "write_file": write_file,
    "append_to_file": append_to_file,
    "run_python": run_python,
    "grep": grep,
    "create_folder": create_folder,
    "run_command": run_command,
}


def run_tool(tool_name: str, arguments: dict) -> dict:
    """Call a tool by name with the given arguments.
    This is what your agent loop calls when the LLM returns a tool call."""
    if tool_name not in TOOLS:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}
    return TOOLS[tool_name](**arguments)
