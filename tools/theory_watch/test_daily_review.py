from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import curation
import daily_review
import update
from test_update import NOW, work


class DailyReviewTests(unittest.TestCase):
    def setUp(self):
        self.paper = update.normalize(work(), NOW)
        self.policy = deepcopy(curation.POLICY)
        self.policy["approvals"] = {}
        self.now = datetime(2026, 10, 20, tzinfo=timezone.utc)

    def decision(self, action="exclude"):
        return {"fingerprint": self.paper["fingerprint"], "decision": action,
                "reviewed_at": "2026-10-20T00:00:00+00:00", "reason": "Outside scope.",
                "retry_after": "2026-10-22T00:00:00+00:00"}

    def test_source_identity_matches_existing_publication_fingerprint(self):
        title, authors, abstract, fingerprint = daily_review.source_identity(work(), update.plain)
        self.assertEqual(fingerprint, self.paper["fingerprint"])
        changed = work()
        changed["author"] = [{"given": "New", "family": "Author"}]
        self.assertNotEqual(daily_review.source_identity(changed, update.plain)[3], fingerprint)

    def test_excluded_fingerprint_is_remembered_but_changed_content_returns(self):
        self.policy["decisions"] = {self.paper["doi"]: self.decision()}
        self.assertEqual(daily_review.queue_candidates([self.paper], self.policy, self.now, 60), [])
        data = {"last_successful_check": self.now.isoformat(), "papers": [self.paper]}
        self.assertEqual(curation.review_report(data, self.policy)["pending_count"], 0)
        changed = {**self.paper, "fingerprint": "1" * 64}
        self.assertEqual(len(daily_review.queue_candidates([changed], self.policy, self.now, 60)), 1)
        self.assertEqual(curation.review_report({**data, "papers": [changed]}, self.policy)["pending_count"], 1)

    def test_defer_has_cooldown_but_never_becomes_an_approval(self):
        self.policy["decisions"] = {self.paper["doi"]: self.decision("defer")}
        self.assertEqual(daily_review.queue_candidates([self.paper], self.policy, self.now, 60), [])
        later = datetime(2026, 10, 23, tzinfo=timezone.utc)
        self.assertEqual(len(daily_review.queue_candidates([self.paper], self.policy, later, 60)), 1)
        self.assertIsNone(curation.approval(self.paper, self.policy))

    def test_recent_batch_reserves_space_for_old_backlog(self):
        papers = [{**self.paper, "id": str(i), "doi": f"10.2139/ssrn.{i}"} for i in range(100)]
        queue = daily_review.queue_candidates(papers, self.policy, self.now, 60)
        self.assertEqual(len(queue), 60)
        self.assertEqual(len({p["doi"] for p in queue}), 60)
        self.assertEqual(queue[0]["id"], "99")
        self.assertEqual(queue[-1]["id"], "0")

    def test_review_timestamp_is_separate_from_latest_admission(self):
        self.policy["review_status"] = {"last_completed": self.now.isoformat(),
                                      "reviewed_count": 1, "decisions": {"exclude": 1},
                                      "remaining_candidates": 3}
        data = {"last_successful_check": self.now.isoformat(), "papers": []}
        selected = curation.select_public(data, self.policy)
        self.assertIsNone(selected["last_selection_review"])
        self.assertEqual(selected["review_status"]["last_completed"], self.now.isoformat())
        with tempfile.TemporaryDirectory() as directory, patch.object(update, "select_public", return_value=selected):
            update.render(data, Path(directory))
            html = (Path(directory) / "theory-watch/index.html").read_text()
            self.assertIn('id="last-review"', html)
            self.assertIn("20 Oct 2026", html)
            self.assertIn("1 screened, 0 approved", html)

    def test_exclusion_cannot_coexist_with_a_public_approval(self):
        self.policy["approvals"][self.paper["doi"]] = {"fingerprint": self.paper["fingerprint"]}
        self.policy["decisions"] = {self.paper["doi"]: self.decision()}
        self.assertIsNone(curation.approval(self.paper, self.policy))

    def test_missing_decisions_cannot_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            daily_review.save(root / "source/tools/theory_watch/curation.json", self.policy)
            daily_review.save(root / "queue.json", {"papers": [self.paper]})
            with self.assertRaisesRegex(ValueError, "Every queued paper"):
                daily_review.apply_decisions(root, {"decisions": []})

    def test_publish_checks_both_heads_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            daily_review.save(root / "snapshot.json", {b: {"sha": b} for b in ("main", "gh-pages")})
            with patch.object(daily_review, "api", return_value={"object": {"sha": "changed"}}) as api:
                with self.assertRaisesRegex(ValueError, "Remote changed"):
                    daily_review.publish(root)
                self.assertTrue(all(len(call.args) == 1 for call in api.call_args_list))


if __name__ == "__main__":
    unittest.main()
