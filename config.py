"""
Config loader — single source of truth for bismuth settings.
Import MEMORY_DIR and BASE_DIR from here instead of computing paths in each agent.
"""

import os
import yaml
from pathlib import Path

BASE_DIR = Path(__file__).parent


def load_config() -> dict:
    with open(BASE_DIR / "config.yaml") as f:
        return yaml.safe_load(f)


_config = load_config()

# Memory directory — read from config.yaml. The fallback is anchored to the
# repo, never the caller's cwd, so launching from elsewhere can't silently
# grow a memory tree in the wrong place.
_raw = _config.get("memory_path") or (BASE_DIR / "memory")
MEMORY_DIR = Path(os.path.expanduser(str(_raw))).resolve()
