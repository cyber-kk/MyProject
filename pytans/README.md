# PyTans — a simple Python IDE for Android

PyTans is a lightweight, native Android IDE for Python 3. It ships a complete
CPython 3.14 interpreter (the Termux `python` package and its shared
libraries) inside the APK, extracts it into the app's private data directory
on first launch, and runs your scripts entirely on-device — no root, no
external storage permission, no network round-trip required.

## Features

- Python code editor with **line numbers** and **syntax highlighting**
  (keywords, strings, comments, numbers, builtins, decorators)
- **Undo / Redo** with typing-merge for comfortable editing
- **Run** the current file with the bundled interpreter; stdout **and**
  stderr stream live into an output panel below the editor
- **Stop** button kills the running Python process
- **Clear** output panel
- File management for the private workspace:
  - New file
  - Open file (list of all `*.py` files in the workspace)
  - Save file
  - Rename file
  - Delete file
- **Status bar** showing the current file name, caret position (`line:column`)
  and the running time of the active process
- **Auto-save** every 30 seconds when the file has unsaved changes
- Light and dark theme that follows the system setting
- Full Python **standard library**: `json`, `urllib`, `http`, `ssl`, `sqlite3`,
  `ctypes`, `asyncio`, `multiprocessing`, `unittest`, and more

## Installation

1. Download `pytans.apk` from this folder.
2. On your Android device, allow installing apps from unknown sources
   (Settings → Security → Install unknown apps) for the browser or file
   manager you use to open the APK.
3. Tap the APK and press **Install**. The app requests only the `INTERNET`
   permission (used by the Python standard library for sockets/urllib).
4. Open **PyTans** from the launcher.

Requirements:

- Android 5.0+ (API 21) to install the app.
- **Android 7.0+ (API 24)** for the bundled Python runtime to actually run
  (the Termux interpreter binaries are built against SDK 24).
- **arm64-v8a (64-bit ARM)** device. This covers virtually all modern phones.
- ~120 MB of free internal storage (the interpreter is extracted into the
  app's private directory on first launch).

## First launch

On the first start PyTans extracts the bundled CPython runtime from the APK
assets into:

```
/data/data/com.pytans/files/python/      <- interpreter ($PREFIX)
/data/data/com.pytans/files/workspace/   <- your scripts
/data/data/com.pytans/files/home/        <- HOME for scripts
```

It also creates a sample script `workspace/hello.py` containing:

```python
print("Hello from PyTans")
```

Press **Run** to execute it — the output panel shows:

```
Hello from PyTans

[Process finished with exit code 0 in 0.2s]
```

## Usage

| Button  | Action                                                              |
|---------|---------------------------------------------------------------------|
| New     | Create a new `.py` file in the workspace (extension auto-added)     |
| Open    | Pick a file from the workspace file list                            |
| Save    | Write the editor buffer to disk (UTF-8)                             |
| Rename  | Rename the current file                                             |
| Delete  | Delete the current file (with confirmation)                         |
| Run     | Saves unsaved changes, then executes the current file               |
| Stop    | Kills the running Python process                                    |
| Clear   | Clears the output panel                                             |

Undo/Redo is available via rapid tap-undo merging (the editor records your
typing history); the status bar always shows `file • line:column • state`
where state is `idle`, `modified`, or the elapsed run time in seconds.
Changes are auto-saved every 30 seconds.

Everything (compilation caches, workspace files, extracted interpreter)
stays inside the app's private data directory. No files are written to
shared storage, and no storage permission is requested.

## Technical notes

- **Interpreter**: CPython 3.14.6, Termux `python` package for `aarch64`,
  plus its dependencies (`libandroid-support`, `openssl`, `libffi`,
  `ncurses`, `readline`, `libbz2`, `libsqlite`, `liblzma`, `zlib`,
  `zstd`, `gdbm`, `libexpat`, `libcrypt`, `ca-certificates`).
- The Python launcher binary ships as a native library
  (`lib/arm64-v8a/libpytanspython.so`) so Android extracts it into the
  app's `nativeLibraryDir` — the only location where apps targeting
  SDK 29+ may execute bundled binaries. All other files live under
  `files/python/` and are resolved via `LD_LIBRARY_PATH`, `PYTHONHOME`
  and `PYTHONPATH` at process start.
- Certificate bundle: `SSL_CERT_FILE` points at the bundled CA store, so
  `urllib`/`ssl` work out of the box.
- Limitations:
  - `pip` is not preinstalled, but `python -m ensurepip` works if you need it.
  - Scripts that spawn a *second* `python3` process via `subprocess` will
    fail with permission denied on Android 10+ (same OS restriction as
    above). In-process work is unaffected.

## Building from source (no Gradle)

The APK is built with the plain Android build tools:

```bash
# 1. Stage the Python runtime into ./assets (downloads Termux debs)
python3 tools/prepare_python_assets.py

# 2. Copy the launcher stub into the jniLibs folder
mkdir -p lib/arm64-v8a
cp assets/python/bin/python3.14 lib/arm64-v8a/libpytanspython.so

# 3. Compile, package, align, sign
aapt2 compile --dir res -o res.zip
aapt2 link -o base.apk -I android.jar --manifest AndroidManifest.xml \
    --java gen -A assets --min-sdk-version 21 --target-sdk-version 34 \
    --version-code 1 --version-name 1.0 res.zip
javac -source 1.8 -target 1.8 -bootclasspath android.jar \
    -d classes $(find src gen -name "*.java")
d8 --release --lib android.jar --min-api 21 --output out \
    $(find classes gen -name "*.class")
zip -j base.apk out/classes.dex
zip -r base.apk lib
zipalign -f 4 base.apk aligned.apk
apksigner sign --ks keystore/bashstore.keystore \
    --ks-key-alias bashstore00filetans \
    --ks-pass pass:filetans0011 --key-pass pass:filetans0011 \
    --out pytans.apk aligned.apk
```

Signing keystore: `keystore/bashstore.keystore`
(alias `bashstore00filetans`, password `filetans0011`, RSA 2048).

## Repository layout

```
pytans/
├── AndroidManifest.xml      app manifest (minSdk 21, targetSdk 34)
├── pytans.apk               signed, installable build
├── README.md                this file
├── src/com/pytans/
│   ├── MainActivity.java    UI, editor logic, dialogs, auto-save, crash guard
│   ├── PyEditor.java        EditText with caret-position reporting
│   ├── SyntaxEngine.java    regex-based Python highlighter
│   ├── UndoStack.java       undo/redo with typing merge
│   ├── PythonRuntime.java   asset extraction + interpreter process control
│   └── Workspace.java       private-directory file I/O
├── res/                     layouts, strings, colors (light + night), icons
└── tools/
    └── prepare_python_assets.py   builds assets/ from Termux packages
```

Every `Activity.onCreate` is wrapped in `try/catch (Throwable)` and a global
uncaught-exception guard renders the error inside the app instead of letting
Android show a crash dialog — PyTans never shows "has stopped".
