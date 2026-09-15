"""Tiny TF-IDF retrieval over the bilingual knowledge base."""
import json
import os
from collections import Counter

import numpy as np

from tokenizer import normalizer as norm
from nlu.classifier import text_features

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "data")


def _tokens(text):
    t = norm.normalize(text)
    words = [w for w in t.split(" ") if w]
    grams = []
    s = "^" + t.replace(" ", "_") + "$"
    for n in (3, 4):
        for i in range(len(s) - n + 1):
            grams.append(s[i:i + n])
    return words + grams


class ResponseBank:
    """TF-IDF retrieval over the assistant's own response lines.

    Gives contextual, grammatical fallback answers for chit-chat that the
    rule/intent layers do not cover. Far safer than free-form generation.
    """

    def __init__(self, lines=None):
        self.lines = lines or []
        self._index = None

    def _build(self):
        docs = [Counter(_tokens(ln)) for ln in self.lines]
        df = Counter()
        for c in docs:
            for t in c:
                df[t] += 1
        n = max(1, len(docs))
        idf = {t: np.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}
        vecs = []
        for c in docs:
            v = {t: (1.0 + np.log(cnt)) * idf.get(t, 1.0) for t, cnt in c.items()}
            nrm = float(np.sqrt(sum(x * x for x in v.values()))) or 1.0
            vecs.append({t: x / nrm for t, x in v.items()})
        self._index = vecs

    def query(self, text, threshold=0.38):
        if not self.lines:
            return None, 0.0
        if self._index is None:
            self._build()
        c = Counter(_tokens(text))
        if not c:
            return None, 0.0
        q = {t: float(n) for t, n in c.items()}
        nrm = float(np.sqrt(sum(x * x for x in q.values()))) or 1.0
        q = {t: x / nrm for t, x in q.items()}
        best, best_s = None, 0.0
        for i, v in enumerate(self._index):
            s = sum(x * v[t] for t, x in q.items() if t in v)
            if s > best_s:
                best, best_s = self.lines[i], s
        if best is None or best_s < threshold:
            return None, best_s
        return best, best_s

    @classmethod
    def load(cls, corpus_path):
        lines = []
        try:
            with open(corpus_path, encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if raw.startswith("<a>") and len(raw) > 6:
                        lines.append(raw[3:].strip())
        except OSError:
            pass
        return cls(lines=lines)


class KnowledgeBase:
    def __init__(self, entries=None):
        self.entries = entries or []
        self._index = None

    # -------------------------------------------------------------- retrieval
    def _build_index(self):
        docs = []
        for e in self.entries:
            for lang in ("fa", "en"):
                for q in e.get(lang, {}).get("q", []):
                    docs.append((e, lang, Counter(_tokens(q))))
        df = Counter()
        for _, _, c in docs:
            for tok in c:
                df[tok] += 1
        n_docs = max(1, len(docs))
        idf = {t: np.log((n_docs + 1) / (c + 1)) + 1.0 for t, c in df.items()}
        vectors = []
        for e, lang, c in docs:
            v = {t: (1.0 + np.log(cnt)) * idf.get(t, 1.0) for t, cnt in c.items()}
            nrm = float(np.sqrt(sum(x * x for x in v.values()))) or 1.0
            vectors.append((e, lang, {t: x / nrm for t, x in v.items()}))
        self._index = vectors

    def query(self, text, lang=None, threshold=0.32):
        """Best matching entry; returns (answer, score) or (None, score)."""
        if not self.entries:
            return None, 0.0
        if self._index is None:
            self._build_index()
        c = Counter(_tokens(text))
        if not c:
            return None, 0.0
        q = {t: float(n) for t, n in c.items()}
        nrm = float(np.sqrt(sum(x * x for x in q.values()))) or 1.0
        q = {t: x / nrm for t, x in q.items()}

        best, best_score = None, 0.0
        for e, doc_lang, v in self._index:
            score = 0.0
            for t, x in q.items():
                if t in v:
                    score += x * v[t]
            # prefer documents in the user's language
            if lang and doc_lang == lang:
                score *= 1.15
            if score > best_score:
                best, best_score = (e, doc_lang), score
        if best is None or best_score < threshold:
            return None, best_score
        e, doc_lang = best
        ans_lang = lang if (lang and lang in e) else doc_lang
        return e.get(ans_lang, {}).get("a"), best_score

    # ------------------------------------------------------------ persistence
    @classmethod
    def load(cls, path=None):
        if path is None:
            path = os.path.join(DATA_DIR, "knowledge.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return cls(entries=data.get("entries", []))
        except (FileNotFoundError, OSError, ValueError):
            return cls()
