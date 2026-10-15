# Theory Watch

An independent selected reading list of SSRN microeconomic-theory papers, maintained by Sijie Wang. Discovery runs daily; publication is separately gated and has no daily quota.

## Source and scope

The collector uses the public Crossref REST API, restricted to DOI prefix `10.2139` and identifiers of the form `10.2139/ssrn.NUMBER`. It does not scrape SSRN or download papers. Crossref records provide titles, authors, abstracts, registration timestamps, and metadata deposit timestamps. These are publisher-deposited metadata, not a complete or immediate SSRN submission stream.

The scope is microeconomic theory: games and networks, mechanism and market design, information and contracts, decision and social choice, general equilibrium foundations, and theoretical IO. The former broad macro/growth/other-theory retrieval category has been removed. An application merely using game theory, equilibrium or optimization does not qualify. Primarily empirical, calibrated macro-finance, engineering optimization and management-framework papers are outside the public list unless their principal contribution is genuinely to microeconomic theory. Foundational preference and equilibrium papers can remain eligible even if their applications are macroeconomic or financial.

## Discovery is not publication

Automatic semantic matches, including borderline records, enter a separate candidate archive. They never automatically enter the public page, static fallback, JSON or RSS. `curation.py` enforces an exact DOI and content-fingerprint approval in `curation.json` for every public record. Legacy discovery overrides in `rules.json` cannot bypass this gate. A changed title, author list or abstract requires a fresh approval, even if the DOI was selected before; ordinary deposit timestamp changes do not. Explicit exclusions take precedence.

Selection records include topic, a brief contribution-specific reason, review date, primary sources, and the extent of screening. Initial records were screened with Codex assistance; the site does not claim the owner personally reviewed them. `abstract_and_source` means only an abstract and source check; `abstract_and_main_results` means the stated model/results were also inspected, not that all proofs were verified. Neither level is peer review or a guarantee of correctness, novelty, or quality. Author reputation and affiliation are not admission rules. Absence from the list is not an adverse quality judgment. Collection dates and selection-review dates are shown separately.

To add a selection, inspect the candidate's abstract, research question, relation to the literature and analytical results; consult the paper where needed. Copy the exact current candidate fingerprint into a new approval, record the actual screening level and evidence, and run the tests and workflow. Approvals can also be removed. There is no minimum number of papers to publish per day. No unattended peer-review or automatic quality-assessment service is claimed.

`semantic.json` defines semantic topic retrieval using MiniLM sentence embeddings, followed by transparent formal-contribution and empirical-evidence checks in `semantic.py`. Topic retrieval is not an exact phrase/author-keyword gate. The second stage remains a text heuristic, not a learned method classifier or an assessment of proof validity. Small zero-shot NLI classifiers were tested and rejected because they missed many clear theory papers. The deployed model uses a pinned public revision and local CPU ONNX inference without paid APIs or remote inference services. Token windows read complete long abstracts. Explicit JEL codes, when present in deposited metadata, support retrieval; this is not an official SSRN subject-category feed. Borderline cases and records without abstracts are withheld for review. Cosine scores are not probabilities or quality judgments. False positives and missed papers remain possible. `rules.json` retains legacy phrase rules for regression comparisons and supports DOI-level editorial inclusions/exclusions.

The first run or a cache rebuild scans the complete registration window from the configured coverage start. Later runs scan metadata deposits since the last successful check, with a two-day overlap. IDs are deduplicated; records with the same normalized title and author set are also merged, retaining alternate SSRN IDs in `ssrn_ids`. A record's `first_seen` remains stable. A title, author, or abstract change sets `record_updated_at`; this is not described as a new paper version. Full abstracts are used during selection but only short excerpts (at most 20 words) and fingerprints are stored in the public archive.

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

`papers.json` contains only approved selections and the public collection checkpoint. `index.html`, `feed.xml`, `rules.json`, `method.json`, `curation.json`, `watch.css`, and `watch.js` are generated. Change the corresponding source files under `tools/theory_watch/` on `main`, then run the workflow. RSS contains only the latest 100 selected registrations. Full original abstracts are fetched directly from the public Crossref API when a reader expands one, with SSRN attribution and fallback links. They are not mirrored in this repository. The browser renders source text only, never raw HTML.

Discovery state is retained outside the website in `.cache/theory-watch/candidates.json` and the Actions cache, not in deployed assets. If the candidate cache is missing, corrupt, older than the published checkpoint, or uses an old discovery configuration, the collector rebuilds the complete registration window before advancing the checkpoint. This prevents cache eviction from silently losing earlier candidates. Rebuilds can take longer; an incomplete or failed rebuild preserves the published site. The workflow saves all unselected candidates to its 30-day review artifact. It contains bibliographic metadata, at most 20-word excerpts and fingerprints, never complete abstracts. GitHub workflow artifacts are not claimed to be private; they are simply not deployed or presented as recommendations.

GitHub Actions caches public model files and decisions by model configuration and title/abstract fingerprint. Changed records are screened again. Models and input records are not uploaded to an external AI service. Model or collection failures stop before advancing the published checkpoint.

For a full migration, use `--rescreen` (or `--input raw.json --rescreen` for a complete saved registration window). This preserves the first-seen date of retained papers and removes previous false positives. `--model-dir` supports an offline directory with `minilm/` model files; `--cache` and `--review-output` configure non-public working outputs. Do not publish raw metadata dumps containing complete abstracts. `validation_cases.json` contains agent-reviewed regression examples, not an independent human benchmark or a corpus-wide accuracy estimate.
