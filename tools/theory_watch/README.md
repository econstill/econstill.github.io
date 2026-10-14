# Theory Watch

An independent daily discovery index of SSRN economic-theory papers, maintained by Sijie Wang.

## Source and scope

The collector uses the public Crossref REST API, restricted to DOI prefix `10.2139` and identifiers of the form `10.2139/ssrn.NUMBER`. It does not scrape SSRN or download papers. Crossref records provide titles, authors, abstracts, registration timestamps, and metadata deposit timestamps. These are publisher-deposited metadata, not a complete or immediate SSRN submission stream.

`rules.json` defines automatic topic matching across game theory and networks, mechanism and market design, information and contracts, decision and social choice, and equilibrium and mathematical economics. Selection uses both title and abstract evidence; it is a discovery heuristic rather than an official SSRN classification or quality assessment. False positives and missed papers are expected. Add DOI strings to `include_dois` or `exclude_dois` for editorial corrections.

The initial run scans the last 14 days of DOI registrations. Later runs scan metadata deposits since the last successful check, with a two-day overlap. IDs are deduplicated; records with the same normalized title and author set are also merged, retaining alternate SSRN IDs in `ssrn_ids`. A record's `first_seen` remains stable. A title, author, or abstract change sets `record_updated_at`; this is not described as a new paper version. Full abstracts are used during selection but only short excerpts (at most 20 words) and fingerprints are stored in the public archive.

The archive begins with DOI registrations from September 30, 2026 (`registrations_from` in `rules.json`). Older registrations encountered in metadata-deposit queries are skipped, so routine updates to old records do not appear as newly discovered papers in this feed.

Failed or incomplete collection does not advance the checkpoint or publish an empty replacement. The last successful static page remains online. The page flags checks older than three days as delayed.

## Run

Python 3.12 or later; standard library only:

```sh
python tools/theory_watch/update.py --site-dir site
python -m unittest discover -s tools/theory_watch -p 'test_*.py'
```

`site` must contain the current `gh-pages` checkout. The collector owns only `site/theory-watch/`. The workflow commits that directory without forcing a push, then deploys the complete `gh-pages` site using GitHub Pages actions. Existing homepage files, seminar redirects, images, and CV are included in the deployment.

The workflow is installed on `main` for daily scheduling and on `gh-pages` for publishing manual website edits. Scheduled runs use 00:17 UTC (08:17 Asia/Shanghai); GitHub may start scheduled workflows later during busy periods. Use **Actions → Theory Watch and website → Run workflow** to retry manually. The workflow uses GitHub's built-in token; no external API key or running personal computer is required.

`papers.json` is the persistent archive and checkpoint. `index.html`, `feed.xml`, `rules.json`, `watch.css`, and `watch.js` in the published directory are generated. Change the corresponding files under `tools/theory_watch/` on `main`, then run the workflow to update them. The RSS feed contains the 100 latest DOI registrations; the JSON archive retains all collected records.
