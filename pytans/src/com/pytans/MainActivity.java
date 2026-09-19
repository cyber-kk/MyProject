package com.pytans;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.Editable;
import android.text.Spanned;
import android.text.TextWatcher;
import android.text.style.ForegroundColorSpan;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.CompoundButton;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.IOException;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * PyTans — a simple Python IDE for Android.
 *
 * Everything runs in the app private directory:
 *   /data/data/com.pytans/files/python/     bundled CPython (Termux build)
 *   /data/data/com.pytans/files/workspace/  user scripts
 */
public class MainActivity extends Activity {

    private static final int AUTO_SAVE_MS = 30000;
    private static final int HIGHLIGHT_DELAY_MS = 300;
    private static final int LINENOS_DELAY_MS = 120;
    private static final int MAX_OUTPUT_CHARS = 400000;

    private PyEditor editor;
    private TextView lineNumbers;
    private TextView outputView;
    private TextView statusBar;
    private ScrollView outputScroll;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService ioPool = Executors.newFixedThreadPool(2);
    private final StringBuilder outBuf = new StringBuilder();

    private Workspace wsPrivate;   // /data/data/com.pytans/files/workspace
    private Workspace wsPublic;    // /storage/emulated/0/PyTans
    private Workspace workspace;   // currently selected one
    private CheckBox wsPublicToggle;
    private boolean usePublicWs = false;

    private static final int REQ_LEGACY_STORAGE = 41;
    private static final int REQ_ALL_FILES = 42;

    private PythonRuntime runtime;
    private final UndoStack undoStack = new UndoStack();

    private File currentFile = null;
    private volatile boolean dirty = false;
    private boolean programmatic = false;
    private volatile boolean pythonReady = false;
    private long runStartMs = 0;

    private int colKeyword, colString, colComment, colNumber, colBuiltin, colDefault;

    private Runnable pendingHighlight = null;
    private Runnable pendingLineNos = null;
    private Runnable autoSaveTick = null;
    private String pendingBefore = null;
    private int pendingStart = 0;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        try {
            Thread.setDefaultUncaughtExceptionHandler(new CrashGuard());
            setContentView(R.layout.activity_main);

            editor = (PyEditor) findViewById(R.id.editor);
            lineNumbers = (TextView) findViewById(R.id.line_numbers);
            outputView = (TextView) findViewById(R.id.output);
            statusBar = (TextView) findViewById(R.id.status_bar);
            outputScroll = (ScrollView) findViewById(R.id.output_scroll);

            resolveColors();
            setupEditor();
            setupButtons();
            setupWorkspaceToggle();

            wsPrivate = Workspace.privateWs(this);
            wsPublic = Workspace.publicWs();
            workspace = wsPrivate;
            runtime = new PythonRuntime(this);

            outputView.setText(getString(R.string.msg_extracting));
            runtime.ensureInstalled(new PythonRuntime.ReadyCallback() {
                @Override
                public void onReady(int fileCount) {
                    pythonReady = true;
                    if (fileCount > 0) {
                        appendOutput(getString(R.string.msg_extract_done,
                                PythonRuntime.PY_VERSION, fileCount) + "\n\n");
                    }
                    if (currentFile == null) {
                        openFile(new File(workspace.dir(), "hello.py"), true);
                    }
                }

                @Override
                public void onError(String message) {
                    appendOutput(getString(R.string.msg_extract_fail, message) + "\n");
                }
            });

            startAutoSave();
            updateStatus();

            // Problem 2 fix: on first launch request READ/WRITE at runtime;
            // on Android 11+ the grant callback routes to the
            // "All files access" screen.
            requestStorageIfNeeded();
        } catch (Throwable t) {
            showFatal(t);
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        try {
            // Re-check permission state every resume; the file browser works
            // on the public workspace as soon as access is granted.
            refreshStorageState();
            if (storageOk()) {
                afterStorageReady();
            }
        } catch (Throwable ignored) {
        }
    }

