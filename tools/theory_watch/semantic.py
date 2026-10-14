"""Local, pinned ONNX models; complete abstracts are used but never cached here."""

import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "semantic.json").read_text())


def fingerprint(title, abstract):
    return hashlib.sha256(json.dumps([CONFIG, title, abstract], sort_keys=True).encode()).hexdigest()


def explicit_jel(work, abstract):
    # Require an explicit JEL label; a bare code in prose is not classification metadata.
    values = work.get("subject") or []
    labeled = " ".join(str(value) for value in values) + " " + abstract
    match = re.search(r"\b(?i:JEL(?:\s+(?:codes?|classification))?)\s*[:\-]\s*([A-Z0-9,;.\s]+)", labeled)
    return sorted(set(re.findall(r"\b[A-Z]\d{1,2}\b", match[1]))) if match else []


def supported_jel(codes):
    return any(code.startswith(prefix) for code in codes for prefix in CONFIG["jel_codes"])


def chunks(title, abstract):
    words = abstract.split()
    if not words:
        return [title]
    # Overlapping windows cover the whole abstract, not just the lead paragraph.
    return [title + ". " + " ".join(words[start:start + 170]) for start in range(0, len(words), 140)]


def decide(theory, empirical, outside, has_abstract):
    margin = theory - max(empirical, outside)
    if has_abstract and theory >= CONFIG["include_minimum"] and margin >= CONFIG["include_margin"]:
        return "include"
    if theory >= CONFIG["review_minimum"]:
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
        self.models = {}
        for name in ("embedding", "nli"):
            onnx_file = CONFIG["nli_onnx_file"] if name == "nli" else CONFIG["onnx_file"]
            if model_dir:
                directory = Path(model_dir) / ("minilm" if name == "embedding" else "nli")
            else:
                from huggingface_hub import snapshot_download
                directory = Path(snapshot_download(
                    CONFIG[name + "_model"], revision=CONFIG[name + "_revision"],
                    allow_patterns=["tokenizer.json", "config.json", onnx_file],
                ))
            tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
            tokenizer.enable_truncation(max_length=256 if name == "embedding" else 512,
                                        strategy="longest_first" if name == "embedding" else "only_first")
            tokenizer.enable_padding()
            options = ort.SessionOptions()
            options.intra_op_num_threads = int(os.environ.get("THEORY_WATCH_THREADS", "2"))
            session = ort.InferenceSession(str(directory / onnx_file), sess_options=options,
                                          providers=["CPUExecutionProvider"])
            config = json.loads((directory / "config.json").read_text())
            self.models[name] = (tokenizer, session, config)
        label_map = self.models["nli"][2]["id2label"]
        self.entailment = next(int(key) for key, value in label_map.items() if value.lower() == "entailment")
        self.topic_names = list(CONFIG["topics"])
        self.prototypes = self.embed(list(CONFIG["topics"].values()) + CONFIG["negative_prototypes"])

    def infer(self, name, texts):
        tokenizer, session, _ = self.models[name]
        tokens = tokenizer.encode_batch(texts)
        arrays = {
            "input_ids": self.np.asarray([token.ids for token in tokens], dtype="int64"),
            "attention_mask": self.np.asarray([token.attention_mask for token in tokens], dtype="int64"),
            "token_type_ids": self.np.asarray([token.type_ids for token in tokens], dtype="int64"),
        }
        output = session.run(None, {key.name: arrays[key.name] for key in session.get_inputs()})[0]
        return output, arrays["attention_mask"]

    def embed(self, texts):
        results = []
        for start in range(0, len(texts), 32):
            output, mask = self.infer("embedding", texts[start:start + 32])
            weights = mask[..., None]
            pooled = (output * weights).sum(axis=1) / weights.sum(axis=1).clip(min=1)
            pooled /= self.np.linalg.norm(pooled, axis=1, keepdims=True).clip(min=1e-9)
            results.append(pooled)
        return self.np.concatenate(results)

    def prepare(self, records):
        from update import plain
        pending = []
        texts, offsets = [], []
        for work in records:
            title = plain(" ".join(work.get("title") or []))
            abstract = plain(work.get("abstract", ""))
            key = fingerprint(title, abstract)
            doi = str(work.get("DOI", "")).lower()
            if key in self.cache:
                self.decisions[doi] = self.cache[key]
                self.stats["cached"] += 1
                continue
            segments = chunks(title, abstract)
            offsets.append((len(texts), len(segments)))
            texts.extend(segments)
            pending.append((doi, title, abstract, key, explicit_jel(work, abstract)))
        print(f"Semantic screening: {len(pending)} uncached records, {len(texts)} abstract windows", flush=True)
        for start in range(0, len(pending), 128):
            end = min(start + 128, len(pending))
            text_start = offsets[start][0]
            text_end = sum(offsets[end - 1])
            vectors = self.embed(texts[text_start:text_end])
            similarities = vectors @ self.prototypes.T
            for index in range(start, end):
                doi, title, abstract, key, codes = pending[index]
                offset, length = offsets[index]
                scores = similarities[offset - text_start:offset - text_start + length].max(axis=0)
                positive = float(scores[:len(self.topic_names)].max())
                negative = float(scores[len(self.topic_names):].max())
                selected = positive >= CONFIG["retrieval_minimum"] and positive - negative >= CONFIG["retrieval_margin"]
                selected = selected or supported_jel(codes)
                decision = {"decision": "exclude", "retrieval_score": round(positive, 4), "jel_codes": codes}
                if selected:
                    self.stats["retrieved"] += 1
                    # Every window is checked. Strong empirical/outside evidence anywhere also counts.
                    premises = chunks(title, abstract)
                    pairs = [(text, hypothesis) for text in premises for hypothesis in CONFIG["hypotheses"]]
                    logits = []
                    for batch in range(0, len(pairs), 12):
                        output, _ = self.infer("nli", pairs[batch:batch + 12])
                        output = output - output.max(axis=1, keepdims=True)
                        probabilities = self.np.exp(output)
                        probabilities /= probabilities.sum(axis=1, keepdims=True)
                        logits.extend(probabilities[:, self.entailment])
                    theory, empirical, outside = self.np.asarray(logits).reshape(-1, 3).max(axis=0)
                    order = self.np.argsort(scores[:len(self.topic_names)])[::-1]
                    topics = [self.topic_names[i] for i in order[:2] if scores[i] >= max(0.25, positive - 0.055)]
                    decision.update({"decision": decide(float(theory), float(empirical), float(outside), bool(abstract)),
                                     "scores": [round(float(value), 4) for value in (theory, empirical, outside)],
                                     "topics": topics or [self.topic_names[order[0]]]})
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
