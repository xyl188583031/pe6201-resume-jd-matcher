"""The vector index is a shared mutable resource, so it needs its own guard.

Why this file exists: a repeat evaluation lost all 20 of its condition-C cases to
`NotFoundError` because a *second* process rebuilt `artifacts/chroma_db` while the
first was querying it. The per-out-dir run lock could not see this, since the two
processes had different out-dirs and therefore different lock files. These tests
pin the rule that replaced it.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.retrieval import store as S  # noqa: E402


class TestIndexLock(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.persist = Path(self._tmp.name) / "chroma_db"
        self.lock = self.persist.with_name(self.persist.name + ".lock")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_acquire_creates_a_lock_carrying_our_pid(self) -> None:
        path = S.acquire_index_lock(self.persist)
        self.assertIsNotNone(path)
        assert path is not None
        self.assertEqual(path, self.lock)
        info = json.loads(self.lock.read_text(encoding="utf-8"))
        self.assertEqual(info["pid"], os.getpid())
        self.assertIn("started_at", info)

    def test_second_acquire_in_the_same_process_is_allowed(self) -> None:
        """Re-entrancy matters: the pipeline may build a KB more than once."""
        S.acquire_index_lock(self.persist)
        S.acquire_index_lock(self.persist)  # must not raise
        self.assertTrue(self.lock.exists())

    def test_a_live_holder_is_refused_on_both_backends(self) -> None:
        """A live foreign PID must abort, not race."""
        self.persist.mkdir(parents=True, exist_ok=True)
        self.lock.write_text(json.dumps({"pid": 4242, "started_at": "whenever"}), encoding="utf-8")
        with mock.patch.object(S, "_pid_alive", return_value=True):
            with self.assertRaises(RuntimeError) as ctx:
                S.acquire_index_lock(self.persist)
        message = str(ctx.exception)
        self.assertIn("4242", message)
        self.assertIn(".lock", message)

    def test_a_dead_holder_is_cleared(self) -> None:
        """Otherwise a crashed run would wedge every later run."""
        self.persist.mkdir(parents=True, exist_ok=True)
        self.lock.write_text(json.dumps({"pid": 999999, "started_at": "whenever"}), encoding="utf-8")
        with mock.patch.object(S, "_pid_alive", return_value=False):
            path = S.acquire_index_lock(self.persist)
        self.assertIsNotNone(path)
        self.assertEqual(json.loads(self.lock.read_text(encoding="utf-8"))["pid"], os.getpid())

    def test_an_unreadable_lock_is_treated_as_stale(self) -> None:
        self.persist.mkdir(parents=True, exist_ok=True)
        self.lock.write_text("not json", encoding="utf-8")
        path = S.acquire_index_lock(self.persist)
        self.assertIsNotNone(path)
        self.assertEqual(json.loads(self.lock.read_text(encoding="utf-8"))["pid"], os.getpid())

    def test_knowledge_base_close_releases_the_lock(self) -> None:
        path = S.acquire_index_lock(self.persist)
        kb = S.KnowledgeBase(
            store=object(),
            embedder_info={},
            store_info={},
            chunk_count=0,
            lock_path=path,
        )
        self.assertTrue(self.lock.exists())
        kb.close()
        self.assertFalse(self.lock.exists())
        kb.close()  # second close must not raise

    def test_pid_liveness_never_raises_on_garbage(self) -> None:
        for pid in (0, -1, 2_000_000_000):
            self.assertFalse(S._pid_alive(pid))


if __name__ == "__main__":
    unittest.main()
