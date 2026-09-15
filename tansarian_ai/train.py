#!/usr/bin/env python3
"""Tansarian AI — full training pipeline.

Trains (in order):
  1. the corpus            (data/build_corpus.py)
  2. the BPE tokenizer     (tokenizer/trained/)
  3. the GRU language model (model/weights/lm_weights.npz)
  4. the intent classifier (nlu/weights/)

Usage:
    python train.py                 # train everything with defaults
    python train.py --skip-lm       # only tokenizer + intent classifier
    python train.py --epochs-lm 60  # custom LM epochs
    python train.py --quick         # tiny smoke train (for CI / checks)
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from data.build_corpus import build_corpus  # noqa: E402
from tokenizer.bpe import BPETokenizer  # noqa: E402
from model.gru_lm import GRULM, train_lm  # noqa: E402
from nlu.classifier import IntentClassifier  # noqa: E402


def train_tokenizer(quick=False):
    print("== [1/4] corpus ==")
    path, n = build_corpus(os.path.join(ROOT, "data", "corpus.txt"))
    print("   corpus: %d lines at %s" % (n, path))

    print("== [2/4] BPE tokenizer ==")
    with open(path, encoding="utf-8") as f:
        corpus = f.read()
    vocab_size = 600 if quick else 3200
    tok = BPETokenizer.train(corpus, vocab_size=vocab_size, verbose=False)
    tok.save(os.path.join(ROOT, "tokenizer", "trained"))
    print("   trained:", tok.stats())
    return tok


def train_language_model(tok, quick=False, epochs=None):
    print("== [3/4] GRU language model ==")
    t0 = time.time()
    lines = [ln.strip() for ln in open(os.path.join(ROOT, "data", "corpus.txt"),
                                       encoding="utf-8") if ln.strip()]
    stream = []
    eos = tok.vocab["<eos>"]
    for ln in lines:
        stream.extend(tok.encode_line(ln))
    data = np.array(stream, dtype=np.int64)
    print("   token stream: %d tokens | vocab %d" % (len(data), tok.vocab_size))

    if quick:
        epochs = epochs or 3
        model = GRULM(vocab_size=tok.vocab_size, embed_dim=32, hidden_dim=64, seed=7)
        loss = train_lm(model, data, epochs=epochs, batch_size=8, seq_len=32,
                        lr=3e-3, log_every=0)
    else:
        epochs = epochs or 60
        model = GRULM(vocab_size=tok.vocab_size, embed_dim=96, hidden_dim=192, seed=7)
        loss = train_lm(model, data, epochs=epochs, batch_size=16, seq_len=48,
                        lr=2.5e-3, log_every=150)
    out = os.path.join(ROOT, "model", "weights", "lm_weights.npz")
    model.save(out)
    print("   final loss %.4f (ppl %.2f) in %.1fs -> %s"
          % (loss, float(np.exp(min(20.0, loss))), time.time() - t0, out))
    return model, loss


def _augment(samples, labels, rng, copies=4):
    """Data augmentation for robustness to new phrasings."""
    fa_prefix = ["لطفا", "خب", "بگو", "می‌شه بگی", "سلام،"]
    en_prefix = ["please", "hey", "so", "can you tell me,", "ok,"]
    fa_suffix = ["لطفا", "ممنون", "دستیار جان", "?", "؟"]
    en_suffix = ["please", "thanks", "?", "now"]
    fa_digits = "۰۱۲۳۴۵۶۷۸۹"
    en_digits = "0123456789"

    new_s, new_l = [], []
    for s, l in zip(samples, labels):
        new_s.append(s)
        new_l.append(l)
        for _ in range(copies):
            t = s
            mode = rng.integers(0, 4)
            if mode == 0:  # prefix
                pre = fa_prefix[rng.integers(0, len(fa_prefix))] \
                    if any("\u0600" <= c <= "\u06ff" for c in s) \
                    else en_prefix[rng.integers(0, len(en_prefix))]
                t = pre + " " + s
            elif mode == 1:  # suffix
                suf = fa_suffix[rng.integers(0, len(fa_suffix))] \
                    if any("\u0600" <= c <= "\u06ff" for c in s) \
                    else en_suffix[rng.integers(0, len(en_suffix))]
                t = s + " " + suf
            elif mode == 2:  # digit style swap
                t = "".join(fa_digits[en_digits.index(c)] if c in en_digits else c
                            for c in s)
            else:  # word dropout (only if 3+ words)
                words = t.split()
                if len(words) >= 3:
                    drop = rng.integers(0, len(words))
                    t = " ".join(words[:drop] + words[drop + 1:])
            if t and t.strip() != s:
                new_s.append(t.strip())
                new_l.append(l)
    order = rng.permutation(len(new_s))
    return [new_s[i] for i in order], [new_l[i] for i in order]


def train_intent_classifier(quick=False):
    print("== [4/4] intent classifier ==")
    with open(os.path.join(ROOT, "data", "intents.json"), encoding="utf-8") as f:
        import json
        intents = json.load(f)
    samples, labels = [], []
    for it in intents["intents"]:
        for lang in ("fa", "en"):
            for p in it.get("patterns", {}).get(lang, []):
                samples.append(p)
                labels.append(it["name"])
    rng = np.random.default_rng(11)
    order = rng.permutation(len(samples))
    samples = [samples[i] for i in order]
    labels = [labels[i] for i in order]

    split = max(1, int(len(samples) * 0.85))
    if quick:
        epochs = 60
        aug_copies = 1
    else:
        epochs = 300
        aug_copies = 5

    # evaluation on HELD-OUT ORIGINAL patterns (no augmentation), early stopping
    val_s, val_l = samples[split:], labels[split:]
    aug_train, aug_labels = _augment(samples[:split], labels[:split], rng, copies=aug_copies)
    clf = IntentClassifier.train(aug_train, aug_labels, epochs=epochs, l2=3e-4,
                                 eval_samples=val_s, eval_labels=val_l,
                                 eval_every=10, verbose=False)
    best_acc = getattr(clf, "best_eval_acc", 0.0)
    best_ep = getattr(clf, "best_epoch", 0)
    total = max(1, len(val_s))
    print("   train samples %d (augmented from %d) | best held-out acc %.3f @ epoch %d"
          % (len(aug_train), split, best_acc, best_ep))

    # final model: train on ALL patterns (+augmentation) for best_epoch epochs
    if not quick:
        all_aug, all_labels = _augment(samples, labels, rng, copies=aug_copies)
        final_ep = max(30, best_ep * 12 // 10)  # 20% more data -> a bit more training
        clf = IntentClassifier.train(all_aug, all_labels, epochs=final_ep, l2=3e-4,
                                     verbose=False)
        ok = 0
        for s, l in zip(samples, labels):
            pred, _ = clf.predict(s)
            ok += int(pred == l)
        print("   final model trained %d epochs | full-data fit %.3f" % (final_ep, ok / len(samples)))
    clf.save(os.path.join(ROOT, "nlu", "weights"))
    print("   weights saved to nlu/weights/")
    return clf, best_acc


def main():
    ap = argparse.ArgumentParser(description="Train Tansarian AI components")
    ap.add_argument("--skip-lm", action="store_true", help="skip language model training")
    ap.add_argument("--skip-intent", action="store_true", help="skip intent classifier")
    ap.add_argument("--epochs-lm", type=int, default=None)
    ap.add_argument("--quick", action="store_true", help="fast smoke training")
    args = ap.parse_args()

    print("Tansarian AI training pipeline")
    print("-" * 46)
    tok = train_tokenizer(quick=args.quick)
    if not args.skip_lm:
        _, loss = train_language_model(tok, quick=args.quick, epochs=args.epochs_lm)
        if not args.quick and loss > 2.5:
            print("   WARNING: LM loss looks high (%.3f)" % loss)
    if not args.skip_intent:
        clf, acc = train_intent_classifier(quick=args.quick)
        if not args.quick and acc < 0.60:
            print("   WARNING: intent accuracy low (%.3f)" % acc)
    print("-" * 46)
    print("Done. Start chatting:  python chat.py   (or ./tansarian)")


if __name__ == "__main__":
    main()
