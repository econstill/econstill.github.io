from copy import deepcopy
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch
import xml.etree.ElementTree as ET

import curation
import semantic
import update
from test_update import NOW, work


class CurationTests(unittest.TestCase):
    def setUp(self):
        self.paper = update.normalize(work(), NOW)
        self.data = update.merge({}, [work()], NOW, {})
        self.policy = deepcopy(curation.POLICY)
        self.policy["approvals"] = {self.paper["doi"]: {
            "fingerprint": self.paper["fingerprint"], "reviewed_at": "2026-10-14",
            "review_level": "abstract_and_source", "topics": ["Game Theory & Networks"],
            "reason": "Equilibrium uniqueness in network games.",
            "sources": ["https://api.crossref.org/works/" + self.paper["doi"]],
        }}

    def selection_fixture(self):
        data, policy = deepcopy(self.data), deepcopy(self.policy)
        data["papers"], policy["approvals"] = [], {}
        for identifier, registered, selected in [
            ("2345678", "2026-10-13", "2026-10-14"),
            ("3456789", "2026-10-01", "2026-10-15"),
            ("4567890", "2026-10-02", "2026-10-15"),
        ]:
            item = work(title="Equilibrium theorem " + identifier)
            item["DOI"] = "10.2139/ssrn." + identifier
            item["created"] = {"date-time": registered + "T12:00:00Z"}
            paper = update.normalize(item, NOW)
            data["papers"].append(paper)
            policy["approvals"][paper["doi"]] = {
                **next(iter(self.policy["approvals"].values())),
                "fingerprint": paper["fingerprint"], "reviewed_at": selected,
            }
        return data, policy

    def test_latest_selections_precede_later_ssrn_registrations(self):
        data, policy = self.selection_fixture()
        before = deepcopy(data)
        selected = curation.select_public(data, policy)
        self.assertEqual([p["id"] for p in selected["papers"]], ["4567890", "3456789", "2345678"])
        self.assertEqual(data, before)
        data["last_successful_check"] = "2026-10-30T00:00:00+00:00"
        policy["review_status"] = {"last_completed": "2026-10-30T01:00:00+00:00"}
        refreshed = curation.select_public(data, policy)
        self.assertEqual(refreshed["papers"], selected["papers"])

    def test_json_static_fallback_and_rss_share_selection_order_and_dates(self):
        data, policy = self.selection_fixture()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            update, "select_public", side_effect=lambda value: curation.select_public(value, policy)
        ):
            update.render(data, Path(directory))
            output = Path(directory) / "theory-watch"
            papers = json.loads((output / "papers.json").read_text())["papers"]
            self.assertEqual([p["id"] for p in papers], ["4567890", "3456789", "2345678"])
            html = (output / "index.html").read_text()
            offsets = [html.index('data-doi="' + p["doi"] + '"') for p in papers]
            self.assertEqual(offsets, sorted(offsets))
            self.assertIn('Added <time datetime="2026-10-15">15 Oct 2026</time>', html)
            self.assertIn('DOI registered <time datetime="2026-10-02">02 Oct 2026</time>', html)
            self.assertIn("Added to this list", html)
            items = ET.parse(output / "feed.xml").findall("./channel/item")
            self.assertEqual([item.findtext("guid") for item in items], [p["doi"] for p in papers])
            for item, paper in zip(items, papers):
                self.assertEqual(parsedate_to_datetime(item.findtext("pubDate")).date().isoformat(),
                                 paper["reviewed_at"])
                self.assertIn("DOI registered " + update.display_date(paper["indexed_at"]),
                              item.findtext("description"))

    def test_unapproved_automatic_match_is_not_published(self):
        self.policy["approvals"] = {}
        self.assertEqual(curation.select_public(self.data, self.policy)["papers"], [])

    def test_exact_approval_has_contribution_and_review_extent(self):
        self.data["papers"][0]["publication_status"] = "awaiting_content_review"
        selected = curation.select_public(self.data, self.policy)
        self.assertEqual(len(selected["papers"]), 1)
        self.assertEqual(selected["papers"][0]["selection_note"], "Equilibrium uniqueness in network games.")
        self.assertEqual(selected["last_selection_review"], "2026-10-14")
        self.assertEqual(selected["selection_mode"], "curated")
        self.assertNotIn("selection_note", self.data["papers"][0])
        self.assertNotIn("publication_status", selected["papers"][0])

    def test_approval_expires_on_any_content_change(self):
        for content in [work(title="A different title"), work(abstract="We prove a new theorem on network games.")]:
            changed = update.merge(self.data, [content], NOW, {})
            self.assertEqual(curation.select_public(changed, self.policy)["papers"], [])
        content = work()
        content["author"] = [{"given": "Another", "family": "Author"}]
        changed = update.merge(self.data, [content], NOW, {})
        self.assertEqual(curation.select_public(changed, self.policy)["papers"], [])

    def test_deposit_timestamp_change_does_not_expire_approval(self):
        content = work()
        content["deposited"] = {"date-time": "2026-10-14T01:00:00Z"}
        changed = update.merge(self.data, [content], NOW, {})
        self.assertEqual(len(curation.select_public(changed, self.policy)["papers"]), 1)

    def test_discovery_override_cannot_bypass_publication(self):
        self.policy["approvals"] = {}
        with patch.dict(update.RULES, {"include_dois": [self.paper["doi"]]}):
            data = update.merge({}, [work()], NOW, {})
        self.assertTrue(data["papers"])
        self.assertEqual(curation.select_public(data, self.policy)["papers"], [])

    def test_explicit_exclusion_wins_over_approval(self):
        with patch.object(curation, "EXCLUDED", {self.paper["doi"]}):
            self.assertEqual(curation.select_public(self.data, self.policy)["papers"], [])

    def test_unselected_records_are_retained_for_review(self):
        self.policy["approvals"][self.paper["doi"]]["fingerprint"] = "0" * 64
        report = curation.review_report(self.data, self.policy)
        self.assertEqual(report["pending_count"], 1)
        self.assertEqual(report["papers"][0]["publication_status"], "content_changed_requires_review")
        self.assertEqual(report["papers"][0]["fingerprint"], self.paper["fingerprint"])
        self.assertNotIn("abstract", report["papers"][0])

    def test_invalid_approval_fails_closed(self):
        for field, value in [("fingerprint", ""), ("topics", ["Other Economic Theory"]), ("review_level", "peer_reviewed"), ("sources", [])]:
            bad = deepcopy(self.policy)
            bad["approvals"][self.paper["doi"]][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                curation.select_public(self.data, bad)

    def test_missing_or_obsolete_candidate_cache_requires_complete_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "candidates.json"
            previous, reusable = update.load_candidate_state(cache, self.data)
            self.assertFalse(reusable)
            self.assertEqual(previous, self.data)
            cache.write_text(json.dumps(self.data))
            self.assertFalse(update.load_candidate_state(cache, self.data)[1])

    def test_current_candidate_cache_is_reused_but_stale_one_is_not(self):
        state = {**self.data, "rule_version": semantic.CONFIG["version"], "archive_kind": "discovery_candidates"}
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "candidates.json"
            cache.write_text(json.dumps(state))
            self.assertTrue(update.load_candidate_state(cache, self.data)[1])
            cache.write_text(json.dumps(curation.select_public(state, self.policy)))
            self.assertFalse(update.load_candidate_state(cache, self.data)[1])
            state["last_successful_check"] = "2026-10-01T00:00:00+00:00"
            cache.write_text(json.dumps(state))
            self.assertFalse(update.load_candidate_state(cache, self.data)[1])
            cache.write_text("{bad json")
            self.assertFalse(update.load_candidate_state(cache, self.data)[1])
            cache.write_text("[]")
            self.assertFalse(update.load_candidate_state(cache, self.data)[1])

    def test_borderline_candidate_retained_without_automatic_publication(self):
        class Selector:
            decisions = {"10.2139/ssrn.1234567": {"decision": "review", "topics": ["Game Theory & Networks"]}}
            stats = {}
            def classify(self, *args):
                return []
        candidate = update.merge({}, [work()], NOW, {}, Selector(), rescreen=True, candidates=True)
        self.assertEqual(len(candidate["papers"]), 1)
        self.policy["approvals"] = {}
        self.assertEqual(curation.select_public(candidate, self.policy)["papers"], [])

    def test_all_public_outputs_share_the_gate_and_empty_days_are_valid(self):
        self.policy["approvals"] = {}
        with tempfile.TemporaryDirectory() as directory, patch.object(update, "select_public", side_effect=lambda data: curation.select_public(data, self.policy)):
            update.render(self.data, Path(directory))
            output = Path(directory) / "theory-watch"
            self.assertEqual(json.loads((output / "papers.json").read_text())["papers"], [])
            self.assertEqual(ET.parse(output / "feed.xml").findall("./channel/item"), [])
            self.assertNotIn(self.paper["title"], (output / "index.html").read_text())

    def test_scope_removes_generic_macro_but_retains_micro_foundations(self):
        self.assertNotIn("Other Economic Theory", semantic.CONFIG["topics"])
        self.assertIn("Equilibrium & Mathematical Economics", semantic.CONFIG["topics"])
        self.assertIn("Decision & Social Choice", semantic.CONFIG["topics"])

    def test_render_only_cannot_overwrite_candidate_state_with_selected_subset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site, cache = root / "site", root / "state.json"
            update.write_text(site / "theory-watch/papers.json", json.dumps(curation.select_public(self.data, self.policy)))
            update.write_text(cache, json.dumps(self.data))
            before = cache.read_bytes()
            args = ["update.py", "--site-dir", str(site), "--candidate-cache", str(cache), "--render-only"]
            with patch.object(sys, "argv", args):
                update.main()
            self.assertEqual(cache.read_bytes(), before)

    def test_daily_pipeline_persists_candidates_without_publishing_them(self):
        class Selector:
            decisions = {"10.2139/ssrn.1234567": {"decision": "include", "topics": ["Game Theory & Networks"]}}
            stats = {}
            def prepare(self, works):
                pass
            def classify(self, *args):
                return ["Game Theory & Networks"]
            def save(self):
                pass
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site, cache, report = root / "site", root / "state.json", root / "review.json"
            args = ["update.py", "--site-dir", str(site), "--candidate-cache", str(cache), "--review-output", str(report)]
            window = {"from": "2026-09-30", "through": "2026-10-15", "date_field": "created"}
            with patch.object(sys, "argv", args), patch.object(semantic, "SemanticSelector", return_value=Selector()), patch.object(update, "collect", return_value=([work()], window)) as collect:
                update.main()
                self.assertEqual(collect.call_args.args[0], {})
            self.assertEqual(len(json.loads(cache.read_text())["papers"]), 1)
            self.assertEqual(json.loads((site / "theory-watch/papers.json").read_text())["papers"], [])
            self.assertEqual(json.loads(report.read_text())["pending_count"], 1)
            with patch.object(sys, "argv", args), patch.object(semantic, "SemanticSelector", return_value=Selector()), patch.object(update, "collect", return_value=([], {})) as collect:
                update.main()
                self.assertEqual(len(collect.call_args.args[0]["papers"]), 1)
            self.assertEqual(len(json.loads(cache.read_text())["papers"]), 1)
            before = (site / "theory-watch/papers.json").read_bytes()
            cache_before = cache.read_bytes()
            with patch.object(sys, "argv", args), patch.object(update, "collect", side_effect=RuntimeError("Incomplete window")):
                with self.assertRaises(RuntimeError):
                    update.main()
            self.assertEqual((site / "theory-watch/papers.json").read_bytes(), before)
            self.assertEqual(cache.read_bytes(), cache_before)


if __name__ == "__main__":
    unittest.main()
