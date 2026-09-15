"""TansarianAgent: the conversational agent that ties NLU, tools, memory,
the neural language model and the persona together."""
import json
import os
import re

import numpy as np

from tokenizer.bpe import BPETokenizer
from tokenizer import normalizer as norm
from model.gru_lm import GRULM
from nlu.classifier import IntentClassifier
from nlu.knowledge import KnowledgeBase, ResponseBank
from engine import tools
from engine.language import detect_language
from engine.memory import ConversationMemory
from engine.responder import Responder, IntentExtractor

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)


class TansarianAgent:
    def __init__(self, root=PROJECT_ROOT, config=None, seed=None):
        self.root = root
        self.rng = np.random.default_rng(seed)
        self.config = self._load_config(config)
        self.persona = self._load_system_prompt()
        self.memory = ConversationMemory()
        self.responder = Responder(self.memory, seed=seed if seed is not None else None)
        self.extractor = IntentExtractor()

        self.tokenizer = BPETokenizer.load(os.path.join(root, "tokenizer", "trained"))
        self.classifier = IntentClassifier.load(os.path.join(root, "nlu", "weights"))
        self.knowledge = KnowledgeBase.load(os.path.join(root, "data", "knowledge.json"))
        self.response_bank = ResponseBank.load(os.path.join(root, "data", "corpus.txt"))
        self.intents = self._load_intents()

        self.lm = None
        lm_path = os.path.join(root, "model", "weights", "lm_weights.npz")
        if os.path.exists(lm_path):
            self.lm = GRULM.load(lm_path)

        self.calc = tools.Calculator()
        self.clock = tools.DateTimeTool()
        self.notes = tools.NotesTool()
        self.random_tool = tools.RandomTool(self.rng)

        self.fallbacks = self.intents.get("fallback_responses", {})
        self.name = self.config.get("name", "Tansarian")
        # exact-match table: normalized pattern -> intent (handles short inputs like "hi")
        self._exact = {}
        for it in self.intents.get("intents", []):
            for lang in ("fa", "en"):
                for p in it.get("patterns", {}).get(lang, []):
                    key = norm.normalize(p)
                    if key and key not in self._exact:
                        self._exact[key] = it["name"]

    # ------------------------------------------------------------- loading
    def _load_config(self, config):
        if config is not None:
            return config
        path = os.path.join(self.root, "config.json")
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"name": "Tansarian", "default_language": "fa"}

    def _load_system_prompt(self):
        path = os.path.join(self.root, "prompts", "system.txt")
        persona = {"name": self.config.get("name", "Tansarian"),
                   "languages": "fa,en", "tone": "friendly"}
        try:
            with open(path, encoding="utf-8") as f:
                persona["raw"] = f.read()
            for line in persona["raw"].splitlines():
                if ":" in line and not line.startswith((" ", "#")):
                    key, _, value = line.partition(":")
                    key = key.strip().upper()
                    if key in ("NAME", "LANGUAGES", "TONE"):
                        persona[key.lower()] = value.strip()
        except OSError:
            persona["raw"] = ""
        return persona

    def _load_intents(self):
        path = os.path.join(self.root, "data", "intents.json")
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"intents": [], "fallback_responses": {}}

    def _intent(self, name):
        for it in self.intents.get("intents", []):
            if it["name"] == name:
                return it
        return None

    # ------------------------------------------------------------ LM usage
    def _lm_generate(self, max_tokens=None, temperature=None):
        """Free-form generation starting from the assistant marker.
        Returns cleaned text or None if the output fails quality checks."""
        if self.lm is None or self.tokenizer is None:
            return None
        cfg = self.config.get("lm", {})
        max_tokens = max_tokens or int(cfg.get("max_tokens", 48))
        temperature = float(temperature if temperature is not None
                            else cfg.get("temperature", 0.75))
        top_k = int(cfg.get("top_k", 12))
        tok = self.tokenizer
        ban = [tok.vocab.get(t, -1) for t in ("<pad>", "<unk>", "<bos>", "<u>", "<a>")]
        ban = [b for b in ban if b >= 0]
        seed_ids = [tok.vocab["<a>"]]
        out_ids = self.lm.sample(tok, seed_ids, max_tokens=max_tokens,
                                 temperature=temperature, top_k=top_k,
                                 ban_ids=ban, rng=self.rng)
        text = tok.text_from_ids_for_generation(out_ids).strip()
        return text if self._lm_ok(text) else None

    @staticmethod
    def _lm_ok(text):
        if not text or len(text) < 12 or len(text) > 220:
            return False
        words = text.split()
        if len(words) < 3:
            return False
        tris = [tuple(words[i:i + 3]) for i in range(len(words) - 2)]
        if tris and len(tris) != len(set(tris)):
            return False  # stuck in a loop
        if len(set(text)) / max(1, len(text)) < 0.28:
            return False
        return True

    # ---------------------------------------------------------- main entry
    def respond(self, user_text):
        """Main brain. Returns the reply string."""
        raw = (user_text or "").strip()
        if not raw:
            lang = self.memory.last_lang
            return (self.responder.say("empty", {
                "fa": ["چیزی ننوشتی! یک سوال یا پیام بفرست."],
                "en": ["You sent nothing! Type a question or a message."],
            }, lang))

        lang = self.memory.preferred_lang or detect_language(
            raw, default=self.config.get("default_language", "fa"))

        # 1) pending note content?
        if self.memory.awaiting == "note":
            intent = self.classifier.predict(raw)[0] if self.classifier.ready else None
            if intent not in ("notes_list", "notes_clear", "notes_add", "farewell"):
                count = self.notes.add(raw)
                self.memory.awaiting = None
                return self.responder.say("notes_add", self._intent("notes_add")["responses"], lang)

        # 2) explicit language switch (fast path, high precision keywords)
        target = self.extractor.extract_language_target(raw)
        if target and any(w in raw.lower() for w in
                          ("حرف بزن", "جواب بده", "صحبت کن", "speak", "talk", "answer in", "switch", "change language", "عوض کن")):
            self.memory.preferred_lang = target
            self.memory.last_lang = target
            return self.responder.say("language_switch",
                                      self._intent("language_switch")["responses"], target)

        # 3) math fast path: bare expression or natural math phrase
        if self._try_math_route(raw, lang):
            return self._last_reply

        # 4) deterministic fast routes (slot-carrying commands)
        fast_intent, slot = self.extractor.fast_intent(raw)
        if fast_intent:
            handler = getattr(self, "_h_" + fast_intent, None)
            if handler is not None:
                if fast_intent == "set_name" and slot:
                    self.memory.name = slot.capitalize()
                    reply = self.responder.say(fast_intent,
                                               self._intent(fast_intent)["responses"], lang,
                                               name=self.memory.name)
                    self._finish(raw, fast_intent, lang)
                    return self._reply(reply)
                if fast_intent == "notes_add" and slot:
                    self.notes.add(slot)
                    reply = self.responder.say(fast_intent,
                                               self._intent(fast_intent)["responses"], lang)
                    self._finish(raw, fast_intent, lang)
                    return self._reply(reply)
                reply = handler(raw, lang, fast_intent)
                self._finish(raw, fast_intent, lang)
                return reply

        # 5) exact match on known patterns (short inputs like "hi" / "سلام")
        exact = self._exact.get(norm.normalize(raw).rstrip("!?.,;:؟،؛"))
        if exact is None:
            exact = self._exact.get(norm.normalize(raw))
        if exact and getattr(self, "_h_" + exact, None) is not None:
            reply = getattr(self, "_h_" + exact)(raw, lang, exact)
            self._finish(raw, exact, lang)
            return reply

        # 6) classify intent
        intent, conf = (self.classifier.predict(raw) if self.classifier.ready
                        else (None, 0.0))
        threshold = float(self.config.get("intent_threshold", 0.45))
        if intent is None or conf < threshold:
            # 7) knowledge retrieval, then response-bank retrieval
            answer, score = self.knowledge.query(raw, lang=lang)
            if answer:
                self._finish(raw, "knowledge", lang)
                return answer
            bank_hit, bank_score = self.response_bank.query(
                raw, threshold=float(self.config.get("response_bank_threshold", 0.38)))
            if bank_hit:
                self._finish(raw, "response_bank", lang)
                return bank_hit
            # 8) curated fallback (LM freeform is only used on explicit request)
            self._finish(raw, "fallback", lang)
            return self.responder.say("fallback", self.fallbacks, lang)

        handler = getattr(self, "_h_" + intent, None)
        if handler is None:
            answer, score = self.knowledge.query(raw, lang=lang)
            if answer:
                self._finish(raw, intent, lang)
                return answer
            bank_hit, bank_score = self.response_bank.query(
                raw, threshold=float(self.config.get("response_bank_threshold", 0.38)))
            if bank_hit:
                self._finish(raw, intent, lang)
                return bank_hit
            self._finish(raw, intent, lang)
            return self.responder.say("fallback", self.fallbacks, lang)

        reply = handler(raw, lang, intent)
        self._finish(raw, intent, lang)
        return reply

    # ------------------------------------------------------------ plumbing
    def _finish(self, raw, intent, lang):
        self.memory.remember_exchange(raw, getattr(self, "_last_reply", ""), lang, intent)

    def _reply(self, text):
        self._last_reply = text
        return text

    def _try_math_route(self, raw, lang):
        """Direct calculation when the text is clearly an expression."""
        t = norm.normalize(raw)
        has_symbol_math = bool(tools.EXPR_HAS_MATH.search(t))
        has_word_math = bool(re.search(
            r"\d\s*(?:به\s*علاوه|به\s*اضافه|بعلاوه|ضرب\s*در|ضربدر|تقسیم\s*بر|"
            r"منهای|منها|به\s*توان|باقی\s*مانده|"
            r"plus|minus|times|multiplied\s+by|divided\s+by|to\s+the\s+power\s+of|"
            r"power\s+of|mod(?:ulo)?)\s*\d", t, re.IGNORECASE)
            or re.search(r"(?:جمع|add)\s+\d+\s*(?:و|and)\s*\d+", t, re.IGNORECASE))
        if not (has_symbol_math or has_word_math):
            return False
        # math is language-neutral: prefer the conversation's language,
        # but honor a clear script signal (e.g. English question words)
        fa_n = sum(1 for ch in raw if "\u0600" <= ch <= "\u06ff")
        en_n = sum(1 for ch in raw if ch.isascii() and ch.isalpha())
        if fa_n == 0 and en_n == 0:
            lang = self.memory.last_lang
        elif fa_n >= en_n:
            lang = "fa"
        elif en_n <= 4 and self.memory.last_lang == "fa":
            lang = "fa"  # something like "ans + 1" mid-Persian-conversation
        try:
            value, expr = self.calc.calc(raw, lang=lang, ans=self.memory.last_result)
        except tools.CalcError:
            return False
        self.memory.last_result = value
        self.memory.last_expression = expr
        it = self._intent("math")
        text = self.responder.say("math", it["responses"], lang,
                                  result=self.responder.format_number(value, lang))
        return self._reply(text)

    # ----------------------------------------------------------- handlers
    def _h_greeting(self, raw, lang, intent):
        name = self.memory.name
        return self._reply(self.responder.say(intent, self._intent(intent)["responses"], lang))

    def _h_farewell(self, raw, lang, intent):
        return self._reply(self.responder.say(intent, self._intent(intent)["responses"], lang))

    def _h_thanks(self, raw, lang, intent):
        return self._reply(self.responder.say(intent, self._intent(intent)["responses"], lang))

    def _h_how_are_you(self, raw, lang, intent):
        return self._reply(self.responder.say(intent, self._intent(intent)["responses"], lang))

    def _h_identity(self, raw, lang, intent):
        return self._reply(self.responder.say(intent, self._intent(intent)["responses"], lang))

    def _h_creator(self, raw, lang, intent):
        return self._reply(self.responder.say(intent, self._intent(intent)["responses"], lang))

    def _h_capabilities(self, raw, lang, intent):
        return self._reply(self.responder.say(intent, self._intent(intent)["responses"], lang))

    def _h_age(self, raw, lang, intent):
        return self._reply(self.responder.say(intent, self._intent(intent)["responses"], lang))

    def _h_feelings(self, raw, lang, intent):
        return self._reply(self.responder.say(intent, self._intent(intent)["responses"], lang))

    def _h_joke(self, raw, lang, intent):
        return self._reply(self.responder.say(intent, self._intent(intent)["responses"], lang))

    def _h_praise(self, raw, lang, intent):
        return self._reply(self.responder.say(intent, self._intent(intent)["responses"], lang))

    def _h_love(self, raw, lang, intent):
        return self._reply(self.responder.say(intent, self._intent(intent)["responses"], lang))

    def _h_insult(self, raw, lang, intent):
        return self._reply(self.responder.say(intent, self._intent(intent)["responses"], lang))

    def _h_weather(self, raw, lang, intent):
        return self._reply(self.responder.say(intent, self._intent(intent)["responses"], lang))

    def _h_affirmation(self, raw, lang, intent):
        return self._reply(self.responder.say(intent, self._intent(intent)["responses"], lang))

    def _h_negation(self, raw, lang, intent):
        return self._reply(self.responder.say(intent, self._intent(intent)["responses"], lang))

    def _h_more(self, raw, lang, intent):
        last = self.memory.last_intent
        if last == "joke":
            return self._reply(self.responder.say("joke", self._intent("joke")["responses"], lang))
        if last in ("random", "math"):
            value = self.random_tool.number(1, 100)
            self.memory.last_result = value
            return self._reply(self.responder.say("random", self._intent("random")["responses"], lang,
                                                  result=self.responder.format_number(value, lang)))
        return self._reply(self.responder.say(intent, self._intent(intent)["responses"], lang))

    def _h_freeform_generate(self, raw, lang, intent):
        """Explicit request for the neural language model to write something."""
        for temperature in (0.65, 0.8, 0.95):
            gen = self._lm_generate(temperature=temperature)
            if gen:
                return self._reply(gen)
        return self._reply(self.responder.say("freeform_generate", {
            "fa": ["الان چیزی تازه از ذهنم درنیاومدم! ازم یه سوال ریاضی بپرس یا بگو «جک بگو».",
                   "شبکه‌ی عصبیم امروز کمی خجالتیه! چیز دیگه‌ای بخواه."],
            "en": ["My neural network is a bit shy right now! Ask me some math or say tell me a joke.",
                   "Could not come up with something new — try me with a question instead!"]},
            lang))

    def _h_set_name(self, raw, lang, intent):
        name = self.extractor.extract_name(raw)
        if name:
            self.memory.name = name.capitalize()
            return self._reply(self.responder.say(intent, self._intent(intent)["responses"], lang,
                                                  name=self.memory.name))
        it = self._intent(intent)
        return self._reply(self.responder.say(intent, it.get("fallback", it["responses"]), lang))

    def _h_get_name(self, raw, lang, intent):
        it = self._intent(intent)
        if self.memory.name:
            return self._reply(self.responder.say(intent, it["responses"], lang,
                                                  name=self.memory.name))
        return self._reply(self.responder.say(intent, it.get("fallback", it["responses"]), lang))

    def _h_notes_add(self, raw, lang, intent):
        content = self.extractor.extract_note_text(raw)
        it = self._intent(intent)
        if content:
            self.notes.add(content)
            return self._reply(self.responder.say(intent, it["responses"], lang))
        self.memory.awaiting = "note"
        return self._reply(self.responder.say(intent, it.get("fallback", it["responses"]), lang))

    def _h_notes_list(self, raw, lang, intent):
        it = self._intent(intent)
        notes = self.notes.listing()
        if not notes:
            return self._reply(self.responder.say(intent, it.get("fallback", it["responses"]), lang))
        listing = self.responder.notes_list(notes, lang)
        header = self.responder.say(intent, it["responses"], lang)
        return self._reply(header + "\n" + listing)

    def _h_notes_clear(self, raw, lang, intent):
        it = self._intent(intent)
        removed = self.notes.clear()
        if removed == 0:
            return self._reply(self.responder.say(intent, it.get("fallback", it["responses"]), lang))
        return self._reply(self.responder.say(intent, it["responses"], lang))

    def _h_time_date(self, raw, lang, intent):
        t = raw.lower()
        asking_date = any(w in t for w in ("تاریخ", "چندمه", "امروز چند", "چه روزی",
                                           "date", "day is it", "today"))
        asking_time = any(w in t for w in ("ساعت", "وقت", "time"))
        if asking_date and not asking_time:
            date_str = self.clock.today(lang)
            return self._reply(self.responder.say("time_date", {
                "fa": ["امروز {d} است."], "en": ["Today is {d}."]}, lang, d=date_str))
        if asking_time and not asking_date:
            time_str = self.clock.now_time(lang)
            it = self._intent(intent)
            return self._reply(self.responder.say(intent, it["responses"], lang, time=time_str))
        # both or ambiguous: give both
        time_str = self.clock.now_time(lang)
        date_str = self.clock.today(lang)
        if lang == "fa":
            return self._reply("ساعت %s است؛ امروز %s." % (time_str, date_str))
        return self._reply("It's %s; today is %s." % (time_str, date_str))

    def _h_math(self, raw, lang, intent):
        it = self._intent(intent)
        try:
            value, expr = self.calc.calc(raw, lang=lang, ans=self.memory.last_result)
            self.memory.last_result = value
            self.memory.last_expression = expr
            return self._reply(self.responder.say(intent, it["responses"], lang,
                                                  result=self.responder.format_number(value, lang)))
        except tools.CalcError:
            return self._reply(self.responder.say(intent, it.get("fallback", it["responses"]), lang))

    def _h_random(self, raw, lang, intent):
        kind = self.extractor.random_kind(raw)
        it = self._intent(intent)
        if kind == "dice":
            value = self.random_tool.dice()
            self.memory.last_result = value
            label = "🎲 " + self.responder.format_number(value, lang)
            return self._reply(self.responder.say(intent, it["responses"], lang, result=label))
        if kind == "coin":
            side = self.random_tool.coin(lang)
            return self._reply(self.responder.say("random", {
                "fa": ["سکه انداختم: {result}!"], "en": ["I flipped a coin: {result}!"]},
                lang, result=side))
        bounds = self.extractor.extract_random_bounds(raw)
        low, high = bounds if bounds else (1, 100)
        value = self.random_tool.number(low, high)
        self.memory.last_result = value
        return self._reply(self.responder.say(intent, it["responses"], lang,
                                              result=self.responder.format_number(value, lang)))

    def _h_run_command(self, raw, lang, intent):
        it = self._intent(intent)
        cmd = self.extractor.extract_command(raw)
        if not cmd:
            return self._reply(self.responder.say(intent, it.get("fallback", it["responses"]),
                                                  lang, allowed=", ".join(tools.SAFE_COMMANDS)))
        ok, output = tools.run_safe_command(cmd)
        if not ok:
            return self._reply(self.responder.say(intent, it.get("fallback", it["responses"]),
                                                  lang, allowed=", ".join(tools.SAFE_COMMANDS)))
        header = self.responder.say(intent, it["responses"], lang)
        return self._reply(header + "\n" + self.responder.command_output(ok, output, lang))

    # -------------------------------------------------------------- helpers
    @property
    def about_text(self):
        return self.persona.get("raw", "")
