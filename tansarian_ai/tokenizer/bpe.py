"""Byte-pair-encoding style subword tokenizer for Persian + English + numbers.

- Pre-tokenizes text into word / number / punctuation / space chunks
- Learns BPE merges inside word chunks
- Knows special tokens: <pad> <unk> <bos> <eos> <u> <a>
- Persists vocab.json + merges.json so the trained state ships with the project
"""
import json
import os
from collections import Counter

from . import normalizer as norm

SPECIALS = ["<pad>", "<unk>", "<bos>", "<eos>", "<u>", "<a>"]
PAD, UNK, BOS, EOS, U_TOK, A_TOK = SPECIALS

DEFAULT_VOCAB_SIZE = 3200


def pretokenize(text):
    """Split raw (already normalized) text into chunks.

    Returns list of chunk strings. Words keep letters+ZWNJ together,
    numbers keep digits together, every other char stands alone, spaces
    become explicit ' ' chunks (so decode is exact).
    """
    chunks = []
    buf = []
    buf_kind = None  # 'w' word, 'd' digit

    def flush():
        nonlocal buf, buf_kind
        if buf:
            chunks.append("".join(buf))
            buf = []
            buf_kind = None

    for ch in text:
        if ch == " ":
            flush()
            chunks.append(" ")
        elif norm.is_digit_char(ch):
            flush()
            chunks.append(ch)
        elif norm.is_letter_char(ch):
            buf.append(ch)
            buf_kind = "w"
        else:
            flush()
            chunks.append(ch)
    flush()
    return chunks


