"""Agent tools: calculator, date/time (incl. Jalali), notes, random, safe exec."""
import datetime
import json
import os
import re
import subprocess

from tokenizer import normalizer as norm

# --------------------------------------------------------------------------
# Calculator
# --------------------------------------------------------------------------

_FA_NUM_WORDS = {
    "صفر": 0, "یک": 1, "دو": 2, "سه": 3, "چهار": 4, "پنج": 5, "شش": 6,
    "هفت": 7, "هشت": 8, "نه": 9, "ده": 10, "یازده": 11, "دوازده": 12,
    "سیزده": 13, "چهارده": 14, "پانزده": 15, "پونزده": 15, "شانزده": 16,
    "هفده": 17, "هجده": 18, "نوزده": 19, "بیست": 20, "سی": 30, "چهل": 40,
    "پنجاه": 50, "شصت": 60, "هفتاد": 70, "هشتاد": 80, "نود": 90,
    "صد": 100, "دویست": 200, "سیصد": 300, "چهارصد": 400, "پانصد": 500,
    "ششصد": 600, "هفتصد": 700, "هشتصد": 800, "نهصد": 900, "هزار": 1000,
}
_EN_NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100, "thousand": 1000,
}
_FA_CONNECTIVE = "و"
_EN_CONNECTIVES = {"and"}

_FA_OPS = [
    (r"به\s*توان|توان", "**"),
    (r"ضرب\s*در|ضربدر|ضرب|در\s*ضرب", "*"),
    (r"تقسیم\s*بر|تقسیم", "/"),
    (r"به\s*علاوه|به\s*اضافه|بعلاوه|جمع", "+"),
    (r"منهای|منها|منهای", "-"),
    (r"باقی\s*مانده|باقیمانده|mod", "%"),
]
_EN_OPS = [
    (r"to\s+the\s+power\s+of|power\s+of|power|\*\*", "**"),
    (r"multiplied\s+by|times|multiply|x", "*"),
    (r"divided\s+by|divide\s+by|divide|over", "/"),
    (r"plus|add|added\s+to|\+", "+"),
    (r"minus|subtract|less", "-"),
    (r"mod(?:ulo)?", "%"),
]

_FA_NOISE = ["چنده", "چقدر", "میشه", "می‌شه", "میشود", "می‌شود", "حاصل",
             "حساب", "کن", "بگو", "بده", "چی", "چه", "است", "هست", "به",
             "چند", "مساوی", "برابر", "با", "نتیجه", "جواب", "قدر"]
_EN_NOISE = ["what", "is", "whats", "how", "much", "calculate", "calc",
             "compute", "equals", "equal", "result", "answer", "tell",
             "me", "the", "please", "does", "make", "give"]


def _compose_fa(tokens):
    """بیست و سه -> 23 ; دو هزار و سی -> 2030 ; صد و پنجاه -> 150"""
    total, current = 0, 0
    for p in tokens:
        v = _FA_NUM_WORDS.get(p)
        if v is None:
            return None
        if v == 1000:
            total += (current if current else 1) * 1000
            current = 0
        else:
            current += v
    return total + current


def _compose_en(tokens):
    """twenty five -> 25 ; one hundred twenty -> 120 ; two thousand five hundred -> 2500"""
    total, current = 0, 0
    for p in tokens:
        v = _EN_NUM_WORDS.get(p)
        if v is None:
            return None
        if v == 100:
            current = (current if current else 1) * 100
        elif v == 1000:
            total += (current if current else 1) * 1000
            current = 0
        else:
            current += v
    return total + current


def words_to_numbers(text):
    """Replace Persian/English number-word sequences with digits."""
    t = norm.normalize(text)

    fa_alt = "|".join(sorted(_FA_NUM_WORDS, key=len, reverse=True))
    fa_seq = re.compile(
        r"(?<![\w\u0600-\u06ff\u200c])"
        r"((?:%s)(?:\s+(?:%s|%s))+|(?:%s))"
        r"(?![\w\u0600-\u06ff\u200c])"
        % (fa_alt, fa_alt, _FA_CONNECTIVE, fa_alt))

    def fa_replace(m):
        seq = m.group(0)
        toks = [p for p in seq.split() if p != _FA_CONNECTIVE]
        val = _compose_fa(toks)
        return seq if val is None else str(val)

    t = fa_seq.sub(fa_replace, t)

    en_alt = "|".join(sorted(_EN_NUM_WORDS, key=len, reverse=True))
    en_seq = re.compile(
        r"\b(?:(?:%s)(?:\s+(?:(?:%s)|and))+|(?:%s))\b" % (en_alt, en_alt, en_alt),
        re.IGNORECASE)

    def en_replace(m):
        seq = m.group(0)
        toks = [p for p in seq.split() if p.lower() not in _EN_CONNECTIVES]
        val = _compose_en(toks)
        return seq if val is None else str(val)

    t = en_seq.sub(en_replace, t)
    return t
