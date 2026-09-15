#!/usr/bin/env bash
# ============================================================
#  Tansarian AI — one-shot setup for Termux / Linux / macOS
#
#  Usage:   bash setup.sh
#
#  What it does:
#    1. makes sure Python 3 is available (installs on Termux)
#    2. installs the single dependency (numpy)
#    3. verifies pretrained model files exist (trains if missing)
#    4. runs a self-test so you know everything works
# ============================================================
set -e

cd "$(dirname "$0")"

BOLD=$(tput bold 2>/dev/null || true)
GREEN=$(tput setaf 2 2>/dev/null || true)
YELLOW=$(tput setaf 3 2>/dev/null || true)
RESET=$(tput sgr0 2>/dev/null || true)

say()  { printf "%s\n" "${GREEN}==>${RESET} $1"; }
warn() { printf "%s\n" "${YELLOW}!!>${RESET} $1"; }

echo "----------------------------------------------"
echo "  Tansarian AI setup"
echo "----------------------------------------------"

# --- 1. Python -----------------------------------------------------------
PY=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c "import sys; sys.exit(0 if sys.version_info[0]==3 else 1)" 2>/dev/null; then
            PY="$cand"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    say "Python 3 not found — trying to install..."
    if command -v pkg >/dev/null 2>&1; then
        pkg install -y python
    elif command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update && sudo apt-get install -y python3 python3-pip
    elif command -v brew >/dev/null 2>&1; then
        brew install python
    else
        warn "Please install Python 3 manually, then re-run this script."
        exit 1
    fi
    PY=python3
fi
say "Using Python: $($PY --version 2>&1) ($($PY -c 'import sys;print(sys.executable)'))"

# --- 2. numpy ------------------------------------------------------------
if "$PY" -c "import numpy" 2>/dev/null; then
    say "numpy already installed ($($PY -c 'import numpy; print(numpy.__version__)'))"
else
    say "Installing numpy (the only dependency)..."
    if ! "$PY" -m pip install -r requirements.txt --quiet 2>/dev/null; then
        if command -v pkg >/dev/null 2>&1; then
            warn "pip failed — trying Termux package..."
            pkg install -y python-numpy
        elif command -v apt-get >/dev/null 2>&1; then
            sudo apt-get install -y python3-numpy
        else
            warn "Could not install numpy automatically."
            warn "Try:  pip install numpy   or   pkg install python-numpy"
            exit 1
        fi
    fi
    "$PY" -c "import numpy" || { warn "numpy still missing — aborting."; exit 1; }
    say "numpy installed."
fi

# --- 3. launcher + pretrained weights ------------------------------------
chmod +x tansarian chat.py train.py 2>/dev/null || true

if [ -f "tokenizer/trained/vocab.json" ] && \
   [ -f "model/weights/lm_weights.npz" ] && \
   [ -f "nlu/weights/intent_weights.npz" ]; then
    say "Pretrained model files found."
else
    warn "Some pretrained files are missing — training them now (a few minutes on CPU)..."
    "$PY" train.py
fi

# --- 4. self-test ---------------------------------------------------------
say "Running self-test..."
if "$PY" tests/test_pipeline.py; then
    echo "----------------------------------------------"
    printf "%s\n" "${BOLD}Tansarian is ready!${RESET} Start chatting:"
    echo
    echo "    ./tansarian          (or:  python chat.py)"
    echo "    ./tansarian --demo   (scripted demo)"
    echo
else
    warn "Self-test failed — re-running training usually fixes it:"
    warn "    python train.py"
    exit 1
fi
