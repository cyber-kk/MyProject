"""Builds the LM training corpus from intents + knowledge + prose.

Corpus format: one utterance per line, prefixed with a speaker marker:
    <u> user utterance
    <a> assistant utterance
The markers become real vocabulary tokens, so the language model learns
the dialogue structure as well as the language itself.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# placeholder values used ONLY for corpus generation so the LM never sees "{...}"
_FILL = {
    "{name}": "سارا",
    "{result}": "۴۲",
    "{time}": "۱۰:۳۰",
    "{allowed}": "ls, pwd, uname, whoami, date",
}


def _fill(text):
    for k, v in _FILL.items():
        text = text.replace(k, v)
    return text


def build_corpus(out_path=None):
    if out_path is None:
        out_path = os.path.join(HERE, "corpus.txt")

    with open(os.path.join(HERE, "intents.json"), encoding="utf-8") as f:
        intents = json.load(f)
    with open(os.path.join(HERE, "knowledge.json"), encoding="utf-8") as f:
        knowledge = json.load(f)

    lines = []

    for it in intents["intents"]:
        for lang in ("fa", "en"):
            for p in it.get("patterns", {}).get(lang, []):
                lines.append("<u> " + _fill(p))
            for r in it.get("responses", {}).get(lang, []):
                lines.append("<a> " + _fill(r))
            fb = it.get("fallback", {})
            for r in fb.get(lang, []):
                lines.append("<a> " + _fill(r))

    for e in knowledge["entries"]:
        for lang in ("fa", "en"):
            side = e.get(lang, {})
            for q in side.get("q", []):
                lines.append("<u> " + _fill(q))
            if side.get("a"):
                lines.append("<a> " + _fill(side["a"]))

    prose_path = os.path.join(HERE, "extra_prose.txt")
    if os.path.exists(prose_path):
        with open(prose_path, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if raw:
                    lines.append(raw)

    # de-duplicate while keeping order
    seen = set()
    unique = []
    for ln in lines:
        if ln not in seen:
            seen.add(ln)
            unique.append(ln)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(unique) + "\n")

    return out_path, len(unique)


if __name__ == "__main__":
    path, n = build_corpus()
    print("corpus written:", path, "| lines:", n)
