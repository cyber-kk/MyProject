package com.pytans;

import android.content.Context;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * All file I/O for the IDE happens inside the app's private directory:
 * /data/data/com.pytans/files/workspace/
 */
public class Workspace {

    private final File dir;

    public Workspace(Context ctx) {
        dir = new File(ctx.getFilesDir(), "workspace");
        if (!dir.exists()) {
            dir.mkdirs();
        }
    }

    public File dir() {
        return dir;
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
