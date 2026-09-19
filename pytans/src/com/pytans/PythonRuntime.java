package com.pytans;

import android.content.Context;
import android.content.res.AssetManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.system.Os;

import java.io.BufferedInputStream;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Manages the bundled (Termux) CPython runtime for BOTH arm64-v8a and
 * armeabi-v7a devices.
 *
 * APK asset layout:
 *   assets/python/arm64-v8a/...     full $PREFIX tree (64-bit ELF only)
 *   assets/python/armeabi-v7a/...   full $PREFIX tree (32-bit ELF only)
 *
 * Layout on device:
 *   /data/data/com.pytans/files/python/        <- $PREFIX for THIS device ABI
 *   /data/data/com.pytans/files/workspace/     <- user scripts (private ws)
 *   /data/data/com.pytans/files/home/          <- HOME
 *
 * The python launcher binary itself ships as a native library
 * (libpytanspython.so) in BOTH lib/arm64-v8a/ and lib/armeabi-v7a/ and is
 * extracted by the package installer into nativeLibraryDir, which is the
 * only reliably executable location for apps targeting SDK >= 29.
 * libpython3.14.so and all other shared libraries live in files/python/lib
 * and are resolved through LD_LIBRARY_PATH at process start.
 */
public class PythonRuntime {

    public static final String PY_VERSION = "3.14.6";
    private static final String MARKER = ".installed";
    private static final String LAUNCHER_LIB = "libpytanspython.so";
    private static final String ABI_ARM64 = "arm64-v8a";
    private static final String ABI_ARM32 = "armeabi-v7a";

    /** The ABI of the bundled python tree this app extracts (Problem 1 fix). */
    public static final String DEVICE_ABI = detectDeviceAbi();

    public interface ReadyCallback {
        void onReady(int fileCount);
        void onError(String message);
    }

    public interface OutputCallback {
        void onOutput(String chunk, boolean isErr);
        void onFinished(int exitCode, long elapsedMs);
    }

    private final Context ctx;
    private final Handler main = new Handler(Looper.getMainLooper());
    private volatile Process proc;
    private volatile boolean running = false;
    private volatile long startMs = 0;
    private String stdlibDirName = "python3.14";

    public PythonRuntime(Context ctx) {
        this.ctx = ctx.getApplicationContext();
        detectStdlibDir();
    }

    /**
     * Pick the bundled ABI matching this device. We ship arm64-v8a and
     * armeabi-v7a only; choose the FIRST supported ABI we have a tree for,
     * preferring 64-bit when the device supports both.
     */
    private static String detectDeviceAbi() {
        try {
            String[] abis = Build.SUPPORTED_ABIS;
            if (abis != null) {
                for (String abi : abis) {
                    if (ABI_ARM64.equals(abi)) return ABI_ARM64;
                }
                for (String abi : abis) {
                    if (ABI_ARM32.equals(abi) || "armeabi".equals(abi)) return ABI_ARM32;
                }
            }
        } catch (Throwable ignored) {
        }
        return ABI_ARM32;
    }

    public File pythonDir() {
        return new File(ctx.getFilesDir(), "python");
    }

    public File workspaceDir() {
        return new File(ctx.getFilesDir(), "workspace");
    }

    public File homeDir() {
        return new File(ctx.getFilesDir(), "home");
    }

    public boolean isReady() {
        File marker = new File(pythonDir(), MARKER);
        if (!marker.exists()) return false;
        try {
            // marker format: "<version>:<abi>" (older installs: version only)
            String v = readSmallFile(marker).trim();
            return v.equals(PY_VERSION + ":" + DEVICE_ABI);
        } catch (IOException e) {
            return false;
        }
    }

    public boolean isRunning() {
        return running;
    }

    public double runningSeconds() {
        return running ? (System.currentTimeMillis() - startMs) / 1000.0 : 0.0;
    }

