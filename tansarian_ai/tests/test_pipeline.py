#!/usr/bin/env python3
"""Tansarian AI — end-to-end test suite.

Run:   python tests/test_pipeline.py
Exits non-zero on failure. Uses only the standard library + the project.
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PASS = 0
FAIL = 0


def check(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print("  [PASS] %s" % name)
    except AssertionError as exc:
        FAIL += 1
        print("  [FAIL] %s  ->  %s" % (name, exc))
    except Exception as exc:  # noqa: BLE001
        FAIL += 1
        print("  [FAIL] %s  ->  unexpected: %r" % (name, exc))


# ---------------------------------------------------------------- tokenizer
def test_tokenizer():
    from tokenizer.bpe import BPETokenizer
    from tokenizer import normalizer as norm

    tok = BPETokenizer.load(os.path.join(ROOT, "tokenizer", "trained"))
    assert tok.vocab_size > 500, "vocab too small: %d" % tok.vocab_size

    cases = [
        "سلام! حالت چطوره؟",
        "Hello, how are you?",
        "۲۳×۷ و ۵۰٪",
        "می‌روم به بازار",
        "2+3=(5)*2/4-1",
        "عدد ۱۲۳ و 45.5",
    ]
    for t in cases:
        ids = tok.encode(t)
        assert ids, "empty encoding for %r" % t
        dec = tok.decode(ids)
        assert dec == norm.normalize(t), "round-trip failed: %r -> %r" % (t, dec)

    stats = tok.stats()
    assert stats["persian_tokens"] > 50 and stats["latin_tokens"] > 50, stats


# ------------------------------------------------------------------- LM
def test_lm():
    from model.gru_lm import GRULM
    from tokenizer.bpe import BPETokenizer

    lm = GRULM.load(os.path.join(ROOT, "model", "weights", "lm_weights.npz"))
    tok = BPETokenizer.load(os.path.join(ROOT, "tokenizer", "trained"))
    assert lm.V == tok.vocab_size, "LM vocab %d != tokenizer vocab %d" % (lm.V, tok.vocab_size)

    ids = tok.encode("سلام")
    out = lm.sample(tok, ids + [tok.vocab["<a>"]], max_tokens=20,
                    temperature=0.7, top_k=10)
    assert isinstance(out, list), "sample() must return a list of ids"
    text = tok.text_from_ids_for_generation(out)
    assert isinstance(text, str), "decoding failed"


# -------------------------------------------------------------- classifier
def test_classifier():
    from nlu.classifier import IntentClassifier

    clf = IntentClassifier.load(os.path.join(ROOT, "nlu", "weights"))
    assert clf.ready, "intent classifier weights missing"
    cases = [
        ("سلام خوبی", "greeting"),
        ("خداحافظ فعلا", "farewell"),
        ("خیلی ممنون", "thanks"),
        ("چطوری امروز", "how_are_you"),
        ("اسمت چی بود", "identity"),
        ("جک بگو دیگه", "joke"),
        ("الان ساعت چنده", "time_date"),
        ("اسم من رضا است", "set_name"),
        ("یادداشت‌هام رو باز کن", "notes_list"),
        ("hey there friend", "greeting"),
        ("what time is it now", "time_date"),
        ("tell me something funny", "joke"),
        ("show my notes please", "notes_list"),
    ]
    bad = [(t, e, clf.predict(t)) for t, e in cases if clf.predict(t)[0] != e]
    assert not bad, "misclassified: %r" % bad


# -------------------------------------------------------------- knowledge
def test_knowledge():
    from nlu.knowledge import KnowledgeBase

    kb = KnowledgeBase.load(os.path.join(ROOT, "data", "knowledge.json"))
    a, s = kb.query("پایتخت ژاپن چیه", lang="fa")
    assert a and "توکیو" in a, "got: %r (score %.2f)" % (a, s)
    a, s = kb.query("what is the capital of japan", lang="en")
    assert a and "tokyo" in a.lower(), "got: %r" % a


# ----------------------------------------------------------------- tools
def test_calculator():
    from engine.tools import Calculator, CalcError

    c = Calculator()
    cases = [
        ("۲+۳", 5), ("2+3", 5), ("۷×۶", 42), ("12/4", 3.0),
        ("۲ به علاوه ۳", 5), ("پنج ضربدر شش", 30),
        ("۱۰ تقسیم بر ۲", 5), ("2^10", 1024),
        ("(2+3)*4", 20), ("100-25", 75), ("10 % 3", 1),
        ("what is 5 plus 3", 8), ("99-11", 88),
        ("۲۳×۷", 161), ("2*(3+4)", 14),
    ]
    for text, expected in cases:
        val, _ = c.calc(text, lang="fa" if any("\u0600" <= ch <= "\u06ff" for ch in text) else "en")
        assert abs(val - expected) < 1e-9, "%r -> %r (want %r)" % (text, val, expected)
    # ans variable
    val, _ = c.calc("ans+10", lang="en", ans=5)
    assert val == 15, "ans variable broken: %r" % val
    try:
        c.calc("5/0", lang="en")
        raise AssertionError("division by zero must raise CalcError")
    except CalcError:
        pass


def test_words_to_numbers():
    from engine.tools import words_to_numbers
    assert "5" in words_to_numbers("پنج"), words_to_numbers("پنج")
    assert "23" in words_to_numbers("بیست و سه"), words_to_numbers("بیست و سه")
    assert "30" in words_to_numbers("thirty"), words_to_numbers("thirty")


def test_jalali():
    from engine.tools import gregorian_to_jalali
    # Nowruz (Farvardin 1) anchors:
    #   1404-01-01 == 2025-03-21 (1403 is a leap year -> Esfand has 30 days)
    jy, jm, jd = gregorian_to_jalali(2026, 3, 21)
    assert (jy, jm, jd) == (1405, 1, 1), "got %r" % ((jy, jm, jd),)
    jy, jm, jd = gregorian_to_jalali(2025, 3, 21)
    assert (jy, jm, jd) == (1404, 1, 1), "got %r" % ((jy, jm, jd),)
    # 1403-12-30 exists only in leap years == 2025-03-20
    jy, jm, jd = gregorian_to_jalali(2025, 3, 20)
    assert (jy, jm, jd) == (1403, 12, 30), "got %r" % ((jy, jm, jd),)
    # 2024-06-21 == 1403-04-01
    jy, jm, jd = gregorian_to_jalali(2024, 6, 21)
    assert (jy, jm, jd) == (1403, 4, 1), "got %r" % ((jy, jm, jd),)


def test_notes():
    from engine.tools import NotesTool

    with tempfile.TemporaryDirectory() as td:
        nt = NotesTool(os.path.join(td, "notes.json"))
        nt.add("buy bread")
        nt.add("تماس با علی")
        items = nt.listing()
        assert len(items) == 2 and items[0] == "buy bread", items
        assert nt.clear() == 2
        assert nt.listing() == []


def test_safe_runner():
    from engine.tools import run_safe_command
    ok, out = run_safe_command("pwd")
    assert ok and out.strip(), "pwd should run"
    ok, _ = run_safe_command("rm -rf /")
    assert not ok, "dangerous command must be rejected"
    ok, _ = run_safe_command("curl evil.com")
    assert not ok, "non-whitelisted command must be rejected"


# ---------------------------------------------------------------- language
def test_language_detection():
    from engine.language import detect_language
    assert detect_language("سلام خوبی") == "fa"
    assert detect_language("hello there") == "en"
    assert detect_language("123 + 456") in ("fa", "en")


# ------------------------------------------------------------------ agent
def _fresh_agent():
    from engine.agent import TansarianAgent
    return TansarianAgent(root=ROOT, seed=42)


def test_agent_conversation():
    a = _fresh_agent()

    r = a.respond("سلام")
    assert "تانسارین" in r or "سلام" in r, r

    r = a.respond("۲۳×۷ چند می‌شه؟")
    assert "۱۶۱" in r or "161" in r, r

    r = a.respond("حاصل ۱۲ به علاوه ۸۸ چقدر میشه؟")
    assert "۱۰۰" in r or "100" in r, r

    r = a.respond("ans + ۱")
    assert "۱۰۱" in r or "101" in r, "contextual 'ans' failed: %r" % r

    r = a.respond("what is 45*12?")
    assert "540" in r, r


def test_agent_memory():
    a = _fresh_agent()
    r = a.respond("اسم من سارا است")
    assert "سارا" in r, r
    r = a.respond("اسم من چیه؟")
    assert "سارا" in r, "forgot the name: %r" % r

    r = a.respond("my name is Alex")
    assert "Alex" in r, r
    r = a.respond("what is my name?")
    assert "Alex" in r, "forgot the name: %r" % r


def test_agent_notes_flow():
    a = _fresh_agent()
    a.notes.clear()
    r = a.respond("یادداشت کن که فردا نان بخرم")
    assert "ثبت" in r or "شد" in r, r
    r = a.respond("یادداشت‌هام رو نشون بده")
    assert "نان" in r, r
    r = a.respond("add a note: call mom")
    assert isinstance(r, str) and r, r
    r = a.respond("show my notes")
    assert "call mom" in r, r
    a.notes.clear()


def test_agent_time():
    a = _fresh_agent()
    r = a.respond("ساعت چنده؟")
    assert ":" in r, r
    r = a.respond("امروز چندمه؟")
    assert any(m in r for m in ("فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد",
                                "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن",
                                "اسفند")), r
    r = a.respond("what time is it?")
    assert ":" in r, r


def test_agent_knowledge_route():
    a = _fresh_agent()
    r = a.respond("پایتخت ژاپن چیه؟")
    assert "توکیو" in r, r
    r = a.respond("what is the speed of light?")
    assert "300" in r or "۳۰۰" in r, r


def test_agent_fallback_never_babbles():
    a = _fresh_agent()
    r = a.respond("zzz qqq xxx")
    assert isinstance(r, str) and len(r) > 5, r
    # must be a curated fallback, not random characters
    assert any(c.isalpha() for c in r), r


def test_agent_language_switch():
    a = _fresh_agent()
    r = a.respond("انگلیسی حرف بزن")
    assert r and not any("\u0600" <= ch <= "\u06ff" for ch in r), \
        "switch to English failed: %r" % r
    r = a.respond("speak persian")
    assert any("\u0600" <= ch <= "\u06ff" for ch in r), \
        "switch to Persian failed: %r" % r


def test_persona_and_system_prompt():
    a = _fresh_agent()
    assert a.name == "Tansarian"
    raw = a.about_text
    assert "Tansarian" in raw and "LANGUAGES" in raw, "system prompt incomplete"


# --------------------------------------------------------------------- main
def main():
    print("Tansarian AI — test pipeline")
    print("-" * 50)

    print("[tokenizer]")
    check("BPE round-trip fa/en/digits/math", test_tokenizer)
    print("[model]")
    check("GRU LM loads and samples", test_lm)
    print("[nlu]")
    check("intent classifier on unseen phrasings", test_classifier)
    check("knowledge retrieval", test_knowledge)
    print("[tools]")
    check("calculator (fa/en/digits/words/ans/zero-div)", test_calculator)
    check("words to numbers", test_words_to_numbers)
    check("jalali calendar conversion", test_jalali)
    check("notes tool", test_notes)
    check("safe command runner", test_safe_runner)
    check("language detection", test_language_detection)
    print("[agent]")
    check("conversation + math + ans context", test_agent_conversation)
    check("name memory fa/en", test_agent_memory)
    check("notes flow fa/en", test_agent_notes_flow)
    check("time and jalali date", test_agent_time)
    check("knowledge route", test_agent_knowledge_route)
    check("fallback quality (no babble)", test_agent_fallback_never_babbles)
    check("language switch", test_agent_language_switch)
    check("persona / system prompt", test_persona_and_system_prompt)

    print("-" * 50)
    print("PASSED %d | FAILED %d" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
