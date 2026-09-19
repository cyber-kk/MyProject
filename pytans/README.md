# PyTans — a simple Python IDE for Android

PyTans is a lightweight, native Android IDE for Python 3. It ships a complete
CPython 3.14 interpreter (the Termux `python` package and its shared
libraries) inside the APK — for **both 64-bit and 32-bit ARM devices** —
extracts the matching tree into the app's private data directory on first
launch, and runs your scripts entirely on-device. No root required, no
network round-trip required.

## Features

- Python code editor with **line numbers** and **syntax highlighting**
  (keywords, strings, comments, numbers, builtins, decorators)
- **Undo / Redo** with typing-merge for comfortable editing
- **Run** the current file with the bundled interpreter; stdout **and**
  stderr are consumed line-by-line on separate threads and stream live into
  the output panel (Python runs unbuffered: `-u` + `PYTHONUNBUFFERED=1`).
  Each run clears the panel and ends with exactly one
  `[Process finished with exit code N in X.XXs]` line, printed after both
  stream readers have drained.
- **Stop** button kills the running Python process
- **Clear** output panel
- **Two workspaces**, switchable in the UI:
  - *App-private*: `/data/data/com.pytans/files/workspace/` (always usable)
  - *Public storage*: `/storage/emulated/0/PyTans/` (requires storage
    permission — see below)
  - New / Open / Save / Rename / Delete operate on the selected workspace
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
3. Tap the APK and press **Install**.
4. Open **PyTans** from the launcher.

Requirements:

- Android 5.0+ (API 21) to install the app.
- **Android 7.0+ (API 24)** for the bundled Python runtime to actually run
  (the Termux interpreter binaries are built against SDK 24).
- **arm64-v8a (64-bit ARM) or armeabi-v7a (32-bit ARM)** device — the APK
  contains native code for both ABIs, so it installs and runs on 32-bit
  phones as well.
