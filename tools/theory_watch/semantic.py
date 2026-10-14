"""Semantic topic retrieval with auditable contribution/evidence checks."""

import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "semantic.json").read_text())
FORMAL = re.compile(r"\b((?:we|i) (?:prove|derive|characteri[sz]e)|theorems?|lemmas?|necessary and sufficient|if and only if|"
                    r"axiomati[cz]\w*|closed.form|fixed.point|"
                    r"(?:existence|uniqueness|impossibility) (?:theorem|result)|"
                    r"(?:equilibrium|equilibria) (?:exists?|coincide)|strategy.proof|incentive.compatib\w*)\b", re.I)
MODEL = re.compile(r"\b(model|framework|game|economy|economies|preferences?|mechanism)\b", re.I)
CLAIM = re.compile(r"\b((?:we|i) (?:show|derive|establish|solve|introduce)|"
                   r"optimal (?:contract|policy|allocation|design|mechanism|learning)|"
                   r"comparative statics|best response|stable matching|equilibrium conditions)\b", re.I)
EMPIRICAL = re.compile(r"\b(empirical|regression|difference.in.differences|instrumental variables?|"
                       r"field experiment|laboratory experiment|survey data|panel data|"
                       r"(?:we|i) (?:estimate|document|measure)|(?:using|based on|calibrated to)\b.{0,55}\bdata)\b", re.I)
MATH = re.compile(r"\b(equilibr\w*|optimal|optimi[sz]\w*|strategic|Nash|Bayesian|utility|axiom\w*|"
                  r"concav\w*|convex\w*|monotonic\w*|theorem\w*|lemma\w*|uniqueness|existence|parameters?|probabilit\w*|"
                  r"allocation\w*|incentive.compatib\w*|preferences?|matching|posteriors?|"
                  r"auctions?|mechanism design|information design|sufficient conditions?|necessary conditions?)\b", re.I)
EMPIRICAL_HEADING = re.compile(r"\b(empirical|evidence from|bibliometric|systematic review|scoping review|case study)\b", re.I)


def fingerprint(title, abstract, codes=()):
    return hashlib.sha256(json.dumps([CONFIG, title, abstract, list(codes)], sort_keys=True).encode()).hexdigest()


def explicit_jel(work, abstract):
    labeled = " ".join(str(value) for value in work.get("subject") or []) + " " + abstract
    match = re.search(r"\b(?i:JEL(?:\s+(?:codes?|classification))?)\s*[:\-]\s*([A-Z0-9,;.\s]+)", labeled)
    return sorted(set(re.findall(r"\b[A-Z]\d{1,2}\b", match[1]))) if match else []


def supported_jel(codes):
    return any(code.startswith(prefix) for code in codes for prefix in CONFIG["jel_codes"])


def contribution(title, abstract):
    from update import OUTSIDE_SCOPE, ECONOMIC
    return {"formal": len(FORMAL.findall(abstract)), "model_and_claim": bool(MODEL.search(abstract) and CLAIM.search(abstract)),
            "math_context": len(MATH.findall(abstract)),
            "economic_context": bool(ECONOMIC.search(title + " " + abstract)),
            "empirical": len(EMPIRICAL.findall(abstract)), "empirical_title": bool(EMPIRICAL_HEADING.search(title)),
            "outside_title": bool(OUTSIDE_SCOPE.search(title))}


def decide(score, margin, evidence, has_abstract):
    if evidence["outside_title"]:
        return "exclude"
    relevant = score >= CONFIG["include_minimum"] and margin >= CONFIG["include_margin"]
    formal, empirical = evidence["formal"], evidence["empirical"]
    if has_abstract and relevant and evidence["math_context"] >= 2 and evidence["economic_context"]:
        if formal and not evidence["empirical_title"] and empirical < max(3, 2 * formal):
            return "include"
        if evidence["model_and_claim"] and not empirical and not evidence["empirical_title"]:
            return "include"
    if score >= CONFIG["review_minimum"] and (formal or evidence["model_and_claim"] or not has_abstract):
        return "review"
    return "exclude"


