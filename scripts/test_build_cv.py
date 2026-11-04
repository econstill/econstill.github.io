import json
from pathlib import Path
import tempfile
import unittest

from lxml import html

from build_cv import inline, load_content


class CVSourceTests(unittest.TestCase):
    def fixture(self, root):
        (root / "scripts").mkdir()
        (root / "scripts/cv_education.json").write_text(json.dumps(["Retained education."]))
        (root / "index.html").write_text("""<main>
          <section><h2>About</h2><div><h2>Research Interests</h2>
          <ul><li>Game theory</li></ul></div></section>
          <section><h2>Publications</h2><ol><li>Published paper</li></ol></section>
          <section><h2>Working Papers</h2><ol><li>Working paper</li></ol></section>
          <section><h2>Work in Progress</h2><ol><li>New work</li></ol></section>
        </main>""")

    def test_nested_interests_and_cv_only_education(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            _, sections, education, interests = load_content(root)
            self.assertNotIn("Education", sections)
            self.assertEqual(education, ["Retained education."])
            self.assertEqual(interests, ["Game theory"])

    def test_empty_education_fails_instead_of_disappearing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / "scripts/cv_education.json").write_text("[]")
            with self.assertRaisesRegex(ValueError, "must not be empty"):
                load_content(root)

    def test_legacy_education_section_takes_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            page = root / "index.html"
            page.write_text(page.read_text().replace("</main>", """
              <section><h2>Education</h2><ul><li>Current education.</li></ul></section>
              </main>"""))
            _, _, education, _ = load_content(root)
            self.assertEqual(education, ["Current education."])

    def test_relative_links_become_absolute_in_pdf(self):
        result = inline(html.fromstring('<p><a href="theory-watch/">Theory Watch</a></p>'))
        self.assertIn('href="https://econstill.github.io/theory-watch/"', result)


if __name__ == "__main__":
    unittest.main()
