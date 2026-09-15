"""Text normalization for Persian + English + digits + math symbols.

Handles:
- Persian (U+06F0-06F9) and Arabic-Indic (U+0660-0669) digits -> ASCII
- Arabic script variants -> Persian standard forms (ي->ی, ك->ک, ...)
- Diacritics / tatweel removal
- ZWNJ (U+200C) preservation (essential for Persian: می‌روم)
- Latin lowercasing, whitespace collapsing
- Persian punctuation folding (؟ -> ?, ، -> ,, ؛ -> ;, ٪ -> %)
"""


PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
ASCII_DIGITS = "0123456789"

_DIGIT_MAP = {}
for _i, _ch in enumerate(PERSIAN_DIGITS):
    _DIGIT_MAP[_ch] = str(_i)
for _i, _ch in enumerate(ARABIC_DIGITS):
    _DIGIT_MAP[_ch] = str(_i)

_CHAR_MAP = {
    # Arabic -> Persian letter forms
    "ي": "ی", "ك": "ک", "ة": "ه", "أ": "ا", "إ": "ا", "ٱ": "ا",
    "ؤ": "و", "ئ": "ی", "ى": "ی", "ﮐ": "ک", "ﮑ": "ک", "ﯽ": "ی",
    "ﯼ": "ی", "ﯾ": "ی", "ﮮ": "ک", "ﮤ": "ه", "ﮫ": "ه", "ۀ": "ه",
    "ہ": "ه", "ھ": "ه", "ہ": "ه", "ے": "ی", "ﺁ": "آ", "ﺃ": "أ",
    "ﺏ": "ب", "ﭘ": "پ", "ﺕ": "ت", "ﺝ": "ج", "ﭺ": "چ", "ﺩ": "د",
    "ﺵ": "ش", "ﻑ": "ف", "ﻕ": "ق", "ﻙ": "ک", "ﮒ": "گ", "ﻝ": "ل",
    "ﻡ": "م", "ﻥ": "ن", "ﻭ": "و", "ﻩ": "ه", "ﻱ": "ی", "ﻯ": "ی",
    # presentation forms cleanup
    "\u200f": "",  # RLM
    "\u200e": "",  # LRM
    "\u202b": "",
    "\u202c": "",
    "\ufeff": "",
}

# Arabic diacritics + marks
_STRIP_CHARS = set()
for _cp in list(range(0x064B, 0x0653)) + [0x0670] + list(range(0x06D6, 0x06EE)) + [0x0640, 0x0653, 0x0654, 0x0655]:
    _STRIP_CHARS.add(chr(_cp))

_PUNCT_MAP = {
    "؟": "?", "،": ",", "؛": ";", "٪": "%",
    "٬": ",", "٫": ".",
}

MATH_SYMBOLS = set("+-*/=^%()<>×÷±")


def to_ascii_digits(text):
    """Persian/Arabic digits -> ASCII digits."""
    return "".join(_DIGIT_MAP.get(ch, ch) for ch in text)


def to_persian_digits(text):
    """ASCII digits -> Persian digits (for display)."""
    table = str.maketrans(ASCII_DIGITS, PERSIAN_DIGITS)
    return text.translate(table)


def normalize(text, keep_zwnj=True):
    """Canonical form used everywhere (NLU features, tokenizer input)."""
    if text is None:
        return ""
    out = []
    for ch in text:
        if ch in _STRIP_CHARS:
            continue
        if ch == "\u200c":
            if keep_zwnj:
                out.append("\u200c")
            continue
        ch = _DIGIT_MAP.get(ch, ch)
        ch = _CHAR_MAP.get(ch, ch)
        ch = _PUNCT_MAP.get(ch, ch)
        out.append(ch)
    text = "".join(out)
    text = text.lower()
    # collapse whitespace
    text = " ".join(text.split())
    return text.strip()


def is_letter_char(ch):
    """Letters we consider part of a word (Latin, Persian, ZWNJ, apostrophe)."""
    if ch.isalpha():
        return True
    if ch == "\u200c":
        return True
    if ch in "'’":
        return True
    return False


def is_digit_char(ch):
    return ch in ASCII_DIGITS or ch in _DIGIT_MAP
