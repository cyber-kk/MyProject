"""Terminal chat interface for Tansarian (colors, commands, demo mode)."""
import os
import sys
import time

from tokenizer import normalizer as norm


def _supports_color(stream):
    if os.environ.get("NO_COLOR"):
        return False
    if not stream.isatty():
        return False
    return os.environ.get("TERM", "") != "dumb"


class Colors:
    def __init__(self, enabled):
        self.ok = enabled
        if enabled:
            self.bold = "\033[1m"
            self.dim = "\033[2m"
            self.cyan = "\033[96m"
            self.green = "\033[92m"
            self.yellow = "\033[93m"
            self.magenta = "\033[95m"
            self.reset = "\033[0m"
        else:
            for name in ("bold", "dim", "cyan", "green", "yellow", "magenta", "reset"):
                setattr(self, name, "")


BANNER = r"""
  ______ ____   ____                 _ _
 /_  __// __ \ / ___|_ __ __ _ _ __ | (_)_ __   ___
  / /  / / _` | |   | '__/ _` | '_ \| | | '_ \ / _ \
 / /  | | (_| | |___| | | (_| | | | | | | | | |  __/
/_/    \ \__,_|\____|_|  \__,_|_| |_|_|_|_| |_|\___|
        \____/   {tagline}
"""


def print_banner(colors, agent, tagline_fa="دستیار هوشمند تو", tagline_en="your smart assistant"):
    print(colors.cyan + colors.bold + BANNER.format(tagline=tagline_en) + colors.reset)
    print(colors.dim + "  Tansarian v%s — %s | %s" % (
        "1.0.0",
        tagline_fa,
        tagline_en) + colors.reset)
    print(colors.dim + "  " + ("─" * 56) + colors.reset)


HELP_TEXT = {
    "fa": """
دستورها:
  /help     راهنما          /lang fa|en   تغییر زبان
  /notes    یادداشت‌ها       /reset        شروع تازه‌ی حافظه
  /about    شخصیت تانسارین   /clear        پاک کردن صفحه
  /exit     خروج

نمونه سوال‌ها:
  «ساعت چنده؟»   «۲۳×۷ چند می‌شه؟»   «یادداشت کن که فردا تماس بگیرم»
  «پایتخت ژاپن چیه؟»   «جک بگو»   «اسم من علی است»
""",
    "en": """
Commands:
  /help     this help        /lang fa|en   switch language
  /notes    show notes       /reset        fresh session memory
  /about    Tansarian's persona   /clear    clear screen
  /exit     quit

Try asking:
  "what time is it?"   "45*12+7"   "add a note: call mom tomorrow"
  "what is the capital of japan?"   "tell me a joke"   "my name is Alex"
""",
}


def slow_print(text, colors, enabled, delay=0.004):
    if not enabled:
        print(text)
        return
    try:
        for ch in text:
            sys.stdout.write(ch)
            sys.stdout.flush()
            if ch != " ":
                time.sleep(delay)
        print()
    except (KeyboardInterrupt, OSError):
        print(text)


def handle_command(cmd, agent, colors, lang_state):
    """Returns True if the command was recognized."""
    parts = cmd.split(maxsplit=1)
    name = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    lang = lang_state["lang"]

    if name in ("/exit", "/quit", "/q", "/خروج"):
        print(colors.dim + ("خداحافظ! " if lang == "fa" else "Goodbye! ") + colors.reset)
        raise SystemExit(0)
    if name == "/help":
        print(HELP_TEXT.get(lang, HELP_TEXT["en"]))
        return True
    if name == "/clear":
        os.system("cls" if os.name == "nt" else "clear")
        return True
    if name == "/lang":
        new = arg.lower() if arg else ("en" if lang == "fa" else "fa")
        if new in ("fa", "en"):
            lang_state["lang"] = new
            agent.memory.preferred_lang = new
            agent.memory.last_lang = new
            msg = ("زبان روی فارسی تنظیم شد." if new == "fa"
                   else "Language set to English.")
            print(colors.green + msg + colors.reset)
        else:
            print(colors.yellow + "usage: /lang fa|en" + colors.reset)
        return True
    if name == "/notes":
        notes = agent.notes.listing()
        if not notes:
            print(colors.yellow + ("هنوز یادداشتی نیست."
                                   if lang == "fa" else "No notes yet.") + colors.reset)
        else:
            print(agent.responder.notes_list(notes, lang))
        return True
    if name == "/reset":
        agent.memory.reset()
        print(colors.green + ("حافظه‌ی این نشست تازه شد."
                              if lang == "fa" else "Session memory cleared.") + colors.reset)
        return True
    if name == "/about":
        print(colors.dim + agent.about_text + colors.reset)
        return True
    if name == "/stats":
        import json as _json
        print(_json.dumps(agent.memory.summary(), ensure_ascii=False))
        return True
    return False


