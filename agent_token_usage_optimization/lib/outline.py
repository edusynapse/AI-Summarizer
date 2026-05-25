import re
from . import languages

JS_KEYWORDS = {"if", "for", "while", "switch", "catch", "do", "return",
               "function", "class", "const", "let", "var", "new", "throw",
               "await", "async", "typeof", "delete", "void", "in", "of",
               "else", "try", "finally"}

# Regex-based symbol extraction. Good enough first cut; swap to tree-sitter
# later if accuracy matters. Returns list of (line_no, kind, name, signature).

PATTERNS = {
    "js": [
        ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)")),
        ("function", re.compile(r"^\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>")),
        ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(\w+)\s*\(([^)]*)\)\s*\{")),  # method
        ("class",    re.compile(r"^\s*(?:export\s+)?class\s+(\w+)")),
        ("export",   re.compile(r"^\s*(?:module\.)?exports?\.(\w+)\s*=")),
    ],
    "ts": [
        ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)")),
        ("function", re.compile(r"^\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>")),
        ("class",    re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)")),
        ("interface",re.compile(r"^\s*(?:export\s+)?interface\s+(\w+)")),
        ("type",     re.compile(r"^\s*(?:export\s+)?type\s+(\w+)")),
    ],
    "py": [
        ("function", re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)")),
        ("class",    re.compile(r"^\s*class\s+(\w+)")),
    ],
    "dart": [
        ("function", re.compile(r"^\s*(?:Future<[^>]*>|void|[\w<>?,\s]+)\s+(\w+)\s*\(([^)]*)\)\s*(?:async\s*)?\{")),
        ("class",    re.compile(r"^\s*(?:abstract\s+)?class\s+(\w+)")),
    ],
    "rust": [
        ("function", re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)")),
        ("struct",   re.compile(r"^\s*(?:pub\s+)?struct\s+(\w+)")),
        ("enum",     re.compile(r"^\s*(?:pub\s+)?enum\s+(\w+)")),
        ("trait",    re.compile(r"^\s*(?:pub\s+)?trait\s+(\w+)")),
        ("impl",     re.compile(r"^\s*impl(?:<[^>]*>)?\s+(\w+)")),
    ],
    "go": [
        ("function", re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)\s*\(([^)]*)\)")),
        ("type",     re.compile(r"^\s*type\s+(\w+)\s+(?:struct|interface)")),
    ],
    "java": [
        ("class",    re.compile(r"^\s*(?:public|private|protected)?\s*(?:abstract\s+)?class\s+(\w+)")),
        ("interface",re.compile(r"^\s*(?:public)?\s*interface\s+(\w+)")),
        ("function", re.compile(r"^\s*(?:public|private|protected)\s+(?:static\s+)?[\w<>?,\[\]\s]+\s+(\w+)\s*\(([^)]*)\)")),
    ],
}

def extract(text, lang):
    if lang not in PATTERNS:
        return []
    pats = PATTERNS[lang]
    out = []
    seen = set()
    for i, line in enumerate(text.splitlines(), start=1):
        for kind, pat in pats:
            m = pat.match(line)
            if m:
                name = m.group(1)
                if lang in ("js", "ts") and name in JS_KEYWORDS:
                    continue
                sig = ""
                if m.lastindex and m.lastindex >= 2:
                    sig = "(" + (m.group(2) or "").strip() + ")"
                key = (name, kind)
                if key in seen:
                    continue
                seen.add(key)
                out.append((i, kind, name, sig))
                break
    return out

def render(symbols):
    if not symbols:
        return "(no symbols extracted)"
    width = max(len(str(s[0])) for s in symbols)
    lines = []
    for line_no, kind, name, sig in symbols:
        lines.append(f"{str(line_no).rjust(width)}  {kind:9s} {name}{sig}")
    return "\n".join(lines)

def slice_symbol(text, lang, symbol):
    """Return the source slice for `symbol`. Brace-matched for C-style langs,
    indentation-bounded for Python-style."""
    symbols = extract(text, lang)
    target = next((s for s in symbols if s[2] == symbol), None)
    if not target:
        return None
    start_line = target[0]
    lines = text.splitlines()
    if lang in languages.INDENT_LANGS:
        return _slice_by_indent(lines, start_line)
    if lang in languages.BRACE_LANGS:
        return _slice_by_braces(lines, start_line)
    return "\n".join(lines[start_line - 1:start_line + 40])

def _slice_by_indent(lines, start_line):
    idx = start_line - 1
    base_indent = len(lines[idx]) - len(lines[idx].lstrip())
    out = [lines[idx]]
    i = idx + 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == "":
            out.append(line)
            i += 1
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= base_indent:
            break
        out.append(line)
        i += 1
    while out and out[-1].strip() == "":
        out.pop()
    return "\n".join(out)

def _slice_by_braces(lines, start_line):
    idx = start_line - 1
    text = "\n".join(lines[idx:])
    depth = 0
    started = False
    in_str = None
    escaped = False
    end = None
    for pos, ch in enumerate(text):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_str:
                in_str = None
            continue
        if ch in ('"', "'", "`"):
            in_str = ch
            continue
        if ch == "{":
            depth += 1
            started = True
        elif ch == "}":
            depth -= 1
            if started and depth == 0:
                end = pos
                break
    if end is None:
        return "\n".join(lines[idx:idx + 80])
    return text[:end + 1]