- ~200 MB of free internal storage (the interpreter for your device's ABI
  is extracted into the app's private directory on first launch).

## Storage permission (public workspace)

The app always works without any permission using the private workspace.
To use the public workspace at `/storage/emulated/0/PyTans/`, grant access:

- On **first launch** PyTans requests `READ_EXTERNAL_STORAGE` and
  `WRITE_EXTERNAL_STORAGE` at runtime.
- On **Android 11+ (API 30+)**, after that grant step, the app automatically
  sends you to the system **"All files access"** screen
  (`Settings → Apps → PyTans → Files and media → Allow access to manage all
  files`). Tap **Allow**.
- On **Android 6–10** granting the runtime permission dialog is enough.
- The state is re-checked every time the app resumes (`onResume`); the
  moment access is granted, the public workspace becomes usable. If you try
  to switch to the public workspace (or open/save a file there) without
  access, PyTans guides you straight to the permission screen.

Manifest declarations: `READ_EXTERNAL_STORAGE`, `WRITE_EXTERNAL_STORAGE`,
`MANAGE_EXTERNAL_STORAGE`, and `android:requestLegacyExternalStorage="true"`.

## First launch

On the first start PyTans detects the device ABI (`Build.SUPPORTED_ABIS`)
and extracts the matching bundled CPython tree
(`assets/python/arm64-v8a/` or `assets/python/armeabi-v7a/`) into:

```
/data/data/com.pytans/files/python/      <- interpreter ($PREFIX)
/data/data/com.pytans/files/workspace/   <- private workspace (your scripts)
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

The trees are never mixed: the arm64-v8a assets contain only 64-bit ELFs and
the armeabi-v7a assets only 32-bit ELFs, and the launcher binary for the
device ABI is installed per-ABI as a native library (see below).

## Usage

| Button / control | Action                                                              |
|------------------|---------------------------------------------------------------------|
| New              | Create a new `.py` file in the current workspace (extension auto-added) |
| Open             | Pick a file from the current workspace's `.py` list                 |
| Save             | Write the editor buffer to disk (UTF-8)                             |
| Rename           | Rename the current file                                             |
| Delete           | Delete the current file (with confirmation)                         |
| Workspace □ Public storage | Switch between the private and the public workspace       |
| Run              | Saves unsaved changes, clears the output, executes the current file |
| Stop             | Kills the running Python process                                    |
| Clear            | Clears the output panel                                             |

Undo/Redo is available via rapid tap-undo merging (the editor records your
typing history); the status bar always shows `file • line:column • state`
where state is `idle`, `modified`, or the elapsed run time in seconds.
Changes are auto-saved every 30 seconds.

## Technical notes

- **Interpreter**: CPython 3.14.6, Termux `python` package for `aarch64`
  *and* `arm`, plus their dependencies (`libandroid-support`, `openssl`,
  `libffi`, `ncurses`, `readline`, `libbz2`, `libsqlite`, `liblzma`, `zlib`,
  `zstd`, `gdbm`, `libexpat`, `libcrypt`, `ca-certificates`).
- **Per-ABI packaging**: each interpreter tree lives under
  `assets/python/<abi>/`; the Python launcher binary for each ABI ships as a
  native library (`lib/<abi>/libpytanspython.so`) so Android extracts it
  into the app's `nativeLibraryDir` — the only location where apps
  targeting SDK 29+ may execute bundled binaries. All other files live
  under `files/python/` and are resolved via `LD_LIBRARY_PATH`,
  `PYTHONHOME` and `PYTHONPATH` at process start.
- **Unbuffered output**: scripts run with `python -u` and
  `PYTHONUNBUFFERED=1`; the runtime reads `stdout` and `stderr`
  line-by-line on two dedicated threads, joins them, and only then reports
  the exit line — so `print()` output always appears, in order, exactly
  once per run.
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
# 1. Stage the Python runtime for BOTH ABIs into ./assets
#    (downloads Termux aarch64 + arm debs, rebases the prefix, prunes,
#     resolves symlinks, copies each bin/python3.14 launcher stub into
#     lib/<abi>/libpytanspython.so)
python3 tools/prepare_python_assets.py

# 2. Compile, package, align, sign
aapt2 compile --dir res -o res.zip
aapt2 link -o base.apk -I android.jar --manifest AndroidManifest.xml \
    --java gen -A assets --min-sdk-version 21 --target-sdk-version 34 \
    --version-code 2 --version-name 1.1 res.zip
javac -source 1.8 -target 1.8 -bootclasspath android.jar \
    -d classes $(find src gen -name "*.java")
d8 --release --lib android.jar --min-api 21 --output out \
    $(find classes gen -name "*.class")
zip -j base.apk out/classes.dex
zip -r base.apk lib        # contains lib/arm64-v8a AND lib/armeabi-v7a
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
├── AndroidManifest.xml      app manifest (minSdk 21, targetSdk 34, storage perms)
├── pytans.apk               signed, installable build (arm64-v8a + armeabi-v7a)
├── README.md                this file
├── src/com/pytans/
│   ├── MainActivity.java    UI, editor logic, dialogs, storage-permission flow,
│   │                        workspace switching, auto-save, crash guard
│   ├── PyEditor.java        EditText with caret-position reporting
│   ├── SyntaxEngine.java    regex-based Python highlighter
│   ├── UndoStack.java       undo/redo with typing merge
│   ├── PythonRuntime.java   ABI detection, per-ABI asset extraction,
│   │                        interpreter process + stream pumping
│   └── Workspace.java       file I/O for the private and public workspaces
├── res/                     layouts, strings, colors (light + night), icons
└── tools/
    └── prepare_python_assets.py   builds assets/python/<abi>/ from Termux packages
```

Every `Activity.onCreate` is wrapped in `try/catch (Throwable)` and a global
uncaught-exception guard renders the error inside the app instead of letting
Android show a crash dialog — PyTans never shows "has stopped".