class SemanticSelector:
    def __init__(self, cache_path, model_dir=None):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.np = np
        self.cache_path = Path(cache_path)
        self.cache = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}
        self.decisions = {}
        self.stats = {"retrieved": 0, "included": 0, "review": 0, "excluded": 0, "cached": 0}
        if model_dir:
            directory = Path(model_dir) / "minilm"
        else:
            from huggingface_hub import snapshot_download
            directory = Path(snapshot_download(CONFIG["embedding_model"], revision=CONFIG["embedding_revision"],
                allow_patterns=["tokenizer.json", "config.json", CONFIG["onnx_file"]]))
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=256)
        self.tokenizer.enable_padding()
        self.full_tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.full_tokenizer.no_truncation()
        self.full_tokenizer.no_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = int(os.environ.get("THEORY_WATCH_THREADS", "2"))
        self.session = ort.InferenceSession(str(directory / CONFIG["onnx_file"]), sess_options=options,
                                            providers=["CPUExecutionProvider"])
        self.topic_names = list(CONFIG["topics"])
        self.prototypes = self.embed(list(CONFIG["topics"].values()) + CONFIG["negative_prototypes"])

    def segments(self, title, abstract):
        title_ids = self.full_tokenizer.encode(title, add_special_tokens=False).ids[:100]
        title = self.full_tokenizer.decode(title_ids)
        tokens = self.full_tokenizer.encode(abstract, add_special_tokens=False).ids
        budget = 250 - len(title_ids)
        # Token windows cover the complete abstract without silent truncation.
        return [title + ". " + self.full_tokenizer.decode(tokens[start:start + budget])
                for start in range(0, len(tokens), budget - 32)] or [title]

    def embed(self, texts):
        results = []
        for start in range(0, len(texts), 32):
            tokens = self.tokenizer.encode_batch(texts[start:start + 32])
            arrays = {"input_ids": self.np.asarray([t.ids for t in tokens], dtype="int64"),
                      "attention_mask": self.np.asarray([t.attention_mask for t in tokens], dtype="int64"),
                      "token_type_ids": self.np.asarray([t.type_ids for t in tokens], dtype="int64")}
            output = self.session.run(None, {key.name: arrays[key.name] for key in self.session.get_inputs()})[0]
            weights = arrays["attention_mask"][..., None]
            pooled = (output * weights).sum(axis=1) / weights.sum(axis=1).clip(min=1)
            pooled /= self.np.linalg.norm(pooled, axis=1, keepdims=True).clip(min=1e-9)
            results.append(pooled)
        return self.np.concatenate(results)

    def prepare(self, records):
        from update import plain
        pending, texts, offsets = [], [], []
        for work in records:
            title = plain(" ".join(work.get("title") or []))
            abstract = plain(work.get("abstract", ""))
            codes = explicit_jel(work, abstract)
            key = fingerprint(title, abstract, codes)
            doi = str(work.get("DOI", "")).lower()
            if key in self.cache:
                self.decisions[doi] = self.cache[key]
                self.stats["cached"] += 1
                continue
            segments = self.segments(title, abstract)
            offsets.append((len(texts), len(segments)))
            texts.extend(segments)
            pending.append((doi, title, abstract, key, codes))
        print(f"Semantic screening: {len(pending)} uncached records, {len(texts)} abstract windows", flush=True)
        for start in range(0, len(pending), 128):
            end = min(start + 128, len(pending))
            text_start, text_end = offsets[start][0], sum(offsets[end - 1])
            similarities = self.embed(texts[text_start:text_end]) @ self.prototypes.T
            for index in range(start, end):
                doi, title, abstract, key, codes = pending[index]
                offset, length = offsets[index]
                scores = similarities[offset - text_start:offset - text_start + length].max(axis=0)
                positive = float(scores[:len(self.topic_names)].max())
                negative = float(scores[len(self.topic_names):].max())
                selected = (positive >= CONFIG["retrieval_minimum"] and positive - negative >= CONFIG["retrieval_margin"]) or supported_jel(codes)
                evidence = contribution(title, abstract)
                decision = {"decision": "exclude", "retrieval_score": round(positive, 4),
                            "retrieval_margin": round(positive - negative, 4), "jel_codes": codes, "evidence": evidence}
                if selected:
                    self.stats["retrieved"] += 1
                    order = self.np.argsort(scores[:len(self.topic_names)])[::-1]
                    decision.update({"decision": decide(positive, positive - negative, evidence, bool(abstract)),
                        "topics": [self.topic_names[i] for i in order[:2] if scores[i] >= max(.23, positive - .055)]})
                self.decisions[doi] = decision
                self.cache[key] = decision
            print(f"Screened {end}/{len(pending)}; retrieval candidates {self.stats['retrieved']}", flush=True)
        for decision in self.decisions.values():
            self.stats[{"include": "included", "review": "review", "exclude": "excluded"}[decision["decision"]]] += 1

    def classify(self, title, abstract, doi):
        decision = self.decisions[doi]
        return decision.get("topics", []) if decision["decision"] == "include" else []

    def save(self):
        from update import write_text
        write_text(self.cache_path, json.dumps(self.cache))
