import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from datetime import timedelta

import semantic
import update
from test_update import NOW, work


class SemanticTests(unittest.TestCase):
    def test_explicit_jel_not_bare_code(self):
        self.assertEqual(semantic.explicit_jel({}, "JEL Codes: C72, D85. Keywords: networks"), ["C72", "D85"])
        self.assertEqual(semantic.explicit_jel({}, "Cell D85 contains the outcome."), [])
        self.assertTrue(semantic.supported_jel(["C72"]))
        self.assertFalse(semantic.supported_jel(["G12"]))

    def test_every_abstract_word_is_covered(self):
        words = [f"word{i}" for i in range(1300)]
        selector = object.__new__(semantic.SemanticSelector)
        selector.full_tokenizer = SimpleNamespace(encode=lambda text, **kw: SimpleNamespace(ids=text.split()), decode=lambda ids: " ".join(ids))
        segments = selector.segments("Title", " ".join(words))
        self.assertTrue(all(word in " ".join(segments) for word in words))
        self.assertGreater(len(segments), 1)

    def test_conservative_decision_boundary(self):
        evidence = semantic.contribution("Network Games", "We prove equilibrium uniqueness in a network game.")
        self.assertEqual(semantic.decide(.5, .1, evidence, True), "include")
        self.assertEqual(semantic.decide(.24, -.09, evidence, True), "review")
        self.assertEqual(semantic.decide(.5, .1, evidence, False), "review")
        self.assertEqual(semantic.decide(.2, -.1, evidence, True), "exclude")

    def test_rescreen_preserves_first_seen(self):
        first = update.merge({}, [work()], NOW, {})
        selector = Mock()
        selector.classify.return_value = ["Game Theory & Networks"]
        selector.decisions = {work()["DOI"]: {"decision": "include"}}
        selector.stats = {}
        second = update.merge(first, [work()], NOW + timedelta(days=1), {}, selector, True)
        self.assertEqual(second["papers"][0]["first_seen"], NOW.isoformat())

    def test_rescreen_can_remove_old_false_positive(self):
        first = update.merge({}, [work()], NOW, {})
        selector = Mock()
        selector.classify.return_value = []
        selector.decisions = {work()["DOI"]: {"decision": "exclude"}}
        selector.stats = {}
        second = update.merge(first, [work()], NOW, {}, selector, True)
        self.assertEqual(second["papers"], [])

    def test_fingerprint_changes_with_abstract(self):
        self.assertNotEqual(semantic.fingerprint("Title", "First"), semantic.fingerprint("Title", "Second"))
        self.assertNotEqual(semantic.fingerprint("Title", "First", ["C72"]), semantic.fingerprint("Title", "First", ["G12"]))

    def test_no_full_abstract_in_public_record(self):
        abstract = " ".join("word" + str(i) for i in range(100))
        selector = Mock()
        selector.classify.return_value = ["Game Theory & Networks"]
        selector.decisions = {work()["DOI"]: {"decision": "include"}}
        paper = update.normalize(work(abstract=abstract), NOW, selector)
        self.assertNotIn("abstract", paper)
        self.assertNotIn("word99", paper["excerpt"])
        self.assertTrue(paper["has_abstract"])


if __name__ == "__main__":
    unittest.main()