def _apply_word_ops(text, lang):
    ops = list(_FA_OPS if lang == "fa" else _EN_OPS)
    if lang == "fa":
        # also accept english ops in fa mode
        ops += _EN_OPS
    out = text
    for pat, sym in ops:
        out = re.sub(r"\s*(?:" + pat + r")\s*", " " + sym + " ", out, flags=re.IGNORECASE)
    return out


def clean_expression(text, lang="fa"):
    """Turn natural language math into a bare expression string."""
    t = words_to_numbers(text)
    t = t.replace("×", "*").replace("÷", "/").replace("−", "-")
    t = _apply_word_ops(t, lang)
    # standalone "و"/"and" between numbers is additive: ۴ و ۵ -> 4 + 5
    t = re.sub(r"(?<=\d)\s*(?:و|and)\s*(?=\d)", " + ", t, flags=re.IGNORECASE)
    # drop noise words
    noise = _FA_NOISE + _EN_NOISE
    for w in sorted(noise, key=len, reverse=True):
        t = re.sub(r"(?<![\w])" + re.escape(w) + r"(?![\w])", " ", t)
    t = t.replace("?", " ").replace("!", " ").replace(".", " ")
    t = t.replace("=", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t


class CalcError(Exception):
    pass


class Calculator:
    """Safe recursive-descent arithmetic evaluator."""

    _TOKEN_RE = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|(.))")

    def tokenize(self, expr):
        tokens = []
        for num, op in self._TOKEN_RE.findall(expr):
            if num:
                tokens.append(("num", float(num)))
            elif op.strip():
                tokens.append(("op", op))
        return tokens

    def evaluate(self, tokens, variables=None):
        variables = variables or {}
        pos = [0]

        def peek():
            return tokens[pos[0]] if pos[0] < len(tokens) else (None, None)

        def eat():
            tok = tokens[pos[0]]
            pos[0] += 1
            return tok

        def parse_expr():
            val = parse_term()
            while True:
                kind, v = peek()
                if kind == "op" and v in ("+", "-"):
                    eat()
                    rhs = parse_term()
                    val = val + rhs if v == "+" else val - rhs
                else:
                    return val

        def parse_term():
            val = parse_unary()
            while True:
                kind, v = peek()
                if kind == "op" and v in ("*", "/", "%"):
                    eat()
                    rhs = parse_unary()
                    if v == "*":
                        val *= rhs
                    elif v == "/":
                        if rhs == 0:
                            raise CalcError("div0")
                        val /= rhs
                    else:
                        if rhs == 0:
                            raise CalcError("div0")
                        val %= rhs
                else:
                    return val

        def parse_unary():
            kind, v = peek()
            if kind == "op" and v in ("+", "-"):
                eat()
                val = parse_unary()
                return val if v == "+" else -val
            return parse_pow()

        def parse_pow():
            base = parse_atom()
            kind, v = peek()
            if kind == "op" and v == "^":
                eat()
                exp = parse_unary()  # right-assoc, allows 2^-3
                return base ** exp
            return base

        def parse_atom():
            kind, v = peek()
            if kind == "num":
                eat()
                return v
            if kind == "op" and v == "(":
                eat()
                val = parse_expr()
                kind, v = peek()
                if kind == "op" and v == ")":
                    eat()
                    return val
                raise CalcError("paren")
            if kind == "op" and v.isalpha() and v in variables:
                eat()
                return float(variables[v])
            raise CalcError("atom")

        val = parse_expr()
        if pos[0] != len(tokens):
            raise CalcError("trail")
        if isinstance(val, complex):
            raise CalcError("complex")
        return val

    def calc(self, text, lang="fa", ans=None):
        """Returns (value, expression) or raises CalcError."""
        expr = clean_expression(text, lang)
        if ans is not None:
            expr = re.sub(r"\bans\b|\bجواب\b", "(%s)" % repr(ans), expr)
        expr = expr.replace(" ", "")
        if not expr or not re.search(r"\d", expr):
            raise CalcError("noexpr")
        if not re.search(r"[+\-*/%^]", expr):
            raise CalcError("noexpr")
        tokens = self.tokenize(expr)
        if len(tokens) < 3:
            raise CalcError("noexpr")
        val = self.evaluate(tokens)
        if abs(val - round(val)) < 1e-9 and abs(val) < 1e15:
            val = int(round(val))
        return val, expr


