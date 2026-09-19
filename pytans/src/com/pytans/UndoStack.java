package com.pytans;

import java.util.ArrayDeque;

/**
 * Simple text undo/redo stack for the editor.
 * Consecutive typing (inserts / backspaces) within a short window is merged
 * into one operation so undo works at word-sentence granularity.
 */
public class UndoStack {

    private static final int MAX_OPS = 300;
    private static final long MERGE_WINDOW_MS = 1200;

    public static class Op {
        public int start;
        public String oldText;
        public String newText;

        Op(int start, String oldText, String newText) {
            this.start = start;
            this.oldText = oldText;
            this.newText = newText;
        }
    }

    private final ArrayDeque<Op> undoStack = new ArrayDeque<Op>();
    private final ArrayDeque<Op> redoStack = new ArrayDeque<Op>();
    private long lastMs = 0;

    public void record(int start, String oldText, String newText) {
        Op op = new Op(start, oldText, newText);
        Op last = undoStack.peekFirst();
        long now = System.currentTimeMillis();
        boolean merge = last != null && (now - lastMs) < MERGE_WINDOW_MS;

        if (merge && last.oldText.isEmpty() && op.oldText.isEmpty()
                && op.start == last.start + last.newText.length()) {
            // continued typing: extend previous insert
            last.newText = last.newText + op.newText;
        } else if (merge && last.newText.isEmpty() && op.newText.isEmpty()
                && op.start == last.start) {
            // continued backspacing: extend previous delete
            last.oldText = op.oldText + last.oldText;
        } else {
            undoStack.addFirst(op);
            if (undoStack.size() > MAX_OPS) {
                undoStack.removeLast();
            }
        }
        lastMs = now;
        redoStack.clear();
    }

    public boolean canUndo() {
        return !undoStack.isEmpty();
    }

    public boolean canRedo() {
        return !redoStack.isEmpty();
    }

    /** Pop the next undo operation (to be applied by the caller). */
    public Op popUndo() {
        Op op = undoStack.pollFirst();
        if (op != null) {
            redoStack.addFirst(op);
        }
        return op;
    }

    /** Pop the next redo operation (to be applied by the caller). */
    public Op popRedo() {
        Op op = redoStack.pollFirst();
        if (op != null) {
            undoStack.addFirst(op);
        }
        return op;
    }

    public void clear() {
        undoStack.clear();
        redoStack.clear();
    }
}
