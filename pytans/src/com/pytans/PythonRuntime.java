package com.pytans;

import android.content.Context;
import android.content.res.AssetManager;
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
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Manages the bundled (Termux) CPython runtime.
 *
 * Layout on device:
 *   /data/data/com.pytans/files/python/        <- $PREFIX (bin/, lib/, etc/...)
 *   /data/data/com.pytans/files/workspace/     <- user scripts
 *   /data/data/com.pytans/files/home/          <- HOME
 *
 * The python launcher binary itself ships as a native library
 * (libpytanspython.so) and is extracted by the package installer into
 * nativeLibraryDir, which is the only reliably executable location for
 * apps targeting SDK >= 29. libpython3.14.so and all other shared
 * libraries live in files/python/lib and are resolved through
 * LD_LIBRARY_PATH at process start.
 */
public class PythonRuntime {

    public static final String PY_VERSION = "3.14.6";
    private static final String MARKER = ".installed";
    private static final String LAUNCHER_LIB = "libpytanspython.so";

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
            String v = readSmallFile(marker);
            return PY_VERSION.equals(v.trim());
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

    /** Extract bundled Python on first launch (idempotent, background thread). */
    public synchronized void ensureInstalled(final ReadyCallback cb) {
        if (isReady()) {
            cb.onReady(-1);
            return;
        }
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    int count = extractAll();
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
        copyAssetDir(am, "python", pyRoot, counter);
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
                    PY_VERSION + "\n");
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
                        || rel.startsWith("lib/")
                        || rel.startsWith("usr/bin/");
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

    /** Run a script with the bundled interpreter. Blocking setup, streams on threads. */
    public synchronized void run(final File script, final OutputCallback cb) throws IOException {
        if (running) {
            throw new IOException("already running");
        }
        detectStdlibDir();
        String nativeDir = ctx.getApplicationInfo().nativeLibraryDir;
        String prefix = pythonDir().getAbsolutePath();

        List<String> cmd = new ArrayList<String>();
        cmd.add(new File(nativeDir, LAUNCHER_LIB).getAbsolutePath());
        cmd.add(script.getAbsolutePath());

        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.directory(workspaceDir());

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

        Thread outT = pump(p.getInputStream(), false, cb);
        Thread errT = pump(p.getErrorStream(), true, cb);

        new Thread(new Runnable() {
            @Override
            public void run() {
                int code = -1;
                try {
                    code = p.waitFor();
                } catch (InterruptedException ignored) { }
                running = false;
                proc = null;
                cb.onFinished(code, System.currentTimeMillis() - startMs);
            }
        }, "pytans-wait").start();
    }

    private Thread pump(final InputStream stream, final boolean isErr, final OutputCallback cb) {
        Thread t = new Thread(new Runnable() {
            @Override
            public void run() {
                BufferedReader r = new BufferedReader(
                        new InputStreamReader(new BufferedInputStream(stream), StandardCharsets.UTF_8), 8192);
                try {
                    char[] buf = new char[2048];
                    int n;
                    while ((n = r.read(buf)) > 0) {
                        String chunk = new String(buf, 0, n).replaceAll("\\r\\n?", "\n");
                        cb.onOutput(chunk, isErr);
                    }
                } catch (IOException ignored) {
                } finally {
                    try { r.close(); } catch (IOException ignored) { }
                }
            }
        });
        return t;
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
