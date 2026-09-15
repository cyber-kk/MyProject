"""Language detection: Persian vs English by script, with memory fallback."""


def detect_language(text, default="fa"):
    """Return 'fa' if Persian script dominates, 'en' if Latin dominates,
    otherwise the default (usually the user's last language)."""
    fa = en = 0
    for ch in text:
        o = ord(ch)
        if 0x0600 <= o <= 0x06FF or 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF:
            fa += 1
        elif ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
            en += 1
    if fa == 0 and en == 0:
        return default
    return "fa" if fa >= en else "en"


def looks_like_persian(text):
    return detect_language(text, default="en") == "fa"
