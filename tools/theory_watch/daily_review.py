"""Prepare evidence for a Codex review, then validate and publish its decisions.

This is not an automatic classifier. A scheduled Codex run must read each queued
abstract and supply content-specific decisions. Only public metadata is fetched.
"""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys


REPO = "econstill/econstill.github.io"
TOOLS = "tools/theory_watch/"


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True)


def api(endpoint, method="GET", body=None):
    command = ["gh", "api", f"repos/{REPO}/{endpoint}", "--method", method]
    if body is not None:
        command += ["--input", "-"]
    return json.loads(subprocess.check_output(command, text=True,
                                             input=json.dumps(body) if body is not None else None))


def read(path):
    return json.loads(path.read_text())


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def snapshot(root):
    import base64
    manifest = {}
    for branch, folder in (("main", "source"), ("gh-pages", "site")):
        sha = api(f"git/ref/heads/{branch}")["object"]["sha"]
        commit = api(f"git/commits/{sha}")
        tree = api(f"git/trees/{commit['tree']['sha']}?recursive=1")
        if tree.get("truncated"):
            raise ValueError("Incomplete repository tree")
        manifest[branch] = {"sha": sha, "tree": tree["tree"]}
        for item in tree["tree"]:
            prefix = TOOLS if branch == "main" else "theory-watch/"
            if item["type"] != "blob" or not item["path"].startswith(prefix):
                continue
            data = base64.b64decode(api(f"git/blobs/{item['sha']}")["content"])
            for directory in (folder, "before-" + branch):
                target = root / directory / item["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        if api(f"git/ref/heads/{branch}")["object"]["sha"] != sha:
            raise ValueError("Repository changed during preparation; start a fresh batch")
    save(root / "snapshot.json", manifest)


def queue_candidates(papers, policy, now, limit):
    pending = []
    for paper in papers:
        old = policy.get("approvals", {}).get(paper["doi"], {})
        decision = policy.get("decisions", {}).get(paper["doi"], {})
        if old.get("fingerprint") == paper.get("fingerprint"):
            continue
        if decision.get("fingerprint") == paper.get("fingerprint"):
            if decision.get("decision") == "exclude":
                continue
            if decision.get("decision") == "defer" and now.isoformat() < decision.get("retry_after", ""):
                continue
        pending.append(paper)
    pending.sort(key=lambda p: (p["indexed_at"], int(p["id"])), reverse=True)
    # Reserve capacity for the old backlog, rather than starving it behind new papers.
    old_count = min(10, limit // 5) if len(pending) > limit else 0
    selected = pending[:limit - old_count]
    if old_count:
        selected += pending[-old_count:]
    return selected


def source_identity(work, plain):
    title = plain(" ".join(work.get("title") or []))
    authors = []
    for author in work.get("author") or []:
        name = plain(" ".join(filter(None, [author.get("given"), author.get("family")])) or author.get("name", ""))
        if name:
            authors.append(name)
    abstract = plain(work.get("abstract", ""))
    fingerprint = hashlib.sha256(json.dumps([title, authors, abstract], ensure_ascii=False,
                                            separators=(",", ":")).encode()).hexdigest()
    return title, authors, abstract, fingerprint


def prepare(root, limit):
    if root.exists() and any(root.iterdir()):
        raise ValueError("Use a new empty batch directory")
    root.mkdir(parents=True, exist_ok=True)
    snapshot(root)
    source = root / "source" / TOOLS
    sys.path.insert(0, str(source))
    from update import plain, request_json
    policy = read(source / "curation.json")
    runs = json.loads(gh("run", "list", "--repo", REPO, "--workflow", "theory-watch.yml",
                         "--limit", "50", "--json", "databaseId,event,conclusion,createdAt"))
    run = next((run for run in runs if run["conclusion"] == "success"
                and run["event"] in ("schedule", "workflow_dispatch")), None)
    if not run:
        raise ValueError("No successful collection with a review artifact")
    gh("run", "download", str(run["databaseId"]), "--repo", REPO,
       "--name", "theory-watch-review", "--dir", str(root / "artifact"))
    report = read(root / "artifact/pending.json")
    published = read(root / "site/theory-watch/papers.json")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    checked = datetime.fromisoformat(report["checked_at"])
    if now - checked > timedelta(days=3) or report["checked_at"] < published["last_successful_check"]:
        raise ValueError("Collection is stale or artifact is behind the live feed; do not publish an obsolete batch")
    papers = queue_candidates(report["papers"], policy, now, limit)
    queue = []
    for paper in papers:
        entry = dict(paper)
        try:
            work = request_json("https://api.crossref.org/works/" + paper["doi"])["message"]
            if work.get("DOI", "").lower() != paper["doi"]:
                raise ValueError("Wrong source DOI")
            title, authors, abstract, fingerprint = source_identity(work, plain)
            if fingerprint != paper["fingerprint"]:
                raise ValueError("Source content changed since collection; wait for fresh discovery")
            entry.update(abstract=abstract, evidence_verified=True)
        except Exception as exc:
            entry.update(abstract="", evidence_verified=False, source_error=str(exc))
        queue.append(entry)
        print(paper["doi"], "ready" if entry["evidence_verified"] else "defer: source unavailable", flush=True)
    save(root / "queue.json", {"prepared_at": now.isoformat(), "collection_run": run["databaseId"],
                               "checked_at": report["checked_at"], "papers": queue})
    print(f"Prepared {len(queue)} papers. Read queue.json; full abstracts stay local and must not be published.")


def apply_decisions(root, batch):
    source = root / "source" / TOOLS
    sys.path.insert(0, str(source))
    from curation import validate
    policy = read(source / "curation.json")
    queue = read(root / "queue.json")
    evidence = {p["doi"]: p for p in queue["papers"]}
    decisions = batch["decisions"]
    if len(decisions) != len(evidence) or {d["doi"] for d in decisions} != set(evidence):
        raise ValueError("Every queued paper needs exactly one include, exclude, or defer decision")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    for decision in decisions:
        paper = evidence[decision["doi"]]
        action = decision["decision"]
        if action not in ("include", "exclude", "defer") or not decision.get("reason", "").strip():
            raise ValueError("Missing content decision and reason")
        if decision.get("fingerprint") != paper["fingerprint"]:
            raise ValueError("Decision does not match the reviewed content")
        if action != "defer" and (not paper.get("evidence_verified") or not paper.get("abstract")):
            raise ValueError("Missing verified abstract: defer instead of judging unavailable content")
        record = {key: decision[key] for key in ("fingerprint", "decision", "reason")}
        record.update(reviewed_at=now.isoformat(), reviewer="Codex-assisted content screening")
        if action == "include":
            entry = {key: decision[key] for key in ("fingerprint", "reason", "topics", "review_level", "sources")}
            if paper["abstract_source"] not in entry["sources"]:
                raise ValueError("Record the verified abstract source")
            entry["reviewed_at"] = now.date().isoformat()
            policy["approvals"][paper["doi"]] = entry
        elif action == "exclude":
            policy["approvals"].pop(paper["doi"], None)
        else:
            record["retry_after"] = (now + timedelta(days=2)).isoformat()
        policy.setdefault("decisions", {})[paper["doi"]] = record
    counts = dict(Counter(d["decision"] for d in decisions))
    report = read(root / "artifact/pending.json")
    from curation import review_report
    remaining = review_report({"last_successful_check": report["checked_at"], "papers": report["papers"]}, policy)["pending_count"]
    policy["review_status"] = {"last_completed": now.isoformat(), "candidates_checked_through": queue["checked_at"],
                               "collection_run": queue["collection_run"], "reviewed_count": len(decisions),
                               "decisions": counts, "remaining_candidates": remaining}
    validate(policy)
    save(source / "curation.json", policy)
    published = read(root / "site/theory-watch/papers.json")
    papers = {p["doi"]: p for p in published["papers"]}
    papers.update({p["doi"]: p for p in report["papers"]})
    data = {**published, "archive_kind": "discovery_candidates",
            "papers": sorted(papers.values(), key=lambda p: (p["indexed_at"], int(p["id"])), reverse=True)}
    save(root / "candidate-state.json", data)
    subprocess.run([sys.executable, str(source / "update.py"), "--site-dir", str(root / "site"),
                    "--candidate-cache", str(root / "candidate-state.json"), "--render-only"], check=True)
    print(json.dumps(policy["review_status"]))


def publish(root):
    manifest = read(root / "snapshot.json")
    for branch in ("main", "gh-pages"):
        if api(f"git/ref/heads/{branch}")["object"]["sha"] != manifest[branch]["sha"]:
            raise ValueError("Remote changed. Prepare a fresh batch; never force-push or overwrite it.")
    receipts = []
    for branch, folder, prefix in (("main", "source", TOOLS + "curation.json"),
                                    ("gh-pages", "site", "theory-watch/")):
        changes = []
        for file in (root / folder).rglob("*"):
            if not file.is_file():
                continue
            relative = file.relative_to(root / folder).as_posix()
            old = root / ("before-" + branch) / relative
            if old.exists() and old.read_bytes() == file.read_bytes():
                continue
            if "__pycache__" in file.parts:
                continue
            if not (relative == prefix if branch == "main" else relative.startswith(prefix)):
                raise ValueError("Refusing unrelated modification: " + relative)
            changes.append({"path": relative, "mode": "100644", "type": "blob", "content": file.read_text()})
        if not changes:
            continue
        sha = manifest[branch]["sha"]
        commit = api(f"git/commits/{sha}")
        tree = api("git/trees", "POST", {"base_tree": commit["tree"]["sha"], "tree": changes})
        new = api("git/commits", "POST", {"message": "Screen Theory Watch candidates and refresh selections",
                                          "tree": tree["sha"], "parents": [sha]})
        if api(f"git/ref/heads/{branch}")["object"]["sha"] != sha:
            raise ValueError("Branch advanced; preserving remote changes")
        api(f"git/refs/heads/{branch}", "PATCH", {"sha": new["sha"], "force": False})
        receipts.append({"branch": branch, "sha": new["sha"], "files": [c["path"] for c in changes]})
        save(root / "published.json", receipts)
    print(json.dumps(receipts))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "apply", "publish"))
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--decisions", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        if not 1 <= args.limit <= 100:
            parser.error("Batch limit must be between 1 and 100")
        prepare(args.work_dir, args.limit)
    elif args.action == "apply":
        if not args.decisions:
            parser.error("Supply the Codex content decisions")
        apply_decisions(args.work_dir, read(args.decisions))
    else:
        publish(args.work_dir)


if __name__ == "__main__":
    main()
