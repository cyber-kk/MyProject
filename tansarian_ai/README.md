# Tansarian AI — تانسارین

A complete, ready-to-use AI assistant that runs **entirely on your own device**
(Termux / any Linux / macOS, CPU only). No cloud, no API keys, no root, no GPU.

Tansarian is **pretrained and works out of the box**: clone the repo, run the
setup script, start the chat — and you are talking to your own AI.

```
        you > سلام! ساعت چنده؟
  tansarian > الان ۲۱:۰۹ است.

        you > ۲۳×۷ چند می‌شه؟
  tansarian > حاصل می‌شه ۱۶۱!

        you > اسم من سارا است
  tansarian > خوش‌آمدی سارا جان! از این به بعد اسمت رو یادمه.

        you > what is 45*12?
  tansarian > That would be 540!
```

## What it can do

| | |
|---|---|
| **Conversation** | Real contextual dialogue in **Persian (فارسی)** and **English**, with session memory (remembers your name, your last result, what you were talking about) |
| **Mathematics** | `2+3*4`, `۲۳×۷`, `(۵+۲)/۳`, `2^10`, `۱۰ تقسیم بر ۲`, `پنج ضربدر شش`, `what is 5 plus 3` — Persian *and* English number words, Persian digits (۰-۹), the `ans` / «جواب» variable for the previous result |
| **Time & date** | Device clock + **Jalali (شمسی) calendar** for Persian users |
| **Notes** | Add / list / clear personal notes (persisted on your device) |
| **Knowledge** | General-knowledge questions (capitals, science, Persian literature, tech, daily-life tips) |
| **Safe commands** | A whitelist of harmless shell commands: `ls`, `pwd`, `uname`, `whoami`, `date`, `uptime`, `df`, `echo` |
| **Fun** | Jokes (both languages), dice, coin flips, random numbers |
| **Neural LM** | A real GRU language model trained on the bilingual corpus — ask it to write: «یه جمله بگو» / *say something* |

Everything runs **offline**, on CPU, in pure Python + NumPy.

## Quick start (Termux)

```bash
pkg update && pkg install git python -y
git clone https://github.com/cyber-kk/MyProject.git
cd MyProject/tansarian_ai
bash setup.sh
./tansarian
```

That's it. `setup.sh` installs the single dependency (NumPy), verifies the
pretrained model files, runs a self-test and tells you how to start.

## Quick start (Linux / macOS)

```bash
git clone https://github.com/cyber-kk/MyProject.git
cd MyProject/tansarian_ai
bash setup.sh
./tansarian            # or: python3 chat.py
```

Requirements: **Python 3.8+** and **NumPy** (installed by `setup.sh`).

## Command-line options

```
python chat.py             interactive chat
python chat.py --demo      scripted demo conversation
python chat.py --lang en   start in English (default: fa)
python chat.py --slow      typewriter output
python chat.py --plain     disable ANSI colors
```

## Chat commands

| Command | | |
|---|---|---|
| `/help` | help | `/lang fa\|en` | switch language |
| `/notes` | show notes | `/reset` | clear session memory |
| `/about` | show Tansarian's persona | `/clear` | clear screen |
| `/stats` | session stats | `/exit` | quit |

## Things to try

**Persian:**
```
سلام
حالت چطوره؟
ساعت چنده؟
امروز چندمه؟
۲۳×۷ چند می‌شه؟
حاصل ۱۲ به علاوه ۸۸ چقدر میشه؟
ans + ۱
اسم من علی است
اسم من چیه؟
یادداشت کن که فردا نان بخرم
یادداشت‌هام رو نشون بده
پایتخت ژاپن چیه؟
عدد اول چیه؟
جک بگو
تاس بنداز
یه جمله بگو
اجرا کن pwd
انگلیسی حرف بزن
```

**English:**
```
hello
what can you do?
what time is it?
45*12+7
what is 5 plus 3?
my name is Alex
what's my name?
add a note: call mom tomorrow
show my notes
what is the capital of france?
what is a prime number?
tell me a joke
flip a coin
say something
run pwd
speak persian
```

## How it works (architecture)

```
tansarian_ai/
├── chat.py                  entry point
├── tansarian                shell launcher
├── train.py                 full training pipeline (corpus → tokenizer → LM → NLU)
├── setup.sh                 one-shot installer / verifier
├── config.json              runtime configuration
├── prompts/system.txt       persona & behavior definition (parsed at runtime)
├── data/
│   ├── intents.json         27 intents × 700+ bilingual patterns & responses
│   ├── knowledge.json       65 bilingual knowledge entries
│   ├── corpus.txt           LM training corpus (generated, also ships pretrained)
│   └── build_corpus.py      corpus builder
├── tokenizer/               BPE tokenizer (normalizer + trainer + trained files)
│   └── trained/             vocab.json + merges.json (pretrained)
├── model/                   GRU language model in pure NumPy
│   └── weights/lm_weights.npz   (pretrained, ~2.5 MB)
├── nlu/                     intent classifier + knowledge retrieval
│   └── weights/             pretrained softmax classifier
├── engine/                  the agent: routing, memory, tools, responder
├── interface/               terminal chat UI
└── tests/test_pipeline.py   18-check end-to-end test suite
```

**The pipeline, end to end:**

1. **Normalization** — Persian/Arabic digits → ASCII, Arabic → Persian letter
   forms, diacritics stripped, ZWNJ preserved (می‌روم stays one word).
2. **Tokenizer** — a real BPE subword tokenizer trained on the bilingual
   corpus (≈1.8 K tokens) covering Persian, English, digits and math symbols.
3. **Language model** — embedding + GRU + softmax implemented from scratch in
   NumPy, trained with full BPTT and Adam (verified against complex-step
   differentiation). Used for on-demand text generation.
4. **Intent classifier** — hashed character/word n-gram features + softmax
   regression, trained on 700+ bilingual patterns with data augmentation.
5. **The agent** — deterministic fast-routes for slot-carrying commands
   (names, notes, math), intent routing, TF-IDF knowledge retrieval, a
   retrieval response bank, session memory, and safe tool execution.

## Retraining (optional)

The model ships **pretrained** — you never have to do this. To rebuild from
scratch anyway:

```bash
python train.py                 # everything (≈4 minutes on a phone CPU)
python train.py --skip-lm       # tokenizer + intent classifier only
python train.py --quick         # fast smoke training
```

Edit `data/intents.json` or `data/knowledge.json` to teach Tansarian new
tricks, then retrain. Your persona lives in `prompts/system.txt`; runtime
tuning (temperature, thresholds) in `config.json`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `numpy` fails to install on Termux | `pkg install python-numpy` then re-run `setup.sh` |
| Persian text looks reversed | Termux renders RTL fine; try a font with Persian glyphs, or run `./tansarian --plain` |
| Weights missing / corrupted | `python train.py` rebuilds everything |
| Notes disappeared | Notes are stored in `~/.tansarian/notes.json` — they persist across sessions |
| Something else broke | `python tests/test_pipeline.py` tells you which part failed |

## License

MIT — see the LICENSE file at the repository root.
