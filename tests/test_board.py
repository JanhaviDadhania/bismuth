"""
Unit tests for the board generator — the pieces that would quietly produce a
wrong board rather than an error: the vendored-tree ignore rules, nested-repo
and big-folder collapsing, reminder state parsing, determinism, and the
guarantee that every href on the canvas resolves to a real file.

Run:  python3 -m unittest discover -s tests
"""

import datetime
import re
import shutil
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import board


def write(path: Path, text: str = "x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


class BoardTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.mem = self.root / "mem"
        (self.mem / "projects").mkdir(parents=True)
        (self.mem / "miniprojects").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def build(self, **kw):
        return board.build_board(self.mem, **kw)


class TestIgnoreRules(BoardTestCase):
    def test_vendored_trees_are_not_pinned(self):
        p = self.mem / "projects" / "alpha"
        write(p / "summary.md", "real note")
        for junk in ["node_modules/react/index.js", ".venv/lib/thing.py",
                     "__pycache__/x.pyc", "site-packages/dep/mod.py"]:
            write(p / junk)
        r = self.build()
        self.assertTrue(r["success"])
        # Only the real note survives.
        self.assertEqual(r["cards"], 1)

    def test_noise_files_are_dropped(self):
        p = self.mem / "projects" / "alpha"
        write(p / "summary.md", "real")
        for junk in [".DS_Store", "package-lock.json", "build.log", "lib.so"]:
            write(p / junk)
        self.assertEqual(self.build()["cards"], 1)


class TestCollapsing(BoardTestCase):
    def test_nested_git_repo_becomes_one_card(self):
        p = self.mem / "projects" / "alpha"
        write(p / "summary.md", "real")
        clone = p / "vendor" / "someclone"
        write(clone / ".git" / "HEAD", "ref: refs/heads/main")
        for i in range(30):
            write(clone / f"file_{i}.py", "code")
        r = self.build()
        self.assertEqual(r["cards"], 2)          # note + one repo card
        self.assertEqual([c["why"] for c in r["collapsed"]], ["git repo"])

    def test_oversized_folder_collapses_and_is_reported(self):
        p = self.mem / "projects" / "alpha"
        for i in range(12):
            write(p / "dump" / f"n_{i}.md", "note")
        r = self.build(max_dir_files=5)
        self.assertEqual(r["cards"], 1)
        self.assertEqual(r["collapsed"][0]["files"], 12)
        # A cap that is not reported reads as "everything is on the board".
        self.assertEqual(r["collapsed"][0]["why"], "large folder")

    def test_collapsed_folder_lists_its_file_names_as_links(self):
        p = self.mem / "projects" / "alpha"
        for i in range(8):
            write(p / "shots" / f"shot_{i}.png", "img")
        r = self.build(max_dir_files=5)
        self.assertEqual(r["cards"], 1)
        html = (self.mem / "board.html").read_text()
        # every trimmed file is still named on the board, and clickable
        for i in range(8):
            self.assertIn(f'>shot_{i}.png</a>', html)
            self.assertIn(f'href="projects/alpha/shots/shot_{i}.png"', html)
        # and findable by the filter box
        self.assertIn("shot_3.png", re.search(r'data-s="([^"]*)"', html).group(1))

    def test_listing_overflow_is_stated_on_the_card(self):
        p = self.mem / "projects" / "alpha"
        for i in range(board.FOLDER_LIST_MAX + 7):
            write(p / "dump" / f"f_{i:03}.md", "x")
        self.build(max_dir_files=5)
        html = (self.mem / "board.html").read_text()
        self.assertIn("+7 more", html)

    def test_default_cap_is_forty(self):
        self.assertEqual(board.DEFAULT_MAX_DIR_FILES, 40)

    def test_folder_at_the_limit_is_not_collapsed(self):
        p = self.mem / "projects" / "alpha"
        for i in range(5):
            write(p / "dump" / f"n_{i}.md", "note")
        r = self.build(max_dir_files=5)
        self.assertEqual(r["cards"], 5)
        self.assertEqual(r["collapsed"], [])


class TestCards(BoardTestCase):
    def test_big_video_is_a_link_not_an_embed(self):
        p = self.mem / "projects" / "alpha"
        small = write(p / "clip.mp4", "")
        big = write(p / "feature.mp4", "")
        small.write_bytes(b"0" * 1024)
        big.write_bytes(b"0" * (board.INLINE_VIDEO_MAX_BYTES + 1))
        self.build()
        html = (self.mem / "board.html").read_text()
        self.assertIn('<video src="projects/alpha/clip.mp4"', html)
        self.assertNotIn('<video src="projects/alpha/feature.mp4"', html)
        self.assertIn('class="card file"', html)
        self.assertIn('data-href="projects/alpha/feature.mp4"', html)

    def test_project_spine_files_are_marked(self):
        p = self.mem / "projects" / "alpha"
        write(p / "summary.md", "s")
        write(p / "reference" / "notes.md", "n")
        html_out = self.mem / "board.html"
        self.build()
        html = html_out.read_text()
        self.assertIn('class="card spine"', html)
        self.assertIn('class="card note"', html)

    def test_empty_project_still_gets_a_group(self):
        (self.mem / "projects" / "ghost").mkdir()
        write(self.mem / "projects" / "alpha" / "summary.md", "s")
        r = self.build()
        self.assertEqual(r["projects"], 2)
        self.assertIn("nothing pinned yet", (self.mem / "board.html").read_text())

    def test_underscores_survive_the_markdown_stripper(self):
        # ai_neuroscience must not render as aineuroscience.
        write(self.mem / "projects" / "alpha" / "summary.md",
              "*tracking ai_neuroscience progress*")
        self.build()
        self.assertIn("ai_neuroscience", (self.mem / "board.html").read_text())


class TestReminders(BoardTestCase):
    def test_states_are_classified_against_today(self):
        write(self.mem / "reminders.md",
              "# Reminders\n"
              "- ~~2026-01-01 — done thing~~ (fired)\n"
              "- 2026-08-01 — missed thing\n"
              "- 2026-08-28 — today thing\n"
              "- 2026-09-30 — later thing\n")
        g = board._reminder_group(self.mem, datetime.date(2026, 8, 28))
        states = {i["text"]: i["state"] for c in g.cards for i in c.items}
        self.assertEqual(states["done thing"], "fired")
        self.assertEqual(states["missed thing"], "overdue")
        self.assertEqual(states["today thing"], "today")
        self.assertEqual(states["later thing"], "future")
        self.assertEqual(g.subtitle.split()[0], "3")   # 3 pending of 4

    def test_unparseable_lines_are_skipped_not_crashed(self):
        write(self.mem / "reminders.md",
              "# Reminders\nOne reminder per line, sorted by date:\n"
              "- not-a-date — nope\n- 2026-13-45 — bad date\n"
              "- 2026-08-28 — good one\n")
        g = board._reminder_group(self.mem, datetime.date(2026, 8, 28))
        self.assertEqual(sum(len(c.items) for c in g.cards), 1)

    def test_missing_reminders_file_is_not_fatal(self):
        write(self.mem / "projects" / "alpha" / "summary.md", "s")
        r = self.build()
        self.assertTrue(r["success"])
        self.assertEqual(r["reminders"], 0)


class TestNextTodo(BoardTestCase):
    FILE = ("# General Next Actions\n"
            "- @janhavi refactor the assistant prompt\n"
            "- @agent add an executor watchdog to harness.py\n"
            "- flag for the evaluation cycle: untagged note\n"
            "\n## Punch list [2026-07-27]\n"
            "- ~~@janhavi file ITR~~ done [2026-07-28]\n"
            "- @janhavi then do visa\n")

    def test_owner_and_done_state_are_parsed(self):
        write(self.mem / "nexttodo.md", self.FILE)
        cards, open_count = board._todo_cards(self.mem)
        rows = [i for c in cards for i in c.items]
        self.assertEqual(len(rows), 5)
        self.assertEqual(open_count, 4)                      # one is struck through
        by_text = {i["text"]: i for i in rows}
        self.assertEqual(by_text["refactor the assistant prompt"]["who"], "janhavi")
        self.assertEqual(by_text["add an executor watchdog to harness.py"]["who"], "agent")
        self.assertEqual(by_text["flag for the evaluation cycle: untagged note"]["who"], "")
        self.assertTrue(by_text["file ITR"]["done"])
        # the "done [date]" trailer is not part of the item text
        self.assertNotIn("done", by_text["file ITR"]["text"])

    def test_one_card_per_heading(self):
        write(self.mem / "nexttodo.md", self.FILE)
        cards, _ = board._todo_cards(self.mem)
        self.assertEqual([c.title for c in cards],
                         ["General Next Actions", "Punch list [2026-07-27]"])

    def test_home_todos_and_reminders_share_one_panel(self):
        write(self.mem / "nexttodo.md", self.FILE)
        write(self.mem / "reminders.md", "- 2026-08-28 — a thing\n")
        write(self.mem / "projects" / "alpha" / "summary.md", "s")
        r = self.build()
        self.assertEqual(r["todos"], 4)
        html = (self.mem / "board.html").read_text()
        self.assertIn("NEXT TODO &amp; REMINDERS", html)
        # both card kinds live in the same group box
        panel = html.split('class="group now"')[1].split("</div><div class=\"group")[0]
        self.assertIn('class="card todo"', panel)
        self.assertIn('class="card month"', panel)

    def test_project_nexttodo_stays_with_its_project(self):
        write(self.mem / "nexttodo.md", self.FILE)
        write(self.mem / "projects" / "alpha" / "nexttodo.md", "- @janhavi ship it")
        self.build()
        html = (self.mem / "board.html").read_text()
        alpha = html.split('class="group project"')[1].split('class="group')[0]
        self.assertIn("nexttodo", alpha)          # rendered as the project's spine card
        self.assertNotIn("card todo", alpha)      # not pulled into the merged panel

    def test_missing_nexttodo_is_not_fatal(self):
        write(self.mem / "projects" / "alpha" / "summary.md", "s")
        r = self.build()
        self.assertTrue(r["success"])
        self.assertEqual(r["todos"], 0)


class TestOutput(BoardTestCase):
    def _seed(self):
        p = self.mem / "projects" / "alpha"
        write(p / "summary.md", "# Title\nbody text here")
        write(p / "reference" / "deep.md", "more")
        write(self.mem / "miniprojects" / "tiny" / "notes.md", "m")
        write(self.mem / "reminders.md", "- 2026-08-28 — a thing\n")

    def test_same_tree_gives_byte_identical_board(self):
        self._seed()
        self.build()
        first = (self.mem / "board.html").read_bytes()
        self.build()
        self.assertEqual(first, (self.mem / "board.html").read_bytes())

    def test_every_href_resolves_to_a_real_path(self):
        self._seed()
        self.build()
        html = (self.mem / "board.html").read_text()
        hrefs = re.findall(r'data-href="([^"]+)"', html)
        hrefs += re.findall(r'src="([^"]+)"', html)
        self.assertTrue(hrefs)
        for h in hrefs:
            self.assertTrue((self.mem / urllib.parse.unquote(h)).exists(), h)

    def test_every_note_card_resolves_to_embedded_text(self):
        self._seed()
        self.build()
        html = (self.mem / "board.html").read_text()
        notes = re.search(r"const NOTES = (\{.*?\});</script>", html, re.S).group(1)
        ids = re.findall(r'id="(c[0-9a-f]+)"[^>]*data-full="1"', html)
        self.assertTrue(ids)
        for i in ids:
            # The JS looks the note up as el.id.slice(1).
            self.assertIn(f'"{i[1:]}":', notes)

    def test_out_must_stay_beside_the_memory_root(self):
        self._seed()
        r = self.build(out=self.root / "elsewhere.html")
        self.assertFalse(r["success"])
        self.assertIn("relative hrefs", r["error"])

    def test_board_is_landscape(self):
        self._seed()
        for n in range(40):
            write(self.mem / "projects" / f"p{n}" / "summary.md", "x" * 400)
        self.build()
        html = (self.mem / "board.html").read_text()
        m = re.search(r'id="canvas" style="width:(\d+)px;height:(\d+)px"', html)
        w, h = int(m.group(1)), int(m.group(2))
        self.assertGreater(w / h, 1.2, "a portrait board wastes the screen at fit-zoom")


if __name__ == "__main__":
    unittest.main()
