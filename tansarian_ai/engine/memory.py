"""Session memory: keeps the conversation contextual within a session."""
import json
import os
from collections import deque


class ConversationMemory:
    def __init__(self, max_history=50):
        self.name = None
        self.preferred_lang = None       # set by /lang or explicit switch
        self.last_lang = "fa"            # language of the last exchange
        self.last_intent = None
        self.last_result = None          # last numeric answer (calculator / random)
        self.last_expression = None
        self.awaiting = None             # None | 'note'
        self.history = deque(maxlen=max_history)
        self._said = {}                  # intent -> set of used responses

    def remember_exchange(self, user_text, ai_text, lang, intent):
        self.history.append({"user": user_text, "ai": ai_text,
                             "lang": lang, "intent": intent})
        self.last_lang = lang
        self.last_intent = intent

    def pick_variant(self, intent, variants, rng):
        """Choose a response variant, avoiding immediate repeats."""
        if not variants:
            return ""
        used = self._said.setdefault(intent, set())
        fresh = [v for v in variants if v not in used]
        if not fresh:
            used.clear()
            fresh = list(variants)
        choice = fresh[int(rng.integers(0, len(fresh)))] if hasattr(rng, "integers") \
            else fresh[rng.randrange(len(fresh))]
        used.add(choice)
        return choice

    def reset(self):
        self.name = None
        self.preferred_lang = None
        self.last_lang = "fa"
        self.last_intent = None
        self.last_result = None
        self.last_expression = None
        self.awaiting = None
        self.history.clear()
        self._said.clear()

    # notes are persisted by the notes tool, not here
    def summary(self):
        return {
            "name": self.name,
            "preferred_lang": self.preferred_lang,
            "last_lang": self.last_lang,
            "last_intent": self.last_intent,
            "exchanges": len(self.history),
        }
