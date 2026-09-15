#!/usr/bin/env python3
"""Tansarian AI — chat entry point.

Usage:
    python chat.py            interactive chat
    python chat.py --demo     scripted demo conversation
    python chat.py --lang fa  force starting language
    python chat.py --slow     typewriter output
    python chat.py --plain    no ANSI colors
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def _fail(message):
    print(message)
    sys.exit(1)


def main():
    args = {"demo": False, "slow": False, "plain": False, "lang": None}
    for a in sys.argv[1:]:
        if a == "--demo":
            args["demo"] = True
        elif a == "--slow":
            args["slow"] = True
        elif a == "--plain":
            args["plain"] = True
        elif a.startswith("--lang"):
            if "=" in a:
                args["lang"] = a.split("=", 1)[1].strip().lower()
            else:
                i = sys.argv.index(a)
                if i + 1 < len(sys.argv):
                    args["lang"] = sys.argv[i + 1].lower()
        elif a in ("-h", "--help"):
            print(__doc__)
            return

    try:
        import numpy  # noqa: F401
    except ImportError:
        _fail("numpy is not installed.\n"
              "Run the setup script first:   bash setup.sh\n"
              "(on Termux you may need:  pkg install python-numpy  or  pip install numpy)")

    try:
        from engine.agent import TansarianAgent
        from interface import cli
    except ImportError as exc:
        _fail("Failed to import the agent: %s\nRun this from the tansarian_ai directory." % exc)

    try:
        agent = TansarianAgent(root=ROOT)
    except Exception as exc:
        _fail("Failed to start Tansarian: %s\n"
              "If model weights are missing, run:  python train.py" % exc)

    if args["lang"] in ("fa", "en"):
        agent.memory.last_lang = args["lang"]
        agent.memory.preferred_lang = args["lang"]

    cli.run(agent, args)


if __name__ == "__main__":
    main()