EXPR_HAS_MATH = re.compile(r"\d\s*[+\-*/%^×÷]|[+\-*/%^×÷]\s*\d|\d\s*×\s*\d")


def looks_like_math(text):
    t = norm.normalize(text)
    return bool(EXPR_HAS_MATH.search(t)) or bool(
        re.search(r"\d", t)) and bool(re.search(r"[+\-*/%^×÷]", t))


# --------------------------------------------------------------------------
# Date & time (Gregorian + Jalali)
# --------------------------------------------------------------------------

_FA_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
              "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
_FA_WEEKDAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه",
                "پنجشنبه", "جمعه"]


def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 \
        + (gy2 + 399) // 400 + gd + g_d_m[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


class DateTimeTool:
    def now_time(self, lang="fa"):
        now = datetime.datetime.now()
        t = now.strftime("%H:%M")
        if lang == "fa":
            return norm.to_persian_digits(t)
        return t

    def today(self, lang="fa"):
        now = datetime.datetime.now()
        if lang == "fa":
            jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
            weekday = _FA_WEEKDAYS[(now.weekday() + 2) % 7]
            date = norm.to_persian_digits("%d %s %d" % (jd, _FA_MONTHS[jm - 1], jy))
            return "%s، %s" % (weekday, date)
        return now.strftime("%A, %B %d, %Y")


# --------------------------------------------------------------------------
# Notes
# --------------------------------------------------------------------------

class NotesTool:
    def __init__(self, storage_path=None):
        if storage_path is None:
            base = os.path.join(os.path.expanduser("~"), ".tansarian")
            os.makedirs(base, exist_ok=True)
            storage_path = os.path.join(base, "notes.json")
        self.path = storage_path

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, OSError, ValueError):
            return []

    def _save(self, notes):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(notes, f, ensure_ascii=False, indent=1)

    def add(self, text):
        notes = self._load()
        notes.append({"text": text, "ts": datetime.datetime.now().isoformat(timespec="seconds")})
        self._save(notes)
        return len(notes)

    def listing(self):
        return [n["text"] for n in self._load()]

    def clear(self):
        n = len(self._load())
        self._save([])
        return n


# --------------------------------------------------------------------------
# Random
# --------------------------------------------------------------------------

class RandomTool:
    def __init__(self, rng):
        self.rng = rng

    def number(self, low=1, high=100):
        if low > high:
            low, high = high, low
        return int(self.rng.integers(low, high + 1))

    def dice(self, sides=6):
        return int(self.rng.integers(1, sides + 1))

    def coin(self, lang="fa"):
        if lang == "fa":
            return "شیر" if self.rng.integers(0, 2) else "خط"
        return "heads" if self.rng.integers(0, 2) else "tails"


# --------------------------------------------------------------------------
# Safe command runner (whitelist only)
# --------------------------------------------------------------------------

SAFE_COMMANDS = ["ls", "pwd", "uname", "whoami", "date", "uptime", "df", "echo"]


def run_safe_command(cmd):
    """Run a whitelisted, argument-free command. Returns (ok, output)."""
    cmd = (cmd or "").strip()
    parts = cmd.split()
    if not parts:
        return False, ""
    base = os.path.basename(parts[0])
    if base not in SAFE_COMMANDS or len(parts) > 3:
        return False, ""
    try:
        out = subprocess.run([base] + parts[1:], capture_output=True,
                             text=True, timeout=5)
        text = (out.stdout or "").strip()
        return out.returncode == 0, text[:600]
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
