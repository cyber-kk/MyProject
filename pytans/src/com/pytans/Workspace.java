package com.pytans;

import android.content.Context;
import android.os.Environment;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * All file I/O for the IDE goes through a Workspace rooted at either
 *   - the app-private directory: /data/data/com.pytans/files/workspace/
 *   - the public directory:      /storage/emulated/0/PyTans/   (Problem 2 fix,
 *     requires storage permission)
 */
public class Workspace {

    /** Public workspace location (fixed, per spec). */
    public static final String PUBLIC_PATH = "/storage/emulated/0/PyTans";

    private final File dir;

    public Workspace(File dir) {
        this.dir = dir;
        if (!dir.exists()) {
            // also create missing parents (e.g. /storage/emulated/0/PyTans)
            dir.mkdirs();
        }
    }

    public static Workspace privateWs(Context ctx) {
        return new Workspace(new File(ctx.getFilesDir(), "workspace"));
    }

    public static Workspace publicWs() {
        return new Workspace(new File(PUBLIC_PATH));
    }

    public File dir() {
        return dir;
    }

    public String path() {
        return dir.getAbsolutePath();
    }

    public boolean canUse() {
        if (dir.isDirectory()) return true;
        return dir.mkdirs();
    }

    public File file(String name) {
        return new File(dir, name);
    }

    /** List all *.py files in the workspace, sorted by name. */
    public List<String> listPyFiles() {
        List<String> out = new ArrayList<String>();
        File[] files = dir.listFiles();
        if (files != null) {
            for (File f : files) {
                if (f.isFile() && f.getName().toLowerCase().endsWith(".py")) {
                    out.add(f.getName());
                }
            }
        }
        Collections.sort(out);
        return out;
    }

    /** Create hello.py sample if the workspace is usable and empty of it. */
    public boolean ensureSample() {
        try {
            if (!canUse()) return false;
            File hello = new File(dir, "hello.py");
            if (!hello.exists()) {
                write(hello, "print(\"Hello from PyTans\")\n");
            }
            return true;
        } catch (Throwable t) {
            return false;
        }
    }

    public static boolean validName(String name) {
        if (name == null) return false;
        String n = name.trim();
        if (n.isEmpty()) return false;
        if (n.contains("/") || n.contains("\\") || n.contains("..")) return false;
        if (n.startsWith(".")) return false;
        return true;
    }

    public static String ensurePyExt(String name) {
        String n = name.trim();
        if (!n.toLowerCase().endsWith(".py")) {
            n = n + ".py";
        }
        return n;
    }

    public String read(File f) throws IOException {
        FileInputStream in = new FileInputStream(f);
        try {
            java.io.ByteArrayOutputStream buf = new java.io.ByteArrayOutputStream();
            byte[] chunk = new byte[8192];
            int n;
            while ((n = in.read(chunk)) > 0) {
                buf.write(chunk, 0, n);
            }
            return new String(buf.toByteArray(), StandardCharsets.UTF_8);
        } finally {
            try { in.close(); } catch (IOException ignored) { }
        }
    }

    public void write(File f, String content) throws IOException {
        // make sure a freshly switched-to public workspace exists on disk
        if (!f.getParentFile().isDirectory() && !f.getParentFile().mkdirs()) {
            throw new IOException("cannot create " + f.getParent());
        }
        FileOutputStream out = new FileOutputStream(f);
        try {
            out.write(content.getBytes(StandardCharsets.UTF_8));
            out.flush();
        } finally {
            try { out.getFD().sync(); } catch (IOException ignored) { }
            try { out.close(); } catch (IOException ignored) { }
        }
    }
}