class BPETokenizer:
    def __init__(self, vocab=None, merges=None):
        self.vocab = vocab or {}
        self.inv_vocab = {i: t for t, i in self.vocab.items()} if self.vocab else {}
        self.merges = merges or []
        self.ranks = {tuple(m): i for i, m in enumerate(self.merges)}
        self._cache = {}

    # ------------------------------------------------------------------ train
    @staticmethod
    def train(corpus_text, vocab_size=DEFAULT_VOCAB_SIZE, min_freq=2, verbose=False):
        # word frequency over chunks that participate in BPE (words + digits)
        chunk_freq = Counter()
        for line in corpus_text.split("\n"):
            line = norm.normalize(line)
            if not line:
                continue
            for ch in pretokenize(line):
                if len(ch) > 1:
                    chunk_freq[ch] += 1

        # initial alphabet from all chunks + single chars of corpus
        words = {tuple(w): f for w, f in chunk_freq.items()}
        alphabet = Counter()
        for w in words:
            for s in w:
                alphabet[s] += 1
        for line in corpus_text.split("\n"):
            for ch in norm.normalize(line):
                if ch and ch != " ":
                    alphabet[ch] += 1
                elif ch == " ":
                    alphabet[" "] += 1

        merges = []
        target = max(0, vocab_size - len(SPECIALS) - len(alphabet))
        for step in range(int(target)):
            pairs = Counter()
            for w, f in words.items():
                if len(w) < 2 or f < min_freq:
                    continue
                for i in range(len(w) - 1):
                    pairs[(w[i], w[i + 1])] += f
            if not pairs:
                break
            best, best_f = None, 0
            for p, f in pairs.items():
                if f > best_f:
                    best, best_f = p, f
            if best is None or best_f < min_freq:
                break
            a, b = best
            new_sym = a + b
            merges.append([a, b])
            new_words = {}
            for w, f in words.items():
                nw = []
                i = 0
                while i < len(w):
                    if i < len(w) - 1 and w[i] == a and w[i + 1] == b:
                        nw.append(new_sym)
                        i += 2
                    else:
                        nw.append(w[i])
                        i += 1
                new_words[tuple(nw)] = new_words.get(tuple(nw), 0) + f
            words = new_words
            if verbose and (step + 1) % 200 == 0:
                print("  merge %5d: %s+%s (freq %d)" % (step + 1, a, b, best_f))

        vocab = {t: i for i, t in enumerate(SPECIALS)}
        for ch in sorted(alphabet):
            if ch not in vocab:
                vocab[ch] = len(vocab)
        for m in merges:
            tok = m[0] + m[1]
            if tok not in vocab:
                vocab[tok] = len(vocab)

        tok = BPETokenizer(vocab=vocab, merges=merges)
        return tok

    # ----------------------------------------------------------------- encode
    def _encode_chunk(self, chunk):
        if chunk in self._cache:
            return self._cache[chunk]
        if chunk in self.vocab:  # whole chunk is one token (single char etc.)
            ids = [self.vocab[chunk]]
        else:
            syms = list(chunk)
            while len(syms) > 1:
                best_rank, best_i = None, None
                for i in range(len(syms) - 1):
                    r = self.ranks.get((syms[i], syms[i + 1]))
                    if r is not None and (best_rank is None or r < best_rank):
                        best_rank, best_i = r, i
                if best_rank is None:
                    break
                a, b = syms[best_i], syms[best_i + 1]
                syms = syms[:best_i] + [a + b] + syms[best_i + 2:]
            ids = [self.vocab.get(s, self.vocab.get(UNK)) for s in syms]
        self._cache[chunk] = ids
        return ids

    def encode(self, text, add_eos=False, add_bos=False):
        ids = []
        if add_bos:
            ids.append(self.vocab[BOS])
        for ch in pretokenize(norm.normalize(text)):
            ids.extend(self._encode_chunk(ch))
        if add_eos:
            ids.append(self.vocab[EOS])
        return ids

    def encode_line(self, line):
        """Encode a corpus line that starts with a <u>/<a> marker."""
        line = line.strip()
        marker = None
        for m in (U_TOK, A_TOK):
            if line.startswith(m):
                marker = m
                line = line[len(m):].strip()
                break
        ids = []
        if marker:
            ids.append(self.vocab[marker])
        ids.extend(self.encode(line))
        ids.append(self.vocab[EOS])
        return ids

    # ----------------------------------------------------------------- decode
    def decode(self, ids):
        out = []
        for i in ids:
            t = self.inv_vocab.get(int(i))
            if t is None:
                continue
            if t in (PAD,):
                continue
            if t in (EOS, BOS, U_TOK, A_TOK):
                out.append("\n")
                continue
            out.append(t)
        return "".join(out)

    def text_from_ids_for_generation(self, ids):
        """Decode generated ids (without marker newline handling)."""
        out = []
        for i in ids:
            t = self.inv_vocab.get(int(i))
            if t is None or t == PAD:
                continue
            if t in (EOS, BOS, U_TOK, A_TOK):
                break
            out.append(t)
        return "".join(out).strip()

    # ------------------------------------------------------------ persistence
    def save(self, directory):
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "vocab.json"), "w", encoding="utf-8") as f:
            json.dump(self.vocab, f, ensure_ascii=False, indent=0)
        with open(os.path.join(directory, "merges.json"), "w", encoding="utf-8") as f:
            json.dump(self.merges, f, ensure_ascii=False)

    @classmethod
    def load(cls, directory):
        with open(os.path.join(directory, "vocab.json"), encoding="utf-8") as f:
            vocab = json.load(f)
        merges = []
        mpath = os.path.join(directory, "merges.json")
        if os.path.exists(mpath):
            with open(mpath, encoding="utf-8") as f:
                merges = json.load(f)
        return cls(vocab=vocab, merges=merges)

    # ------------------------------------------------------------------ utils
    @property
    def vocab_size(self):
        return len(self.vocab)

    def token_id(self, token):
        return self.vocab.get(token, self.vocab.get(UNK))

    def stats(self):
        n_persian = sum(1 for t in self.vocab if any("\u0600" <= c <= "\u06ff" for c in t))
        n_latin = sum(1 for t in self.vocab if t.isascii() and any(c.isalpha() for c in t))
        return {
            "vocab_size": self.vocab_size,
            "merges": len(self.merges),
            "persian_tokens": n_persian,
            "latin_tokens": n_latin,
        }
