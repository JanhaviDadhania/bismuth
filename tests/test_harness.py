"""
Unit tests for the trickiest harness logic — the pieces that broke (or
nearly broke) in the 2026-06 review: token tail-parsing, HALT/PENDING
interaction, session TTL/migration, executor question relay re-arming,
project resolution for SWITCH, and the locked tracking append.

Run:  python3 -m unittest discover -s tests
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import harness
from tools.track_append import insert_entry

# Keep test log lines out of the real runtime log.
_log_tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
harness.LOG_FILE = Path(_log_tmp.name)


class TestParseTokens(unittest.TestCase):
    def test_token_at_end_detected(self):
        out = "I routed everything.\n\nSWITCH:coffeechat:seldon"
        self.assertEqual(parse(out).get("SWITCH"), "coffeechat:seldon")

    def test_quoted_token_mid_reply_ignored(self):
        # An agent explaining its own protocol must not trigger it.
        body = "If you ever want me to stop everything, I would emit:\nHALT\n"
        padding = "\n".join(f"line {i} of a long explanation" for i in range(15))
        out = body + padding
        self.assertNotIn("HALT", parse(out))

    def test_multiple_tokens_in_tail(self):
        out = ("replied on telegram.\n"
               'PENDING:["the idea I want to discuss"]\n'
               "SWITCH:coffeechat:seldon")
        tokens = parse(out)
        self.assertEqual(tokens.get("PENDING"), '["the idea I want to discuss"]')
        self.assertEqual(tokens.get("SWITCH"), "coffeechat:seldon")

    def test_reset_session_bare_token(self):
        self.assertIn("RESET_SESSION", parse("flushed mood.md\nRESET_SESSION"))


def parse(stdout):
    return harness.parse_tokens(stdout)


class TestHandleTokens(unittest.TestCase):
    def setUp(self):
        self.state = harness.default_state()

    @patch.object(harness, "telegram_send")
    def test_halt_suppresses_pending(self, _send):
        tokens = {"HALT": True, "PENDING": '["sneaky message"]'}
        harness.handle_tokens(tokens, self.state)
        self.assertEqual(self.state["pending_buffer"], [])
        self.assertEqual(self.state["active_agent"], "assistant")

    @patch.object(harness, "telegram_send")
    def test_pending_alone_fills_buffer(self, _send):
        harness.handle_tokens({"PENDING": '["a", "b"]'}, self.state)
        self.assertEqual(self.state["pending_buffer"], ["a", "b"])

    @patch.object(harness, "telegram_send")
    def test_switch_to_unknown_project_bounces_to_assistant(self, _send):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "projects").mkdir()
            with patch.object(harness, "MEMORY_DIR", Path(tmp)):
                harness.handle_tokens({"SWITCH": "coffeechat:ghost_project"}, self.state)
        self.assertEqual(self.state["active_agent"], "assistant")
        self.assertTrue(any("switch failed" in m for m in self.state["pending_buffer"]))

    @patch.object(harness, "telegram_send")
    def test_switch_typo_resolves_to_closest_project(self, _send):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "projects" / "seldon").mkdir(parents=True)
            with patch.object(harness, "MEMORY_DIR", Path(tmp)):
                harness.handle_tokens({"SWITCH": "coffeechat:sledon"}, self.state)
        self.assertEqual(self.state["active_agent"], "coffeechat:seldon")


class TestSessions(unittest.TestCase):
    def setUp(self):
        self.state = harness.default_state()

    def test_new_session_created_as_dict(self):
        sid, is_new = harness.get_or_create_session("assistant", self.state)
        self.assertTrue(is_new)
        entry = self.state["sessions"]["assistant"]
        self.assertEqual(entry["id"], sid)
        self.assertIn("last_used", entry)

    def test_legacy_string_session_migrates_and_resumes(self):
        self.state["sessions"]["assistant"] = "legacy-uuid"
        sid, is_new = harness.get_or_create_session("assistant", self.state)
        self.assertFalse(is_new)
        self.assertEqual(sid, "legacy-uuid")
        self.assertIsInstance(self.state["sessions"]["assistant"], dict)

    def test_idle_session_expires(self):
        self.state["sessions"]["assistant"] = {
            "id": "old-uuid",
            "created": time.time() - 100_000,
            "last_used": time.time() - harness.SESSION_MAX_IDLE - 60,
        }
        sid, is_new = harness.get_or_create_session("assistant", self.state)
        self.assertTrue(is_new)
        self.assertNotEqual(sid, "old-uuid")

    def test_fresh_session_not_expired(self):
        self.state["sessions"]["assistant"] = {
            "id": "live-uuid", "created": time.time(), "last_used": time.time(),
        }
        sid, is_new = harness.get_or_create_session("assistant", self.state)
        self.assertFalse(is_new)
        self.assertEqual(sid, "live-uuid")


class TestMailboxQuestionRelay(unittest.TestCase):
    def _exec_dir(self, root, uid):
        d = root / f"executor_{uid}"
        d.mkdir()
        return d

    def test_second_question_is_relayed_after_cycle_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            uid = "a" * 32
            d = self._exec_dir(root, uid)
            state = harness.default_state()
            state["executors"][uid] = {"pid": 99999, "project": "seldon",
                                       "status": "running"}
            with patch.object(harness, "HARNESS_DIR", root):
                # question 1
                (d / "status").write_text("asking")
                (d / "question.txt").write_text("which dataset?")
                msgs = harness.read_mailbox(state)
                self.assertEqual(len(msgs), 1)
                self.assertIn("which dataset?", msgs[0])
                # relayed once, not twice
                self.assertEqual(harness.read_mailbox(state), [])
                # executor consumes answer and cleans up per protocol
                (d / "question.txt").unlink()
                (d / "status").write_text("running")
                self.assertEqual(harness.read_mailbox(state), [])
                # question 2 — the regression: this used to be silently dropped
                (d / "status").write_text("asking")
                (d / "question.txt").write_text("and which metric?")
                msgs = harness.read_mailbox(state)
                self.assertEqual(len(msgs), 1)
                self.assertIn("which metric?", msgs[0])

    def test_late_answer_noticed_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            uid = "b" * 32
            d = self._exec_dir(root, uid)
            state = harness.default_state()
            state["executors"][uid] = {"pid": 99999, "project": "seldon",
                                       "status": "done", "result_relayed": True}
            with patch.object(harness, "HARNESS_DIR", root):
                (d / "status").write_text("done")
                (d / "answer.txt").write_text("too late")
                msgs = harness.read_mailbox(state)
                self.assertEqual(len(msgs), 1)
                self.assertIn("after it had already finished", msgs[0])
                self.assertEqual(harness.read_mailbox(state), [])


class TestRunningCount(unittest.TestCase):
    def test_asking_holds_a_slot(self):
        state = harness.default_state()
        state["executors"] = {
            "a": {"status": "running"},
            "b": {"status": "asking"},
            "c": {"status": "done"},
            "d": {"status": "failed"},
        }
        self.assertEqual(harness.running_count(state), 2)


class TestTrackAppend(unittest.TestCase):
    def test_plain_append(self):
        out = insert_entry("existing line\n", "- [2026-06-12] did a thing")
        self.assertEqual(out, "existing line\n- [2026-06-12] did a thing\n")

    def test_creates_project_block(self):
        out = insert_entry("", "- [2026-06-12] built it", project="seldon")
        self.assertIn("<project:seldon>\n- [2026-06-12] built it\n</project:seldon>", out)

    def test_inserts_into_existing_block(self):
        content = ("<project:seldon>\n"
                   "- [2026-06-10] older entry\n"
                   "</project:seldon>\n")
        out = insert_entry(content, "- [2026-06-12] newer entry", project="seldon")
        self.assertLess(out.index("older entry"), out.index("newer entry"))
        self.assertLess(out.index("newer entry"), out.index("</project:seldon>"))
        self.assertEqual(out.count("<project:seldon>"), 1)


if __name__ == "__main__":
    unittest.main()
