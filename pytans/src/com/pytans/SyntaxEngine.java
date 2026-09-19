package com.pytans;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Lightweight regex-based Python syntax tokenizer.
 * Produces colored spans for comments, strings, numbers, keywords and builtins.
 */
public final class SyntaxEngine {

    public static final int TYPE_DEFAULT = 0;
    public static final int TYPE_KEYWORD = 1;
    public static final int TYPE_STRING = 2;
    public static final int TYPE_COMMENT = 3;
    public static final int TYPE_NUMBER = 4;
    public static final int TYPE_BUILTIN = 5;

    public static class Span {
        public final int start;
        public final int end;
        public final int type;

        Span(int start, int end, int type) {
            this.start = start;
            this.end = end;
            this.type = type;
        }
    }

    private static final int MAX_ANALYZE_LEN = 300000;

    private static final Pattern TOKENS = Pattern.compile(
            "#[^\\n]*"                                                    // comment
            + "|\"\"\"[\\s\\S]*?(?:\"\"\"|$)"                             // triple double
            + "|'''[\\s\\S]*?(?:'''|$)"                                   // triple single
            + "|(?:[rRbBuUfF]{0,2})(?:\"(?:[^\"\\\\\\n]|\\\\.)*\""        // string
            + "|'(?:[^'\\\\\\n]|\\\\.)*')"
            + "|\\b(?:0[xXoObB][0-9a-fA-F_]+"                             // number
            + "|(?:\\d[\\d_]*(?:\\.[\\d_]*)?|\\.[\\d_]+)(?:[eE][+-]?\\d+)?[jJ]?)\\b"
            + "|\\b(?:False|None|True|and|as|assert|async|await|break|class"
            + "|continue|def|del|elif|else|except|finally|for|from|global"
            + "|if|import|in|is|lambda|nonlocal|not|or|pass|raise|return"
            + "|try|while|with|yield)\\b"                                 // keyword
            + "|\\b(?:abs|all|any|bin|bool|bytearray|bytes|callable|chr"
            + "|classmethod|compile|complex|delattr|dict|dir|divmod"
            + "|enumerate|eval|exec|filter|float|format|frozenset|getattr"
            + "|globals|hasattr|hash|hex|id|input|int|isinstance"
            + "|issubclass|iter|len|list|locals|map|max|memoryview|min"
            + "|next|object|oct|open|ord|pow|print|property|range|repr"
            + "|reversed|round|set|setattr|slice|sorted|staticmethod|str"
            + "|sum|super|tuple|type|vars|zip)\\b"                        // builtin
            + "|@[A-Za-z_][A-Za-z0-9_.]*"                                 // decorator
    );

    private SyntaxEngine() {
    }

    /** Analyze off the UI thread; returns spans for the given text. */
    public static List<Span> analyze(String text) {
        List<Span> out = new ArrayList<Span>();
        if (text == null || text.isEmpty() || text.length() > MAX_ANALYZE_LEN) {
            return out;
        }
        Matcher m = TOKENS.matcher(text);
        while (m.find()) {
            String t = m.group();
            char c0 = t.charAt(0);
            int type;
            if (c0 == '#') {
                type = TYPE_COMMENT;
            } else if (c0 == '"' || c0 == '\'') {
                type = TYPE_STRING;
            } else if (c0 == '@') {
                type = TYPE_BUILTIN;
            } else if (c0 >= '0' && c0 <= '9') {
                type = TYPE_NUMBER;
            } else if (c0 == '.' || c0 == 'r' || c0 == 'R' || c0 == 'b'
                    || c0 == 'B' || c0 == 'f' || c0 == 'F' || c0 == 'u' || c0 == 'U') {
                // raw-string prefix or .5 number
                type = (c0 == '.') ? TYPE_NUMBER : TYPE_STRING;
            } else {
                type = Character.isDigit(c0) ? TYPE_NUMBER
                        : (t.charAt(t.length() - 1) == '_' || Character.isLetter(t.charAt(0))
                        ? keywordOrBuiltin(t) : TYPE_DEFAULT);
            }
            if (type != TYPE_DEFAULT) {
                out.add(new Span(m.start(), m.end(), type));
            }
        }
        return out;
    }

    private static int keywordOrBuiltin(String t) {
        if (KEYWORDS.contains(t)) return TYPE_KEYWORD;
        if (BUILTINS.contains(t)) return TYPE_BUILTIN;
        return TYPE_DEFAULT;
    }

    private static final java.util.Set<String> KEYWORDS = new java.util.HashSet<String>(
            java.util.Arrays.asList(
                    "False", "None", "True", "and", "as", "assert", "async", "await",
                    "break", "class", "continue", "def", "del", "elif", "else",
                    "except", "finally", "for", "from", "global", "if", "import",
                    "in", "is", "lambda", "nonlocal", "not", "or", "pass", "raise",
                    "return", "try", "while", "with", "yield"));

    private static final java.util.Set<String> BUILTINS = new java.util.HashSet<String>(
            java.util.Arrays.asList(
                    "abs", "all", "any", "bin", "bool", "bytearray", "bytes",
                    "callable", "chr", "classmethod", "compile", "complex",
                    "delattr", "dict", "dir", "divmod", "enumerate", "eval",
                    "exec", "filter", "float", "format", "frozenset", "getattr",
                    "globals", "hasattr", "hash", "hex", "id", "input", "int",
                    "isinstance", "issubclass", "iter", "len", "list", "locals",
                    "map", "max", "memoryview", "min", "next", "object", "oct",
                    "open", "ord", "pow", "print", "property", "range", "repr",
                    "reversed", "round", "set", "setattr", "slice", "sorted",
                    "staticmethod", "str", "sum", "super", "tuple", "type",
                    "vars", "zip"));
}
