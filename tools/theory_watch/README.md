# Theory Watch

An independent daily discovery index of SSRN economic-theory papers, maintained by Sijie Wang.

## Source and scope

The collector uses the public Crossref REST API, restricted to DOI prefix `10.2139` and identifiers of the form `10.2139/ssrn.NUMBER`. It does not scrape SSRN or download papers. Crossref records provide titles, authors, abstracts, registration timestamps, and metadata deposit timestamps. These are publisher-deposited metadata, not a complete or immediate SSRN submission stream.

`semantic.json` defines semantic topic retrieval using MiniLM sentence embeddings, followed by transparent formal-contribution and empirical-evidence checks in `semantic.py`. Topic retrieval is not an exact phrase/author-keyword gate. The second stage remains a text heuristic, not a learned method classifier or an assessment of proof validity. Small zero-shot NLI classifiers were tested and rejected because they missed many clear theory papers. The deployed model uses a pinned public revision and local CPU ONNX inference without paid APIs or remote inference services. Token windows read complete long abstracts. Explicit JEL codes, when present in deposited metadata, support retrieval; this is not an official SSRN subject-category feed. Borderline cases and records without abstracts are withheld for review. Cosine scores are not probabilities or quality judgments. False positives and missed papers remain possible. `rules.json` retains legacy phrase rules for regression comparisons and supports DOI-level editorial inclusions/exclusions.

The initial run scans the last 14 days of DOI registrations. Later runs scan metadata deposits since the last successful check, with a two-day overlap. IDs are deduplicated; records with the same normalized title and author set are also merged, retaining alternate SSRN IDs in `ssrn_ids`. A record's `first_seen` remains stable. A title, author, or abstract change sets `record_updated_at`; this is not described as a new paper version. Full abstracts are used during selection but only short excerpts (at most 20 words) and fingerprints are stored in the public archive.

The archive begins with DOI registrations from September 30, 2026 (`registrations_from` in `rules.json`). Older registrations encountered in metadata-deposit queries are skipped, so routine updates to old records do not appear as newly discovered papers in this feed.

Failed or incomplete collection does not advance the checkpoint or publish an empty replacement. The last successful static page remains online. The page flags checks older than three days as delayed.

## Run

Python 3.12 or later:

```sh
pip install -r tools/theory_watch/requirements.txt
python tools/theory_watch/update.py --site-dir site
python -m unittest discover -s tools/theory_watch -p 'test_*.py'
```

`site` must contain the current `gh-pages` checkout. The collector owns only `site/theory-watch/`. The workflow commits that directory without forcing a push, then deploys the complete `gh-pages` site using GitHub Pages actions. Existing homepage files, seminar redirects, images, and CV are included in the deployment.

The workflow is installed on `main` for daily scheduling and on `gh-pages` for publishing manual website edits. Scheduled runs use 00:17 UTC (08:17 Asia/Shanghai); GitHub may start scheduled workflows later during busy periods. Use **Actions → Theory Watch and website → Run workflow** to retry manually. The workflow uses GitHub's built-in token; no external API key or running personal computer is required.

`papers.json` is the persistent archive and checkpoint. `index.html`, `feed.xml`, `rules.json`, `method.json`, `watch.css`, and `watch.js` are generated. Change the corresponding files under `tools/theory_watch/` on `main`, then run the workflow. RSS contains the latest 100 registrations; JSON retains the selected archive. Full original abstracts are fetched directly from the public Crossref API when a reader expands one, with SSRN attribution and fallback links. They are not mirrored in this repository. The browser renders source text only, never raw HTML.

GitHub Actions caches public model files and decisions by model configuration and title/abstract fingerprint. Changed records are screened again. The review artifact contains only bibliographic metadata, short excerpts and model scores, not complete abstracts. Models and input records are not uploaded to an external AI service. Model or collection failures stop before advancing the published checkpoint.

For a full migration, use `--rescreen` (or `--input raw.json --rescreen` for a complete saved registration window). This preserves the first-seen date of retained papers and removes previous false positives. `--model-dir` supports an offline directory with `minilm/` model files; `--cache` and `--review-output` configure non-public working outputs. Do not publish raw metadata dumps containing complete abstracts. `validation_cases.json` contains agent-reviewed regression examples, not an independent human benchmark or a corpus-wide accuracy estimate.
