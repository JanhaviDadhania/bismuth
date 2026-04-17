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

# Memory directory — read from config.yaml, defaults to memory/ inside project
_raw = _config.get("memory_path", "memory")
MEMORY_DIR = Path(os.path.expanduser(str(_raw))).resolve()
