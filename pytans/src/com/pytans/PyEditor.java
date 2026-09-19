package com.pytans;

import android.content.Context;
import android.text.Editable;
import android.util.AttributeSet;
import android.widget.EditText;

/**
 * EditText that reports caret movement so the status bar can show line:column.
 */
public class PyEditor extends EditText {

    public interface SelectionListener {
        void onSelectionMoved(int line, int col);
    }

    private SelectionListener listener;
    private String cachedText = "";

    public PyEditor(Context context) {
        super(context);
    }

    public PyEditor(Context context, AttributeSet attrs) {
        super(context, attrs);
    }

    public PyEditor(Context context, AttributeSet attrs, int defStyleAttr) {
        super(context, attrs, defStyleAttr);
    }

    public void setSelectionListener(SelectionListener l) {
        listener = l;
    }

    public void refreshCache() {
        Editable e = getText();
        cachedText = (e == null) ? "" : e.toString();
    }

    @Override
    protected void onSelectionChanged(int selStart, int selEnd) {
        super.onSelectionChanged(selStart, selEnd);
        if (listener != null) {
            String s = getText() == null ? "" : getText().toString();
            if (s.length() != cachedText.length()) cachedText = s;
            int sel = Math.min(selStart, cachedText.length());
            int line = 1;
            int col = 1;
            for (int i = 0; i < sel && i < cachedText.length(); i++) {
                char c = cachedText.charAt(i);
                if (c == '\n') {
                    line++;
                    col = 1;
                } else {
                    col++;
                }
            }
            listener.onSelectionMoved(line, col);
        }
    }
}