    // ------------------------------------------------------- storage perms

    /** Legacy READ/WRITE runtime permissions (gate below Android 11). */
    private boolean hasLegacyStorage() {
        if (Build.VERSION.SDK_INT < 23) return true; // install-time grant
        try {
            return checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE)
                    == PackageManager.PERMISSION_GRANTED
                    && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                    == PackageManager.PERMISSION_GRANTED;
        } catch (Throwable t) {
            return false;
        }
    }

    /** "All files access" gate (Android 11+). */
    private boolean hasAllFiles() {
        if (Build.VERSION.SDK_INT >= 30) {
            try {
                return Environment.isExternalStorageManager();
            } catch (Throwable t) {
                return false;
            }
        }
        return hasLegacyStorage();
    }

    /** True when the public workspace /storage/emulated/0/PyTans is usable. */
    private boolean storageOk() {
        return hasAllFiles();
    }

    /** Request READ/WRITE at runtime (first launch). */
    private void requestStorageIfNeeded() {
        try {
            if (Build.VERSION.SDK_INT >= 30) {
                if (!Environment.isExternalStorageManager()) {
                    requestPermissions(new String[]{
                            Manifest.permission.READ_EXTERNAL_STORAGE,
                            Manifest.permission.WRITE_EXTERNAL_STORAGE},
                            REQ_LEGACY_STORAGE);
                }
            } else if (Build.VERSION.SDK_INT >= 23 && !hasLegacyStorage()) {
                requestPermissions(new String[]{
                        Manifest.permission.READ_EXTERNAL_STORAGE,
                        Manifest.permission.WRITE_EXTERNAL_STORAGE},
                        REQ_LEGACY_STORAGE);
            }
        } catch (Throwable ignored) {
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions,
                                           int[] grantResults) {
        // NOTE: no super.onRequestPermissionsResult() here — it does not
        // exist below API 23 and this app supports minSdk 21. The base
        // implementation is a no-op anyway.
        if (requestCode != REQ_LEGACY_STORAGE) return;
        refreshStorageState();
        if (Build.VERSION.SDK_INT >= 30) {
            if (!Environment.isExternalStorageManager()) {
                // After the runtime grant step, Android 11+ needs
                // "All files access" — take the user there now.
                launchAllFilesScreen();
            } else {
                onStorageGranted();
            }
        } else if (storageOk()) {
            onStorageGranted();
        }
    }

    /** Open the system "All files access" page for this app. */
    private void launchAllFilesScreen() {
        if (Build.VERSION.SDK_INT < 30) return;
        try {
            Intent i = new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                    Uri.parse("package:" + getPackageName()));
            startActivityForResult(i, REQ_ALL_FILES);
        } catch (Throwable e) {
            try {
                startActivityForResult(new Intent(
                        Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION), REQ_ALL_FILES);
            } catch (Throwable ignored) {
                toast(R.string.msg_storage_denied);
            }
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_ALL_FILES) {
            refreshStorageState();
            if (storageOk()) {
                onStorageGranted();
            } else {
                toast(R.string.msg_storage_denied);
            }
        }
    }

    private void onStorageGranted() {
        toast(R.string.msg_storage_ready);
        afterStorageReady();
    }

    /** (Re)prepare the public workspace once access is granted. */
    private void afterStorageReady() {
        if (!usePublicWs) return;
        ioPool.execute(new Runnable() {
            @Override
            public void run() {
                final boolean ok = wsPublic.ensureSample();
                ui.post(new Runnable() {
                    @Override
                    public void run() {
                        if (!ok) {
                            toast(R.string.msg_storage_denied);
                            setPublicToggleSilent(false);
                            usePublicWs = false;
                            workspace = wsPrivate;
                        }
                        updateStatus();
                    }
                });
            }
        });
    }

    private void refreshStorageState() {
        // File browser becomes fully usable the moment access is granted;
        // when denied, workspace operations guide the user to grant it.
        updateStatus();
    }

    /** Guide the user to grant access before touching the public workspace. */
    private boolean ensureStorageForWs() {
        if (workspace == wsPublic && !storageOk()) {
            toast(R.string.msg_storage_needed);
            if (Build.VERSION.SDK_INT >= 30) {
                launchAllFilesScreen();
            } else {
                requestStorageIfNeeded();
            }
            return false;
        }
        return true;
    }

    // -------------------------------------------------- workspace switching

    private void setupWorkspaceToggle() {
        wsPublicToggle = (CheckBox) findViewById(R.id.ws_public);
        wsPublicToggle.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            @Override
            public void onCheckedChanged(CompoundButton buttonView, boolean isChecked) {
                onWorkspaceToggled(isChecked);
            }
        });
    }

    private void setPublicToggleSilent(boolean checked) {
        wsPublicToggle.setOnCheckedChangeListener(null);
        wsPublicToggle.setChecked(checked);
        wsPublicToggle.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            @Override
            public void onCheckedChanged(CompoundButton buttonView, boolean isChecked) {
                onWorkspaceToggled(isChecked);
            }
        });
    }

    private void onWorkspaceToggled(final boolean wantPublic) {
        if (wantPublic && !storageOk()) {
            // No access yet: revert and guide the user to grant it.
            setPublicToggleSilent(false);
            usePublicWs = false;
            workspace = wsPrivate;
            toast(R.string.msg_storage_needed);
            if (Build.VERSION.SDK_INT >= 30) {
                launchAllFilesScreen();
            } else {
                requestStorageIfNeeded();
            }
            updateStatus();
            return;
        }
        usePublicWs = wantPublic;
        workspace = wantPublic ? wsPublic : wsPrivate;
        // A file open from the other workspace loses its association.
        if (currentFile != null && !isUnder(currentFile, workspace.dir())) {
            currentFile = null;
        }
        updateStatus();
        ioPool.execute(new Runnable() {
            @Override
            public void run() {
                final boolean ok = workspace.ensureSample();
                ui.post(new Runnable() {
                    @Override
                    public void run() {
                        if (usePublicWs != wantPublic) return; // switched again
                        if (!ok) {
                            toast(R.string.msg_storage_denied);
                            setPublicToggleSilent(false);
                            usePublicWs = false;
                            workspace = wsPrivate;
                        } else {
                            toast(wantPublic ? R.string.ws_switch_public
                                             : R.string.ws_switch_private);
                        }
                        updateStatus();
                    }
                });
            }
        });
    }

    private static boolean isUnder(File f, File root) {
        try {
            String fp = f.getCanonicalPath();
            String rp = root.getCanonicalPath();
            return fp.startsWith(rp.endsWith("/") ? rp : rp + "/");
        } catch (Throwable t) {
            return false;
        }
    }

    private void resolveColors() {
        colDefault = getResources().getColor(R.color.syn_default);
        colKeyword = getResources().getColor(R.color.syn_keyword);
        colString = getResources().getColor(R.color.syn_string);
        colComment = getResources().getColor(R.color.syn_comment);
        colNumber = getResources().getColor(R.color.syn_number);
        colBuiltin = getResources().getColor(R.color.syn_builtin);
    }

    // ------------------------------------------------------------------ editor

    private void setupEditor() {
        editor.setTypeface(Typeface.MONOSPACE);
        editor.setSelectionListener(new PyEditor.SelectionListener() {
            @Override
            public void onSelectionMoved(int line, int col) {
                updateStatus();
            }
        });
        editor.addTextChangedListener(new TextWatcher() {
            @Override
            public void beforeTextChanged(CharSequence s, int start, int count, int after) {
                if (programmatic) {
                    pendingBefore = null;
                    return;
                }
                pendingStart = start;
                int end = Math.min(start + count, s.length());
                pendingBefore = s.subSequence(start, end).toString();
            }

            @Override
            public void onTextChanged(CharSequence s, int start, int before, int count) {
                editor.refreshCache();
                if (programmatic) return;
                dirty = true;
                String inserted = s.subSequence(start, Math.min(start + count, s.length())).toString();
                undoStack.record(pendingStart, pendingBefore == null ? "" : pendingBefore, inserted);
                pendingBefore = null;
                scheduleLineNos();
                scheduleHighlight();
                updateStatus();
            }

            @Override
            public void afterTextChanged(Editable s) {
            }
        });
    }

    private void setEditorText(String text) {
        programmatic = true;
        try {
            editor.setText(text);
            editor.refreshCache();
            editor.setSelection(0);
        } finally {
            programmatic = false;
        }
        undoStack.clear();
        dirty = false;
        scheduleLineNos();
        scheduleHighlight();
        updateStatus();
    }

    private void scheduleLineNos() {
        if (pendingLineNos == null) {
            pendingLineNos = new Runnable() {
                @Override
                public void run() {
                    updateLineNumbers();
                }
            };
        }
        ui.removeCallbacks(pendingLineNos);
        ui.postDelayed(pendingLineNos, LINENOS_DELAY_MS);
    }

    private void updateLineNumbers() {
        try {
            String text = editor.getText().toString();
            int lines = 1;
            for (int i = 0; i < text.length(); i++) {
                if (text.charAt(i) == '\n') lines++;
            }
            StringBuilder sb = new StringBuilder(lines * 5 + 8);
            for (int i = 1; i <= lines + 1; i++) {
                if (i > 1) sb.append('\n');
                sb.append(i);
            }
            lineNumbers.setText(sb.toString());
        } catch (Throwable ignored) {
        }
    }

    private void scheduleHighlight() {
        if (pendingHighlight == null) {
            pendingHighlight = new Runnable() {
                @Override
                public void run() {
                    runHighlight();
                }
            };
        }
        ui.removeCallbacks(pendingHighlight);
        ui.postDelayed(pendingHighlight, HIGHLIGHT_DELAY_MS);
    }

    private void runHighlight() {
        try {
            final String text = editor.getText().toString();
            final int len = text.length();
            ioPool.execute(new Runnable() {
                @Override
                public void run() {
                    final List<SyntaxEngine.Span> spans = SyntaxEngine.analyze(text);
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            applySpans(spans, len);
                        }
                    });
                }
            });
        } catch (Throwable ignored) {
        }
    }

    private void applySpans(List<SyntaxEngine.Span> spans, int expectedLen) {
        Editable e = editor.getText();
        if (e == null || e.length() != expectedLen) {
            return; // text changed meanwhile; a newer highlight is scheduled
        }
        ForegroundColorSpan[] old = e.getSpans(0, e.length(), ForegroundColorSpan.class);
        for (ForegroundColorSpan s : old) {
            e.removeSpan(s);
        }
        for (SyntaxEngine.Span s : spans) {
            if (s.start < 0 || s.end > e.length() || s.start >= s.end) continue;
            int color;
            switch (s.type) {
                case SyntaxEngine.TYPE_KEYWORD:
                    color = colKeyword;
                    break;
                case SyntaxEngine.TYPE_STRING:
                    color = colString;
                    break;
                case SyntaxEngine.TYPE_COMMENT:
                    color = colComment;
                    break;
                case SyntaxEngine.TYPE_NUMBER:
                    color = colNumber;
                    break;
                case SyntaxEngine.TYPE_BUILTIN:
                    color = colBuiltin;
                    break;
                default:
                    color = colDefault;
            }
            e.setSpan(new ForegroundColorSpan(color), s.start, s.end,
                    Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        }
    }

    private void applyUndo(final boolean isUndo) {
        try {
            UndoStack.Op op = isUndo ? undoStack.popUndo() : undoStack.popRedo();
            if (op == null) return;
            programmatic = true;
            try {
                Editable e = editor.getText();
                int st = Math.max(0, Math.min(op.start, e.length()));
                int en = Math.max(st, Math.min(st + op.newText.length(), e.length()));
                e.replace(st, en, op.oldText);
                editor.refreshCache();
                int caret = Math.min(st + op.oldText.length(), e.length());
                editor.setSelection(caret);
            } finally {
                programmatic = false;
            }
            dirty = true;
            scheduleLineNos();
            scheduleHighlight();
            updateStatus();
        } catch (Throwable ignored) {
        }
    }

    // ------------------------------------------------------------------ buttons

    private void setupButtons() {
        findViewById(R.id.btn_new).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                promptNewFile(null);
            }
        });
        findViewById(R.id.btn_open).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showOpenDialog();
            }
        });
        findViewById(R.id.btn_save).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                onSaveClicked(null);
            }
        });
        findViewById(R.id.btn_rename).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                promptRename();
            }
        });
        findViewById(R.id.btn_delete).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                confirmDelete();
            }
        });
        findViewById(R.id.btn_run).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                onRunClicked();
            }
        });
        findViewById(R.id.btn_stop).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                onStopClicked();
            }
        });
        findViewById(R.id.btn_clear).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                clearOutput();
            }
        });
    }

    private void onSaveClicked(final Runnable after) {
        if (!ensureStorageForWs()) return;
        if (currentFile == null) {
            promptNewFile(after);
            return;
        }
        final String text = editor.getText().toString();
        final File f = currentFile;
        ioPool.execute(new Runnable() {
            @Override
            public void run() {
                try {
                    workspace.write(f, text);
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            dirty = false;
                            updateStatus();
                            toast(R.string.msg_saved);
                            if (after != null) after.run();
                        }
                    });
                } catch (final IOException e) {
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            toast(R.string.msg_save_error, e.getMessage());
                        }
                    });
                }
            }
        });
    }

    private void promptNewFile(final Runnable after) {
        if (!ensureStorageForWs()) return;
        AlertDialog.Builder b = new AlertDialog.Builder(this);
        b.setTitle(R.string.dialog_new_title);
        final EditText input = new EditText(this);
        input.setHint(R.string.hint_file_name);
        input.setSingleLine(true);
        input.setTextColor(getResources().getColor(R.color.dialog_text));
        b.setView(input);
        b.setPositiveButton(R.string.ok, new DialogInterface.OnClickListener() {
            @Override
            public void onClick(DialogInterface d, int which) {
                final String name = Workspace.ensurePyExt(input.getText().toString());
                if (!Workspace.validName(name)) {
                    toast(R.string.msg_invalid_name);
                    return;
                }
                final File f = workspace.file(name);
                ioPool.execute(new Runnable() {
                    @Override
                    public void run() {
                        boolean exists = f.exists();
                        if (!exists) {
                            try {
                                workspace.write(f, "");
                            } catch (final IOException e) {
                                ui.post(new Runnable() {
                                    @Override
                                    public void run() {
                                        toast(R.string.msg_save_error, e.getMessage());
                                    }
                                });
                                return;
                            }
                        }
                        final boolean existsF = exists;
                        ui.post(new Runnable() {
                            @Override
                            public void run() {
                                if (existsF) {
                                    toast(R.string.msg_exists);
                                    return;
                                }
                                currentFile = f;
                                setEditorText("");
                                updateLineNumbers();
                                toast(R.string.msg_created);
                                if (after != null) after.run();
                            }
                        });
                    }
                });
            }
        });
        b.setNegativeButton(R.string.cancel, null);
        b.show();
    }

    private void showOpenDialog() {
        if (!ensureStorageForWs()) return;
        ioPool.execute(new Runnable() {
            @Override
            public void run() {
                final List<String> names = workspace.listPyFiles();
                ui.post(new Runnable() {
                    @Override
                    public void run() {
                        buildOpenDialog(names).show();
                    }
                });
            }
        });
    }

    private AlertDialog buildOpenDialog(List<String> names) {
        ScrollView sc = new ScrollView(this);
        sc.setBackgroundColor(getResources().getColor(R.color.editor_bg));
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        sc.addView(box, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        if (names.isEmpty()) {
            TextView empty = new TextView(this);
            empty.setText(R.string.msg_workspace_empty);
            empty.setTextColor(getResources().getColor(R.color.dialog_text));
            empty.setPadding(dp(18), dp(16), dp(18), dp(16));
            box.addView(empty);
        } else {
            for (final String name : names) {
                TextView row = new TextView(this);
                row.setText(name);
                row.setTextSize(15);
                row.setTextColor(getResources().getColor(R.color.dialog_text));
                row.setPadding(dp(18), dp(12), dp(18), dp(12));
                row.setOnClickListener(new View.OnClickListener() {
                    @Override
                    public void onClick(View v) {
                        openFile(workspace.file(name), false);
                    }
                });
                box.addView(row);
            }
        }

        AlertDialog.Builder b = new AlertDialog.Builder(this);
        b.setTitle(R.string.dialog_open_title);
        b.setView(sc);
        b.setNegativeButton(R.string.cancel, null);
        return b.create();
    }

    private void openFile(final File f, final boolean quietFail) {
        ioPool.execute(new Runnable() {
            @Override
            public void run() {
                try {
                    final String content = workspace.read(f);
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            currentFile = f;
                            setEditorText(content);
                            updateLineNumbers();
                        }
                    });
                } catch (final IOException e) {
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            if (!quietFail) {
                                toast(R.string.msg_open_error, e.getMessage());
                            }
                        }
                    });
                }
            }
        });
    }

    private void promptRename() {
        if (!ensureStorageForWs()) return;
        if (currentFile == null) {
            toast(R.string.msg_no_file);
            return;
        }
        AlertDialog.Builder b = new AlertDialog.Builder(this);
        b.setTitle(R.string.dialog_rename_title);
        final EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setText(currentFile.getName());
        input.setTextColor(getResources().getColor(R.color.dialog_text));
        b.setView(input);
        b.setPositiveButton(R.string.ok, new DialogInterface.OnClickListener() {
            @Override
            public void onClick(DialogInterface d, int which) {
                final String name = Workspace.ensurePyExt(input.getText().toString());
                if (!Workspace.validName(name)) {
                    toast(R.string.msg_invalid_name);
                    return;
                }
                final File from = currentFile;
                final File to = workspace.file(name);
                ioPool.execute(new Runnable() {
                    @Override
                    public void run() {
                        final boolean ok = !to.exists() && from.renameTo(to);
                        ui.post(new Runnable() {
                            @Override
                            public void run() {
                                if (ok) {
                                    currentFile = to;
                                    dirty = false;
                                    updateStatus();
                                    toast(R.string.msg_renamed);
                                } else {
                                    toast(R.string.msg_exists);
                                }
                            }
                        });
                    }
                });
            }
        });
        b.setNegativeButton(R.string.cancel, null);
        b.show();
    }

    private void confirmDelete() {
        if (!ensureStorageForWs()) return;
        if (currentFile == null) {
            toast(R.string.msg_no_file);
            return;
        }
        final File f = currentFile;
        new AlertDialog.Builder(this)
                .setTitle(R.string.dialog_delete_title)
                .setMessage(f.getName())
                .setPositiveButton(R.string.ok, new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int which) {
                        ioPool.execute(new Runnable() {
                            @Override
                            public void run() {
                                final boolean ok = f.delete();
                                ui.post(new Runnable() {
                                    @Override
                                    public void run() {
                                        if (ok) {
                                            currentFile = null;
                                            dirty = false;
                                            updateStatus();
                                            toast(R.string.msg_deleted);
                                        } else {
                                            toast(R.string.msg_open_error, f.getName());
                                        }
                                    }
                                });
                            }
                        });
                    }
                })
                .setNegativeButton(R.string.cancel, null)
                .show();
    }

    // ------------------------------------------------------------------ run

    private void onRunClicked() {
        if (runtime != null && runtime.isRunning()) {
            toast(R.string.msg_already_running);
            return;
        }
        if (currentFile == null) {
            if (dirty || editor.getText().length() > 0) {
                toast(R.string.msg_save_before_run);
                promptNewFile(new Runnable() {
                    @Override
                    public void run() {
                        saveAndRun();
                    }
                });
            } else {
                toast(R.string.msg_no_file);
            }
            return;
        }
        if (dirty) {
            toast(R.string.msg_save_before_run);
            onSaveClicked(new Runnable() {
                @Override
                public void run() {
                    doRun();
                }
            });
        } else {
            doRun();
        }
    }

    private void saveAndRun() {
        if (currentFile == null) return;
        onSaveClicked(new Runnable() {
            @Override
            public void run() {
                doRun();
            }
        });
    }

    private void doRun() {
        final File f = currentFile;
        if (f == null) return;
        if (!ensureStorageForWs()) return;
        if (!pythonReady) {
            toast(R.string.msg_python_not_ready);
            runtime.ensureInstalled(new PythonRuntime.ReadyCallback() {
                @Override
                public void onReady(int fileCount) {
                    pythonReady = true;
                    doRun();
                }

                @Override
                public void onError(String message) {
                    appendOutput(getString(R.string.msg_extract_fail, message) + "\n");
                }
            });
            return;
        }
        // Problem 3 fix: clear the output before each run so every run shows
        // exactly its own stdout/stderr followed by ONE final exit line.
        clearOutput(true);
        try {
            runtime.run(f, new PythonRuntime.OutputCallback() {
                @Override
                public void onOutput(final String chunk, final boolean isErr) {
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            appendOutput(chunk);
                        }
                    });
                }

                @Override
                public void onFinished(final int exitCode, final long elapsedMs) {
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            appendOutput("\n" + getString(R.string.msg_process_exit,
                                    exitCode, elapsedMs / 1000.0) + "\n");
                            updateStatus();
                            scrollToOutputBottom();
                        }
                    });
                }
            });
            runStartMs = System.currentTimeMillis();
            ui.postDelayed(statusTicker, 500);
            updateStatus();
        } catch (final IOException e) {
            appendOutput(getString(R.string.msg_run_error, e.getMessage()) + "\n");
        }
    }

    private final Runnable statusTicker = new Runnable() {
        @Override
        public void run() {
            if (runtime != null && runtime.isRunning()) {
                updateStatus();
                ui.postDelayed(this, 500);
            } else {
                updateStatus();
            }
        }
    };

    private void onStopClicked() {
        if (runtime == null || !runtime.isRunning()) {
            toast(R.string.msg_not_running);
            return;
        }
        runtime.stop();
        appendOutput("\n" + getString(R.string.msg_process_killed) + "\n");
    }

    private void clearOutput() {
        clearOutput(false);
    }

    private void clearOutput(boolean silent) {
        synchronized (outBuf) {
            outBuf.setLength(0);
        }
        outputView.setText("");
        if (!silent) {
            toast(R.string.msg_output_cleared);
        }
    }

    // ------------------------------------------------------------------ status

    private void updateStatus() {
        try {
            String name = currentFile == null ? getString(R.string.untitled) : currentFile.getName();
            String text = editor.getText().toString();
            int sel = editor.getSelectionStart();
            if (sel < 0) sel = 0;
            if (sel > text.length()) sel = text.length();
            int line = 1, col = 1;
            for (int i = 0; i < sel; i++) {
                if (text.charAt(i) == '\n') {
                    line++;
                    col = 1;
                } else {
                    col++;
                }
            }
            String third;
            if (runtime != null && runtime.isRunning()) {
                double secs = (System.currentTimeMillis() - runStartMs) / 1000.0;
                third = String.format(Locale.US, "%.1fs", secs);
            } else {
                third = dirty ? getString(R.string.status_modified) : getString(R.string.status_idle);
            }
            statusBar.setText(getString(R.string.status_fmt, name, line, col, third));
        } catch (Throwable ignored) {
        }
    }

    private void startAutoSave() {
        autoSaveTick = new Runnable() {
            @Override
            public void run() {
                try {
                    if (dirty && currentFile != null && currentFile.exists()) {
                        final String text = editor.getText().toString();
                        final File f = currentFile;
                        ioPool.execute(new Runnable() {
                            @Override
                            public void run() {
                                try {
                                    workspace.write(f, text);
                                    ui.post(new Runnable() {
                                        @Override
                                        public void run() {
                                            dirty = false;
                                            updateStatus();
                                            toast(R.string.msg_auto_saved);
                                        }
                                    });
                                } catch (final IOException e) {
                                    ui.post(new Runnable() {
                                        @Override
                                        public void run() {
                                            toast(R.string.msg_save_error, e.getMessage());
                                        }
                                    });
                                }
                            }
                        });
                    }
                } catch (Throwable ignored) {
                }
                ui.postDelayed(this, AUTO_SAVE_MS);
            }
        };
        ui.postDelayed(autoSaveTick, AUTO_SAVE_MS);
    }

    // ------------------------------------------------------------------ output

    private void appendOutput(String s) {
        synchronized (outBuf) {
            outBuf.append(s);
            if (outBuf.length() > MAX_OUTPUT_CHARS) {
                outBuf.delete(0, outBuf.length() - MAX_OUTPUT_CHARS);
            }
            outputView.setText(outBuf.toString());
        }
        scrollToOutputBottom();
    }

    private void scrollToOutputBottom() {
        outputScroll.post(new Runnable() {
            @Override
            public void run() {
                outputScroll.fullScroll(View.FOCUS_DOWN);
            }
        });
    }

    // ------------------------------------------------------------------ misc

    private void toast(int resId, Object... args) {
        try {
            String msg = args.length == 0 ? getString(resId) : getString(resId, args);
            Toast.makeText(this, msg, Toast.LENGTH_SHORT).show();
        } catch (Throwable ignored) {
        }
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private void showFatal(Throwable t) {
        try {
            LinearLayout box = new LinearLayout(this);
            box.setOrientation(LinearLayout.VERTICAL);
            box.setBackgroundColor(getResources().getColor(R.color.window_bg));

            TextView header = new TextView(this);
            header.setText("PyTans — Error");
            header.setTextColor(getResources().getColor(R.color.header_text));
            header.setBackgroundColor(getResources().getColor(R.color.header_bg));
            header.setTextSize(18);
            header.setTypeface(Typeface.DEFAULT_BOLD);
            header.setPadding(dp(14), dp(10), dp(14), dp(10));

            TextView msg = new TextView(this);
            String m = t.getClass().getName()
                    + (t.getMessage() != null ? (": " + t.getMessage()) : "");
            msg.setText(m);
            msg.setTextColor(getResources().getColor(R.color.dialog_text));
            msg.setTextSize(13);
            msg.setPadding(dp(14), dp(14), dp(14), dp(14));
            msg.setTextIsSelectable(true);

            ScrollView sc = new ScrollView(this);
            sc.addView(msg, new ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

            box.addView(header, new ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
            box.addView(sc, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
            setContentView(box);
        } catch (Throwable ignored) {
        }
    }

    /** Last-resort safety net: render the error instead of dying. */
    private class CrashGuard implements Thread.UncaughtExceptionHandler {
        @Override
        public void uncaughtException(Thread t, final Throwable e) {
            try {
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        showFatal(e);
                    }
                });
            } catch (Throwable ignored) {
            }
        }
    }
}
