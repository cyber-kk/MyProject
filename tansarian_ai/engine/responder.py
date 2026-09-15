"""Response assembly: variant picking, template filling, formatting."""
import random
import re

from tokenizer import normalizer as norm
from engine import tools


class Responder:
    def __init__(self, memory, seed=None):
        self.memory = memory
        self.rng = random.Random(seed)

    def say(self, intent, responses, lang, **kw):
        """Pick a response variant for the language, fill {placeholders}."""
        pool = None
        if isinstance(responses, dict):
            pool = responses.get(lang) or responses.get("en") or responses.get("fa")
        elif isinstance(responses, (list, tuple)):
            pool = list(responses)
        if not pool:
            return ""
        text = self.memory.pick_variant(intent, pool, self.rng)
        try:
            return text.format(**kw) if kw else text
        except (KeyError, IndexError):
            return text

    # -------------------------------------------------------------- formatting
    @staticmethod
    def format_number(value, lang="fa"):
        if isinstance(value, float) and value == int(value):
            value = int(value)
        if isinstance(value, int):
            s = str(value)
        else:
            s = ("%g" % value)
        return norm.to_persian_digits(s) if lang == "fa" else s

    @staticmethod
    def notes_list(notes, lang="fa"):
        lines = []
        for i, n in enumerate(notes, 1):
            text = n if len(n) <= 80 else n[:77] + "..."
            prefix = norm.to_persian_digits(str(i)) if lang == "fa" else str(i)
            lines.append("%s. %s" % (prefix, text))
        return "\n".join(lines)

    @staticmethod
    def command_output(ok, output, lang="fa"):
        if not ok:
            if lang == "fa":
                return "اجرا کردنش ممکن نشد."
            return "Could not run that command."
        if not output:
            if lang == "fa":
                return "اجرا شد! خروجی‌ای نداشت."
            return "Done! No output."
        return output


