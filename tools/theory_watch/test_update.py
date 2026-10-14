from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

import update


NOW = datetime(2026, 10, 14, 3, 0, tzinfo=timezone.utc)


def work(title="Uniqueness in Network Games", abstract="We prove a theorem on equilibrium uniqueness in network games with strategic complementarities."):
    return {
        "DOI": "10.2139/ssrn.1234567", "title": [title], "abstract": abstract,
        "author": [{"given": "A", "family": "Researcher"}],
        "created": {"date-time": "2026-10-13T12:00:00Z"},
        "deposited": {"date-time": "2026-10-13T12:00:00Z"},
        "posted": {"date-parts": [[2026]]},
    }


class UpdateTests(unittest.TestCase):
    def test_theory_topics(self):
        examples = [
            ("Network Games", "We prove equilibrium existence in network games.", "Game Theory & Networks"),
            ("Optimal Auctions", "We characterize incentive compatible auctions and prove revenue bounds.", "Mechanism & Market Design"),
            ("Bayesian Persuasion", "We show how information design changes equilibrium incentives.", "Information & Contracts"),
            ("Social Welfare Functions", "We prove an impossibility theorem for social choice with voter preferences.", "Decision & Social Choice"),
            ("Competitive Equilibrium", "We establish existence in exchange economies and derive general equilibrium conditions.", "Equilibrium & Mathematical Economics"),
        ]
        for title, abstract, topic in examples:
            with self.subTest(topic=topic):
                self.assertIn(topic, update.classify(title, abstract, "10.2139/ssrn.1"))

    def test_empirical_and_video_games_are_excluded(self):
        self.assertFalse(update.classify("Auctions: Evidence from Schools", "We estimate auction effects on market prices.", "10.2139/ssrn.1"))
        self.assertFalse(update.classify("Game Theory Applied to Pokemon Video Games", "We prove equilibrium properties in a game theoretic market model.", "10.2139/ssrn.1"))

    def test_html_and_double_encoded_metadata(self):
        self.assertEqual(update.plain("<jats:p>&lt;p&gt;A &amp;amp; B&lt;/p&gt;</jats:p>"), "A & B")
        self.assertEqual(update.plain("<script>alert(1)</script>Safe"), "Safe")

    def test_generic_risk_words_and_quantitative_ge_do_not_suffice(self):
        self.assertFalse(update.classify("A Trading Strategy", "We show portfolio returns depend on risk aversion and risk preferences in markets.", "10.2139/ssrn.1"))
        self.assertFalse(update.classify("Trade in General Equilibrium", "I estimate a general equilibrium model of markets using bilateral data.", "10.2139/ssrn.1"))
        self.assertFalse(update.classify("Microarchitecturally-Constrained Game Theory", "We prove a theorem on Nash equilibrium in economic games.", "10.2139/ssrn.1"))

    def test_singular_author_and_implicit_existence_result(self):
        self.assertTrue(update.classify("General Equilibrium", "Competitive equilibrium exists without convexity in markets.", "10.2139/ssrn.1"))
        self.assertTrue(update.classify("Non-Nashian Game Theory", "I discuss concepts for game theorists.", "10.2139/ssrn.1"))
        self.assertTrue(update.classify("A New Contract", "I prove a theorem in information design and contract theory for markets.", "10.2139/ssrn.1"))

    def test_non_ssrn_and_incomplete_date(self):
        item = work()
        item["DOI"] = "10.9999/fake"
        self.assertIsNone(update.normalize(item, NOW))
        self.assertIsNone(update.normalize(work(), NOW)["posted_date"])

    def test_deduplication_and_stable_first_seen(self):
        first = update.merge({}, [work(), work()], NOW, {})
        second = update.merge(first, [work()], NOW + timedelta(days=1), {})
        self.assertEqual(len(second["papers"]), 1)
        self.assertEqual(second["papers"][0]["first_seen"], NOW.isoformat())
        self.assertIsNone(second["papers"][0]["record_updated_at"])

    def test_metadata_change_does_not_create_another_paper(self):
        first = update.merge({}, [work()], NOW, {})
        changed = work(abstract="We prove a new theorem on uniqueness of equilibrium in network games.")
        second = update.merge(first, [changed], NOW + timedelta(days=1), {})
        self.assertEqual(len(second["papers"]), 1)
        self.assertEqual(second["last_collection"]["changed_matches"], 1)
        self.assertEqual(second["papers"][0]["first_seen"], NOW.isoformat())

    def test_old_registration_is_not_added_by_a_recent_metadata_deposit(self):
        old = work()
        old["created"]["date-time"] = "2024-08-12T12:00:00Z"
        old["deposited"]["date-time"] = "2026-10-14T01:00:00Z"
        result = update.merge({}, [old], NOW, {"date_field": "deposit"})
        self.assertEqual(result["papers"], [])

    def test_identical_work_under_two_ssrn_ids_is_merged(self):
        duplicate = work()
        duplicate["DOI"] = "10.2139/ssrn.2345678"
        result = update.merge({}, [work(), duplicate], NOW, {})
        self.assertEqual(len(result["papers"]), 1)
        self.assertEqual(result["papers"][0]["ssrn_ids"], ["1234567", "2345678"])
        following = update.merge(result, [duplicate], NOW + timedelta(days=1), {})
        self.assertEqual(len(following["papers"]), 1)
        self.assertEqual(following["papers"][0]["doi"], "10.2139/ssrn.1234567")

    def test_incomplete_collection_fails(self):
        with patch.object(update, "request_json", return_value={"message": {"total-results": 2, "items": [work()]}}):
            with self.assertRaises(RuntimeError):
                update.collect({}, NOW, 14)

    def test_render_escapes_paper_content(self):
        paper = update.normalize(work(), NOW)
        paper["title"] = "<img src=x onerror=alert(1)>"
        rendered = update.paper_html(paper)
        self.assertNotIn("<img", rendered)
        self.assertIn("&lt;img", rendered)


if __name__ == "__main__":
    unittest.main()