    /** Extract bundled Python for this ABI on first launch (background thread). */
    public synchronized void ensureInstalled(final ReadyCallback cb) {
        if (isReady()) {
            cb.onReady(-1);
            return;
        }
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    final int count = extractAll();
                    main.post(new Runnable() {
                        @Override
                        public void run() {
                            cb.onReady(count);
                        }
                    });
                } catch (final Throwable t) {
                    main.post(new Runnable() {
                        @Override
                        public void run() {
                            cb.onError(t.getClass().getSimpleName() + ": " + t.getMessage());
                        }
                    });
                }
            }
        }, "pytans-extract").start();
    }

    private int extractAll() throws IOException {
        AssetManager am = ctx.getAssets();
        File pyRoot = pythonDir();
        pyRoot.mkdirs();
        int[] counter = new int[]{0};
        // Per-ABI asset root: assets/python/<device-abi>/ (Problem 1 fix)
        String assetRoot = "python/" + DEVICE_ABI;
        String[] probe = am.list(assetRoot);
        if (probe == null || probe.length == 0) {
            throw new IOException("no bundled python assets for ABI " + DEVICE_ABI);
        }
        copyAssetDir(am, assetRoot, pyRoot, counter);
        applyPermissions(pyRoot);

        File ws = workspaceDir();
        ws.mkdirs();
        homeDir().mkdirs();
        File tmp = new File(pyRoot, "tmp");
        tmp.mkdirs();

        File hello = new File(ws, "hello.py");
        if (!hello.exists()) {
            writePrivate(new FileOutputStream(hello), "print(\"Hello from PyTans\")\n");
        }
        try {
            writePrivate(new FileOutputStream(new File(pyRoot, MARKER)),
                    PY_VERSION + ":" + DEVICE_ABI + "\n");
        } catch (IOException e) {
            throw new IOException("cannot write install marker: " + e.getMessage());
        }
        return counter[0];
    }

    private static void writePrivate(FileOutputStream out, String s) throws IOException {
        try {
            out.write(s.getBytes(StandardCharsets.UTF_8));
            out.flush();
        } finally {
            try { out.getFD().sync(); } catch (IOException ignored) { }
            try { out.close(); } catch (IOException ignored) { }
        }
    }

    private void copyAssetDir(AssetManager am, String assetPath, File target, int[] counter)
            throws IOException {
        String[] children = am.list(assetPath);
        if (children == null || children.length == 0) {
            // treat as file
            target.getParentFile().mkdirs();
            InputStream in = am.open(assetPath);
            FileOutputStream out = new FileOutputStream(target);
            try {
                byte[] buf = new byte[65536];
                int n;
                while ((n = in.read(buf)) > 0) {
                    out.write(buf, 0, n);
                }
                counter[0]++;
            } finally {
                try { in.close(); } catch (IOException ignored) { }
                try { out.close(); } catch (IOException ignored) { }
            }
            return;
        }
        target.mkdirs();
        for (String child : children) {
            copyAssetDir(am, assetPath + "/" + child, new File(target, child), counter);
        }
    }

    private void applyPermissions(File root) {
        final int DIR_MODE = 0755;
        final int EXEC_MODE = 0755;
        final int FILE_MODE = 0644;
        String rootPath = root.getAbsolutePath();
        List<File> dirs = new ArrayList<File>();
        dirs.add(root);
        while (!dirs.isEmpty()) {
            File d = dirs.remove(dirs.size() - 1);
            try {
                Os.chmod(d.getAbsolutePath(), DIR_MODE);
            } catch (Throwable ignored) { }
            File[] items = d.listFiles();
            if (items == null) continue;
            for (File f : items) {
                if (f.isDirectory()) {
                    dirs.add(f);
                    continue;
                }
                String p = f.getAbsolutePath();
                String rel = p.substring(rootPath.length() + 1);
                boolean exec = rel.startsWith("bin/")
                        || rel.startsWith("lib/");
                try {
                    Os.chmod(p, exec ? EXEC_MODE : FILE_MODE);
                } catch (Throwable ignored) { }
            }
        }
    }

    private void detectStdlibDir() {
        File lib = new File(pythonDir(), "lib");
        File[] items = lib.listFiles();
        if (items != null) {
            Pattern p = Pattern.compile("python3\\.\\d+");
            for (File f : items) {
                Matcher m = p.matcher(f.getName());
                if (f.isDirectory() && m.matches()) {
                    stdlibDirName = f.getName();
                    return;
                }
            }
        }
    }

    /**
     * Run a script with the bundled interpreter.
     *
     * Problem 3 fix:
     *  - python is started with -u and PYTHONUNBUFFERED=1 (unbuffered stdout)
     *  - stdout and stderr are consumed LINE BY LINE on two separate threads
     *    that are actually STARTED (the old code created but never started
     *    them, so print() output was never shown)
     *  - the process is waited for, then both stream threads are joined, and
     *    only then the exit callback fires exactly once
     */
    public synchronized void run(final File script, final OutputCallback cb) throws IOException {
        if (running) {
            throw new IOException("already running");
        }
        detectStdlibDir();
        String nativeDir = ctx.getApplicationInfo().nativeLibraryDir;
        String prefix = pythonDir().getAbsolutePath();

        List<String> cmd = new ArrayList<String>();
        cmd.add(new File(nativeDir, LAUNCHER_LIB).getAbsolutePath());
        cmd.add("-u"); // unbuffered stdout/stderr
        cmd.add(script.getAbsolutePath());

        ProcessBuilder pb = new ProcessBuilder(cmd);
        File scriptParent = script.getParentFile();
        if (scriptParent != null && scriptParent.isDirectory()) {
            pb.directory(scriptParent);
        } else {
            pb.directory(workspaceDir());
        }

        Map<String, String> env = pb.environment();
        env.put("PYTHONHOME", prefix);
        env.put("PYTHONPATH",
                prefix + "/lib/" + stdlibDirName
                        + ":" + prefix + "/lib/" + stdlibDirName + "/lib-dynload");
        env.put("LD_LIBRARY_PATH", prefix + "/lib" + ":" + nativeDir);
        env.put("PATH", prefix + "/bin:" + nativeDir + ":/system/bin:/system/xbin");
        env.put("HOME", homeDir().getAbsolutePath());
        env.put("TMPDIR", new File(prefix, "tmp").getAbsolutePath());
        env.put("SSL_CERT_FILE", new File(prefix, "etc/tls/cert.pem").getAbsolutePath());
        env.put("LANG", "C.UTF-8");
        env.put("PYTHONUTF8", "1");
        env.put("PYTHONUNBUFFERED", "1");
        env.put("PYTHONDONTWRITEBYTECODE", "1");

        proc = pb.start();
        running = true;
        startMs = System.currentTimeMillis();
        final Process p = proc;
        final long runStart = startMs;

        final AtomicBoolean finishedOnce = new AtomicBoolean(false);

        // Line-by-line pump threads (started below!)
        final Thread outT = pumpLines(p.getInputStream(), false, cb);
        final Thread errT = pumpLines(p.getErrorStream(), true, cb);

        Thread waitT = new Thread(new Runnable() {
            @Override
            public void run() {
                int code = -1;
                try {
                    code = p.waitFor();
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
                // Join stream pumps BEFORE the exit line so that all
                // stdout/stderr lines appear first, exit line last.
                try { outT.join(5000); } catch (InterruptedException ignored) { }
                try { errT.join(5000); } catch (InterruptedException ignored) { }
                if (finishedOnce.compareAndSet(false, true)) {
                    running = false;
                    proc = null;
                    cb.onFinished(code, System.currentTimeMillis() - runStart);
                }
            }
        }, "pytans-wait");
        outT.start();
        errT.start();
        waitT.start();
    }

    /** Read the given stream line-by-line, appending each line immediately. */
    private Thread pumpLines(final InputStream stream, final boolean isErr, final OutputCallback cb) {
        return new Thread(new Runnable() {
            @Override
            public void run() {
                BufferedReader r = new BufferedReader(
                        new InputStreamReader(new BufferedInputStream(stream), StandardCharsets.UTF_8),
                        8192);
                try {
                    String line;
                    while ((line = r.readLine()) != null) {
                        cb.onOutput(line + "\n", isErr);
                    }
                } catch (IOException ignored) {
                    // stream closed (process killed or ended) — stop pumping
                } finally {
                    try { r.close(); } catch (IOException ignored) { }
                }
            }
        }, isErr ? "pytans-pump-err" : "pytans-pump-out");
    }

    /** Kill the running python process (Stop button). */
    public void stop() {
        Process p = proc;
        if (p == null) return;
        int pid = pidOf(p);
        if (pid > 0) {
            try {
                android.os.Process.killProcess(pid);
            } catch (Throwable ignored) { }
        }
        try {
            p.destroy();
        } catch (Throwable ignored) { }
    }

    private static int pidOf(Process p) {
        try {
            Field f = p.getClass().getDeclaredField("pid");
            f.setAccessible(true);
            return f.getInt(p);
        } catch (Throwable t) {
            return -1;
        }
    }

    private static String readSmallFile(File f) throws IOException {
        InputStream in = new FileInputStream(f);
        try {
            java.io.ByteArrayOutputStream buf = new java.io.ByteArrayOutputStream();
            byte[] chunk = new byte[512];
            int n;
            while ((n = in.read(chunk)) > 0) buf.write(chunk, 0, n);
            return new String(buf.toByteArray(), StandardCharsets.UTF_8);
        } finally {
            try { in.close(); } catch (IOException ignored) { }
        }
    }
}
