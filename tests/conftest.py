"""Shared fixture: a whole v2 pointed at a throwaway tree.

Lifted out of `test_v2.py` when `test_v2_schedules.py` needed the same thing.
Nothing here touches her real memory, and no test spends money on `claude -p`.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Reload order matters: `tools_catalog` imports `schedules`, `intents` imports
# both `schedules` and `destinations`, and `mainagent` imports `tools_catalog`.
# A module reloaded before its dependency keeps the stale path constants.
RELOAD_ORDER = ("trace", "state", "tasks", "destinations", "schedules",
                "tools_catalog", "intents", "subagent", "mainagent", "ingest",
                "board_sections")


@pytest.fixture()
def v2(tmp_path, monkeypatch):
    monkeypatch.setenv("BISMUTH2_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setenv("BISMUTH2_MEMORY_DIR", str(tmp_path / "mem"))
    (tmp_path / "mem" / "projects" / "the_mirror").mkdir(parents=True)
    (tmp_path / "mem" / "projects" / "the_mirror" / "nexttodo.md").write_text("# next\n")
    (tmp_path / "mem" / "reminders.md").write_text("# reminders\n")

    import v2.config as config
    importlib.reload(config)
    mods = {}
    for name in RELOAD_ORDER:
        mods[name] = importlib.reload(importlib.import_module(f"v2.{name}"))
    mods["config"] = config
    config.ensure_dirs()
    return type("V2", (), mods)
