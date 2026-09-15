"""Intent classifier: hashed n-gram features + softmax regression (NumPy).

Language-agnostic by design: Persian and English both produce character
n-grams, so one model handles both. Ships trained weights.
"""
import json
import os

import numpy as np

from tokenizer import normalizer as norm

FEATURE_DIM = 6144


def _stable_hash(s):
    # deterministic across processes (unlike builtin hash)
    import zlib
    return zlib.crc32(s.encode("utf-8")) % FEATURE_DIM


def text_features(text, dim=FEATURE_DIM):
    """Hashed word + char n-gram features, L2 normalized."""
    t = norm.normalize(text)
    # trailing punctuation is noise for classification (سلام! == سلام)
    t = t.rstrip("!?.,;:؟،؛٪%")
    if not t:
        return np.zeros(dim, dtype=np.float32)
    words = t.split(" ")
    feats = []

    # word unigrams + bigrams
    for w in words:
        if w:
            feats.append("w:" + w)
    for i in range(len(words) - 1):
        feats.append("b:" + words[i] + "_" + words[i + 1])

    # char n-grams (3..5) over the whole string with boundary marks
    s = "^" + t.replace(" ", "_") + "$"
    for n in (3, 4, 5):
        for i in range(len(s) - n + 1):
            feats.append("c%d:%s" % (n, s[i:i + n]))

    vec = np.zeros(dim, dtype=np.float32)
    for f in feats:
        vec[_stable_hash(f)] += 1.0
    nrm = float(np.linalg.norm(vec))
    if nrm > 0:
        vec /= nrm
    return vec


class IntentClassifier:
    def __init__(self, labels=None, W=None, b=None):
        self.labels = labels or []
        self.W = W  # (D, K)
        self.b = b  # (K,)

    @property
    def ready(self):
        return self.W is not None and len(self.labels) > 0

    def predict(self, text):
        """Returns (label, confidence) or (None, 0.0) if not ready."""
        if not self.ready:
            return None, 0.0
        x = text_features(text)
        logits = x @ self.W + self.b
        e = np.exp(logits - logits.max())
        p = e / e.sum()
        i = int(np.argmax(p))
        return self.labels[i], float(p[i])

    # ------------------------------------------------------------------ train
    @staticmethod
    def train(samples, labels, epochs=400, lr=0.35, l2=1e-4, seed=3, verbose=False,
              eval_samples=None, eval_labels=None, eval_every=25):
        """Softmax regression over hashed n-gram features.

        If eval_samples/eval_labels are given, early stopping keeps the
        weights with the best held-out accuracy (checked every eval_every
        epochs).
        """
        uniq = sorted(set(labels))
        lab2i = {l: i for i, l in enumerate(uniq)}
        X = np.stack([text_features(s) for s in samples])
        Y = np.array([lab2i[l] for l in labels])
        D, K = FEATURE_DIM, len(uniq)
        rng = np.random.default_rng(seed)
        W = rng.standard_normal((D, K)) * 0.01
        b = np.zeros(K)
        N = len(samples)

        Xv = Yv = None
        if eval_samples:
            Xv = np.stack([text_features(s) for s in eval_samples])
            Yv = np.array([lab2i.get(l, -1) for l in eval_labels])
        best_acc, best_W, best_b, best_ep = -1.0, W.copy(), b.copy(), 0

        idx = np.arange(N)
        for ep in range(epochs):
            rng.shuffle(idx)
            for s0 in range(0, N, 64):
                sel = idx[s0:s0 + 64]
                xb, yb = X[sel], Y[sel]
                logits = xb @ W + b
                logits -= logits.max(axis=1, keepdims=True)
                e = np.exp(logits)
                p = e / e.sum(axis=1, keepdims=True)
                p[np.arange(len(yb)), yb] -= 1.0
                gW = xb.T @ p / len(yb) + l2 * W
                gb = p.mean(axis=0)
                W -= lr * gW
                b -= lr * gb
            if Xv is not None and ((ep + 1) % eval_every == 0 or ep == epochs - 1):
                acc = float(((Xv @ W + b).argmax(axis=1) == Yv).mean())
                if acc > best_acc:
                    best_acc, best_W, best_b, best_ep = acc, W.copy(), b.copy(), ep + 1
                if verbose:
                    print("  epoch %d | held-out acc %.4f (best %.4f @%d)"
                          % (ep + 1, acc, best_acc, best_ep))
            if verbose and Xv is None and (ep + 1) % 100 == 0:
                acc = float(((X @ W + b).argmax(axis=1) == Y).mean())
                print("  epoch %d | train acc %.4f" % (ep + 1, acc))

        clf = IntentClassifier(labels=uniq, W=best_W if Xv is not None else W,
                               b=best_b if Xv is not None else b)
        clf.best_epoch = best_ep
        clf.best_eval_acc = best_acc
        return clf

    # ------------------------------------------------------------ persistence
    def save(self, directory):
        os.makedirs(directory, exist_ok=True)
        np.savez_compressed(os.path.join(directory, "intent_weights.npz"),
                            W=self.W, b=self.b)
        with open(os.path.join(directory, "labels.json"), "w", encoding="utf-8") as f:
            json.dump(self.labels, f, ensure_ascii=False)

    @classmethod
    def load(cls, directory):
        try:
            data = np.load(os.path.join(directory, "intent_weights.npz"))
            with open(os.path.join(directory, "labels.json"), encoding="utf-8") as f:
                labels = json.load(f)
            return cls(labels=labels, W=data["W"], b=data["b"])
        except (FileNotFoundError, OSError):
            return cls()