def chat_loop(agent, colors, slow=False):
    lang_state = {"lang": agent.memory.last_lang}
    print_banner(colors, agent)
    print(colors.dim + HELP_TEXT.get("fa" if lang_state["lang"] == "fa" else "en").strip().splitlines()[0] + colors.reset)
    first = True
    while True:
        try:
            lang = lang_state["lang"]
            prompt = ("تو > " if lang == "fa" else "you > ")
            user = input(colors.magenta + colors.bold + prompt + colors.reset).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print(colors.dim + "Bye!" + colors.reset)
            break
        if not user:
            continue
        if user.startswith("/"):
            if first:
                first = False
            try:
                if not handle_command(user, agent, colors, lang_state):
                    print(colors.yellow + ("دستور ناشناخته. /help را ببین."
                                           if lang_state["lang"] == "fa"
                                           else "Unknown command. Try /help.") + colors.reset)
            except SystemExit:
                break
            continue
        first = False
        try:
            reply = agent.respond(user)
        except Exception as exc:  # never crash the chat
            reply = ("اوپس! یه خطای داخلی پیش آمد: %s" % exc) if lang_state["lang"] == "fa" \
                else ("Oops! Internal error: %s" % exc)
        lang_state["lang"] = agent.memory.last_lang
        print(colors.cyan + colors.bold + ("تانسارین > " if lang_state["lang"] == "fa" else "tansarian > ") + colors.reset, end="")
        slow_print(reply, colors, slow)


def demo(agent, colors):
    """Scripted conversation showing off the product."""
    script = [
        ("سلام!", "fa"),
        ("ساعت چنده؟", "fa"),
        ("۲۳×۷ چند می‌شه؟", "fa"),
        ("حاصل ۱۲ به علاوه ۸۸ چقدر میشه؟", "fa"),
        ("اسم من سارا است", "fa"),
        ("اسم من چیه؟", "fa"),
        ("پایتخت ژاپن چیه؟", "fa"),
        ("یادداشت کن که فردا نان بخرم", "fa"),
        ("یادداشت‌هام رو نشون بده", "fa"),
        ("جک بگو", "fa"),
        ("چه کارهایی بلدی؟", "fa"),
        ("hello!", "en"),
        ("what is 45*12?", "en"),
        ("my name is Alex", "en"),
        ("what's my name?", "en"),
        ("tell me a joke", "en"),
        ("what time is it?", "en"),
        ("thanks!", "en"),
    ]
    print_banner(colors, agent)
    for user, _lang in script:
        print(colors.magenta + "  تو/you > " + colors.reset + user)
        try:
            reply = agent.respond(user)
        except Exception as exc:
            reply = "error: %s" % exc
        print(colors.cyan + "  تانسارین > " + colors.reset + reply)
        print()
    print(colors.dim + "  — پایان نمایش / end of demo —" + colors.reset)


def run(agent, args=None):
    args = args or {}
    colors = Colors(_supports_color(sys.stdout))
    if args.get("plain"):
        colors = Colors(False)
    if args.get("demo"):
        demo(agent, colors)
        return
    chat_loop(agent, colors, slow=bool(args.get("slow")))