class IntentExtractor:
    """Slot/entity extraction helpers."""

    # high-precision fast routes (checked before statistical classification)
    FAST_NAME_GIVE = [
        r"my name is\s+(.+)$", r"^my names\s+(.+)$", r"^call me\s+(.+)$",
        r"^i am called\s+(.+)$",
        r"^(?:اسم من|اسمم|نام من|نامم)\s+(.{1,24}?)\s*(?:هست|است|هستانه|یه|می‌باشد)?$",
        r"^من\s+(.{1,24}?)\s+هستم$", r"^(?:صدام کن|به من بگو)\s+(.{1,24})$",
    ]
    FAST_NAME_ASK = [
        r"(?:what'?s|what is|do you know|do you remember|say|recall)\s+my name",
        r"^who am i\??$",
        r"اسم\s*(?:من|منو)\s*(?:چیه|چی بود|چی بود|چی شده|چیست)",
        r"منو\s+می‌شناسی", r"اسم منو\s+(?:یادته|بلدی)", r"یادته من کی هستم",
    ]
    FAST_NOTE_ADD = [
        r"^(?:add|take|make|write|save|keep)\s+(?:a\s+)?note(?:\s+down)?[\s:,-]*(.+)$",
        r"^new note[\s:,-]*(.+)$", r"^note(?:\s+down)?[\s:,-](.+)$",
        r"^(?:یادداشت کن که|یک یادداشت ثبت کن|این رو یادداشت کن|برام یادداشت بنویس|ذخیره کن یادداشت|یادداشت کن|یادداشت جدید)[\s:،,-]*(.+)$",
    ]
    FAST_NOTE_LIST = [
        r"^(?:show|list|see|view|read|open)\s+(?:my\s+)?notes?\b",
        r"^(?:what|which)\s+(?:notes?|did i note)",
        r"یادداشت(?:\s*ها|\s*هام|\s*هاام)?\s*(?:رو|را)?\s*(?:نشون|نمایش|بخون|لیست|باز)",
        r"^(?:لیست|نمایش|نشان)\s+(?:یادداشت|نوت)", r"^چیا یادداشت", r"^چه یادداشت",
    ]
    FAST_NOTE_CLEAR = [
        r"^(?:clear|delete|remove|wipe|empty)\s+(?:all\s+)?(?:my\s+)?notes?\b",
        r"یادداشت(?:\s*ها|\s*هام)?\s*(?:رو|را)?\s*(?:پاک|حذف|خالی)",
        r"^(?:پاک کردن|حذف)\s+(?:یادداشت|نوت)", r"همه\s+(?:نوت|یادداشت)\s*ها?\s*(?:پاک|حذف)",
    ]
    FAST_GENERATE = [
        r"^say something\b", r"^say a sentence", r"^generate (?:a )?text", r"^talk to me\b",
        r"یه چیزی بگو", r"یه جمله بگو", r"چیزی بگو", r"یه متن بگو", r"یه حرفی بزن",
    ]

    @classmethod
    def fast_intent(cls, text):
        """Deterministic routing for slot-carrying commands.

        Returns (intent, slot) or (None, None). Order matters: questions
        about the name must be checked before name-giving patterns."""
        t = norm.normalize(text)
        if not t:
            return None, None
        for pat in cls.FAST_NOTE_CLEAR:
            if re.search(pat, t, re.IGNORECASE):
                return "notes_clear", None
        for pat in cls.FAST_NOTE_LIST:
            if re.search(pat, t, re.IGNORECASE):
                return "notes_list", None
        for pat in cls.FAST_NOTE_ADD:
            m = re.search(pat, t, re.IGNORECASE)
            if m:
                return "notes_add", (m.group(1).strip() if m.groups() and m.group(1) else None)
        for pat in cls.FAST_NAME_ASK:
            if re.search(pat, t, re.IGNORECASE):
                return "get_name", None
        for pat in cls.FAST_NAME_GIVE:
            m = re.search(pat, t, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                name = " ".join(w for w in name.split()
                                if w not in ("هست", "است", "هستانه", "می‌باشد"))
                if 1 <= len(name) <= 24 and cls._valid_name(name):
                    return "set_name", name
        for pat in cls.FAST_GENERATE:
            if re.search(pat, t, re.IGNORECASE):
                return "freeform_generate", None
        return None, None

    @staticmethod
    def _valid_name(name):
        """Reject question words / punctuation masquerading as a name."""
        if any(ch in name for ch in "؟?!,.؛;:"):
            return False
        bad = ("چی", "چیه", "کیه", "کی", "چند", "کدام", "چرا", "کجا", "what", "who",
               "how", "why", "when", "where", "is", "are")
        words = name.lower().split()
        return not any(w in bad for w in words)


    @staticmethod
    def extract_name(text):
        t = norm.normalize(text)
        patterns = [
            r"(?:اسم من|اسمم|نام من|نامم)\s+(?:چیزی|)[-−]?\s*([a-z\u0600-\u06ff\u200c]+(?:\s+[a-z\u0600-\u06ff\u200c]+)?)\s*(?:هست|است|هستانه|یه|می‌باشد)?$",
            r"^(?:من)\s+([a-z\u0600-\u06ff\u200c]+)\s+هستم$",
            r"(?:صدام کن|به من بگو)\s+([a-z\u0600-\u06ff\u200c]+)",
            r"my name is\s+([a-z]+(?:\s+[a-z]+)?)",
            r"^name is\s+([a-z]+)",
            r"^call me\s+([a-z]+)",
            r"^i\s*'?m\s+([a-z]+)$",
            r"^i am\s+([a-z]+)$",
        ]
        for pat in patterns:
            m = re.search(pat, t)
            if m:
                name = m.group(1).strip()
                name = " ".join(w for w in name.split() if w not in ("هست", "است", "هستانه"))
                if 1 <= len(name) <= 24:
                    return name
        return None

    @staticmethod
    def extract_language_target(text):
        t = norm.normalize(text)
        if any(w in t for w in ("انگلیسی", "english")):
            return "en"
        if any(w in t for w in ("فارسی", "farsi", "persian")):
            return "fa"
        return None

    @staticmethod
    def extract_note_text(text):
        t = text.strip()
        pats = [
            r"^(?:یادداشت کن که|یادداشت کن|این رو یادداشت کن|یک یادداشت ثبت کن:|یادداشت:)\s*(.+)$",
            r"^(?:add a note|take a note|make a note|new note|write a note)[\s:,-]*(.+)$",
            r"^(?:note down|remember this note)[\s:,-]*(.+)$",
        ]
        for pat in pats:
            m = re.search(pat, t, re.IGNORECASE)
            if m and m.group(1).strip():
                return m.group(1).strip()
        return None

    @staticmethod
    def extract_command(text):
        m = re.search(r"(?:اجرا کن|اجرا کنید|execute|run)\s+([a-z0-9.\-]+(?:\s+[a-z0-9.\-]+){0,2})",
                      norm.normalize(text), re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return None

    @staticmethod
    def extract_random_bounds(text):
        t = norm.normalize(text)
        m = re.search(r"(?:بین|between|from)\s+(\d+)\s+(?:و|تا|and|to)\s+(\d+)", t)
        if m:
            low, high = int(m.group(1)), int(m.group(2))
            return low, high
        return None

    @staticmethod
    def random_kind(text):
        t = norm.normalize(text)
        if any(w in t for w in ("تاس", "dice", "dice roll", "roll")):
            return "dice"
        if any(w in t for w in ("شیر یا خط", "سکه", "coin", "heads or tails", "flip")):
            return "coin"
        return "number"

