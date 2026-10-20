"""A fail-closed publication gate, separate from automatic topic discovery."""

from copy import deepcopy
from datetime import date, datetime
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
POLICY = json.loads((ROOT / "curation.json").read_text())
EXCLUDED = set(json.loads((ROOT / "rules.json").read_text())["exclude_dois"])


def validate(policy):
    topics = json.loads((ROOT / "semantic.json").read_text())["topics"]
    for doi, entry in policy.get("decisions", {}).items():
        if (not re.fullmatch(r"10\.2139/ssrn\.\d+", doi)
                or not re.fullmatch(r"[a-f0-9]{64}", entry["fingerprint"])
                or entry["decision"] not in ("include", "exclude", "defer")
                or not entry["reason"].strip()):
            raise ValueError("Invalid content-screening decision")
        datetime.fromisoformat(entry["reviewed_at"])
        if entry["decision"] == "defer":
            datetime.fromisoformat(entry["retry_after"])
    if policy.get("review_status"):
        datetime.fromisoformat(policy["review_status"]["last_completed"])
    for doi, entry in policy["approvals"].items():
        if not re.fullmatch(r"10\.2139/ssrn\.\d+", doi):
            raise ValueError("Invalid approval DOI")
        if not re.fullmatch(r"[a-f0-9]{64}", entry["fingerprint"]):
            raise ValueError("Approval needs the exact content fingerprint")
        date.fromisoformat(entry["reviewed_at"])
        if entry["review_level"] not in ("abstract_and_source", "abstract_and_main_results"):
            raise ValueError("Unknown review level")
        if not entry["topics"] or any(topic not in topics for topic in entry["topics"]):
            raise ValueError("Approval has an invalid microeconomic-theory topic")
        if not entry["reason"].strip() or not entry["sources"] or any(
            not source.startswith("https://") for source in entry["sources"]
        ):
            raise ValueError("Approval needs a contribution note and source")


validate(POLICY)


def approval(paper, policy=POLICY):
    entry = policy["approvals"].get(paper["doi"])
    decision = policy.get("decisions", {}).get(paper["doi"], {})
    if decision.get("fingerprint") == paper.get("fingerprint") and decision.get("decision") == "exclude":
        return None
    return entry if entry and paper["doi"] not in EXCLUDED and entry["fingerprint"] == paper.get("fingerprint") else None


def select_public(candidates, policy=POLICY):
    validate(policy)
    result = deepcopy(candidates)
    result["archive_kind"] = "selected_papers"
    result["selection_mode"] = "curated"
    result["selection"] = "Content-screened microeconomic-theory selections; automatic discovery alone never authorizes publication"
    result["curation_version"] = policy["version"]
    result["papers"] = []
    for paper in candidates.get("papers", []):
        entry = approval(paper, policy)
        if entry:
            selected = {key: value for key, value in paper.items() if not key.startswith("candidate_")}
            selected.update(topics=entry["topics"], selection_reason="Content-screened selection",
                            selection_note=entry["reason"], reviewed_at=entry["reviewed_at"],
                            review_level=entry["review_level"], review_sources=entry["sources"])
            result["papers"].append(selected)
    result["last_selection_review"] = max((paper["reviewed_at"] for paper in result["papers"]), default=None)
    result["review_status"] = deepcopy(policy.get("review_status", {}))
    return result


def review_report(candidates, policy=POLICY):
    pending = []
    for paper in candidates.get("papers", []):
        if not approval(paper, policy):
            decision = policy.get("decisions", {}).get(paper["doi"], {})
            if decision.get("fingerprint") == paper.get("fingerprint") and decision.get("decision") == "exclude":
                continue
            changed = paper["doi"] in policy["approvals"]
            pending.append({**paper, "publication_status": "content_changed_requires_review" if changed else "awaiting_content_review"})
    return {"checked_at": candidates["last_successful_check"], "scope": policy["scope"],
            "notice": "Discovery candidates, not recommendations. No complete abstracts are stored.",
            "pending_count": len(pending), "papers": pending}
