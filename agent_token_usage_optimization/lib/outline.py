"""Symbol outline extraction.

Prefers tree-sitter when `tree-sitter` (+ language pack or per-lang packages)
is installed. Falls back to the original regex patterns otherwise.

Public API (stable):
  extract(text, lang) -> list[(line_no, kind, name, signature)]
  render(symbols) -> str
  slice_symbol(text, lang, symbol) -> str | None
  backend_name() -> "tree-sitter" | "regex"
"""
from __future__ import annotations

import re
from . import languages

JS_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "do", "return",
    "function", "class", "const", "let", "var", "new", "throw",
    "await", "async", "typeof", "delete", "void", "in", "of",
    "else", "try", "finally",
}

# tree-sitter language name as used by tree_sitter_language_pack / common packs
_TS_LANG_ALIASES = {
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "dart": "dart",
    "rust": "rust",
    "go": "go",
    "java": "java",
    "kotlin": "kotlin",
    "c": "c",
    "cpp": "cpp",
    "csharp": "c_sharp",
    "ruby": "ruby",
    "php": "php",
    "swift": "swift",
    "shell": "bash",
}

# S-expression queries: capture @kind and @name (optional @params for signature).
_TS_QUERIES = {
    "python": """
(function_definition
  name: (identifier) @name) @function
(class_definition
  name: (identifier) @name) @class
""",
    "javascript": """
(function_declaration
  name: (identifier) @name) @function
(generator_function_declaration
  name: (identifier) @name) @function
(class_declaration
  name: (identifier) @name) @class
(method_definition
  name: (property_identifier) @name) @function
(lexical_declaration
  (variable_declarator
    name: (identifier) @name
    value: [(arrow_function) (function_expression) (generator_function)])) @function
(export_statement
  declaration: (function_declaration
    name: (identifier) @name)) @function
(export_statement
  declaration: (class_declaration
    name: (identifier) @name)) @class
""",
    "typescript": """
(function_declaration
  name: (identifier) @name) @function
(class_declaration
  name: (type_identifier) @name) @class
(class_declaration
  name: (identifier) @name) @class
(method_definition
  name: (property_identifier) @name) @function
(interface_declaration
  name: (type_identifier) @name) @interface
(type_alias_declaration
  name: (type_identifier) @name) @type
(lexical_declaration
  (variable_declarator
    name: (identifier) @name
    value: [(arrow_function) (function_expression)])) @function
""",
    "go": """
(function_declaration
  name: (identifier) @name) @function
(method_declaration
  name: (field_identifier) @name) @function
(type_declaration
  (type_spec
    name: (type_identifier) @name)) @type
""",
    "rust": """
(function_item
  name: (identifier) @name) @function
(struct_item
  name: (type_identifier) @name) @struct
(enum_item
  name: (type_identifier) @name) @enum
(trait_item
  name: (type_identifier) @name) @trait
(impl_item
  type: (type_identifier) @name) @impl
""",
    "java": """
(class_declaration
  name: (identifier) @name) @class
(interface_declaration
  name: (identifier) @name) @interface
(method_declaration
  name: (identifier) @name) @function
(constructor_declaration
  name: (identifier) @name) @function
""",
    "dart": """
(class_definition
  name: (identifier) @name) @class
(method_signature
  (function_signature
    name: (identifier) @name)) @function
(function_signature
  name: (identifier) @name) @function
""",
    "c": """
(function_definition
  declarator: (function_declarator
    declarator: (identifier) @name)) @function
(type_definition
  declarator: (type_identifier) @name) @type
(struct_specifier
  name: (type_identifier) @name) @struct
""",
    "cpp": """
(function_definition
  declarator: (function_declarator
    declarator: (identifier) @name)) @function
(class_specifier
  name: (type_identifier) @name) @class
(struct_specifier
  name: (type_identifier) @name) @struct
""",
    "ruby": """
(method
  name: (identifier) @name) @function
(class
  name: (constant) @name) @class
(module
  name: (constant) @name) @class
""",
    "php": """
(function_definition
  name: (name) @name) @function
(class_declaration
  name: (name) @name) @class
(method_declaration
  name: (name) @name) @function
""",
    "kotlin": """
(function_declaration
  (simple_identifier) @name) @function
(class_declaration
  (type_identifier) @name) @class
""",
    "c_sharp": """
(method_declaration
  name: (identifier) @name) @function
(class_declaration
  name: (identifier) @name) @class
(interface_declaration
  name: (identifier) @name) @interface
""",
    "swift": """
(function_declaration
  name: (simple_identifier) @name) @function
(class_declaration
  name: (type_identifier) @name) @class
(struct_declaration
  name: (type_identifier) @name) @struct
""",
    "bash": """
(function_definition
  name: (word) @name) @function
""",
}

_ts_ready = None  # None = unprobed, False = unavailable, True = ready
_ts_get_parser = None
_ts_get_language = None
_ts_Query = None
_ts_QueryCursor = None


def backend_name() -> str:
    return "tree-sitter" if _ensure_tree_sitter() else "regex"


def _ensure_tree_sitter() -> bool:
    global _ts_ready, _ts_get_parser, _ts_get_language, _ts_Query, _ts_QueryCursor
    if _ts_ready is not None:
        return _ts_ready
    try:
        from tree_sitter import Query, QueryCursor  # type: ignore

        _ts_Query = Query
        _ts_QueryCursor = QueryCursor
        try:
            from tree_sitter_language_pack import get_parser, get_language  # type: ignore

            _ts_get_parser = get_parser
            _ts_get_language = get_language
            _ts_ready = True
            return True
        except ImportError:
            pass
        # Fallback: per-language packages (tree_sitter_python, …)
        _ts_get_parser = _parser_from_individual_packages
        _ts_get_language = _language_from_individual_packages
        # Probe one common language to decide availability
        try:
            if _ts_get_parser("python") is not None:
                _ts_ready = True
                return True
        except Exception:
            pass
        _ts_ready = False
        return False
    except ImportError:
        _ts_ready = False
        return False


def _parser_from_individual_packages(ts_name: str):
    """Best-effort parsers from tree_sitter_<lang> packages."""
    from tree_sitter import Language, Parser  # type: ignore

    module_map = {
        "python": "tree_sitter_python",
        "javascript": "tree_sitter_javascript",
        "typescript": "tree_sitter_typescript",
        "go": "tree_sitter_go",
        "rust": "tree_sitter_rust",
        "java": "tree_sitter_java",
        "c": "tree_sitter_c",
        "cpp": "tree_sitter_cpp",
        "ruby": "tree_sitter_ruby",
        "php": "tree_sitter_php",
        "c_sharp": "tree_sitter_c_sharp",
        "bash": "tree_sitter_bash",
        "kotlin": "tree_sitter_kotlin",
        "dart": "tree_sitter_dart",
        "swift": "tree_sitter_swift",
    }
    mod_name = module_map.get(ts_name)
    if not mod_name:
        return None
    import importlib

    mod = importlib.import_module(mod_name)
    lang_fn = getattr(mod, "language", None)
    if lang_fn is None:
        return None
    # typescript package often exposes language_typescript / language_tsx
    if ts_name == "typescript" and hasattr(mod, "language_typescript"):
        lang = Language(mod.language_typescript())
    else:
        lang = Language(lang_fn())
    parser = Parser(lang)
    return parser


def _language_from_individual_packages(ts_name: str):
    parser = _parser_from_individual_packages(ts_name)
    if parser is None:
        return None
    return parser.language


def _line_of(byte_offset: int, text_bytes: bytes) -> int:
    return text_bytes.count(b"\n", 0, byte_offset) + 1


_KIND_CAPS = (
    "function", "class", "struct", "enum", "trait", "impl",
    "interface", "type", "symbol",
)


def _extract_tree_sitter(text: str, lang: str):
    if not _ensure_tree_sitter():
        return None
    ts_name = _TS_LANG_ALIASES.get(lang)
    if not ts_name or ts_name not in _TS_QUERIES:
        return None
    try:
        parser = _ts_get_parser(ts_name)
        if parser is None:
            return None
        language = _ts_get_language(ts_name) if _ts_get_language else getattr(parser, "language", None)
        if language is None:
            return None
        source = text.encode("utf-8", errors="replace")
        tree = parser.parse(source)
        query = _ts_Query(language, _TS_QUERIES[ts_name])
        out = []
        seen = set()

        # Prefer matches (keeps @name with the same pattern hit). Global
        # captures() wrongly pairs outer class nodes with nested method names.
        matches = _ts_matches(query, tree.root_node)
        if matches is not None:
            for _pat_idx, caps in matches:
                # caps: dict[str, list[Node]] or list[(name, node)] depending on version
                capmap = _normalize_match_caps(caps)
                kind = next((k for k in _KIND_CAPS if k in capmap), None)
                name_nodes = capmap.get("name") or []
                if not name_nodes and kind:
                    # kind node itself may be the name in some patterns
                    name_nodes = capmap.get(kind) or []
                if not name_nodes:
                    continue
                name_node = name_nodes[0]
                name = source[name_node.start_byte:name_node.end_byte].decode(
                    "utf-8", errors="replace"
                )
                if not name:
                    continue
                if lang in ("js", "ts") and name in JS_KEYWORDS:
                    continue
                kind = kind or "symbol"
                # line: prefer kind node start if present, else name
                kind_nodes = capmap.get(kind) or []
                line_node = kind_nodes[0] if kind_nodes else name_node
                line_no = _line_of(line_node.start_byte, source)
                key = (name, kind)
                if key in seen:
                    continue
                seen.add(key)
                out.append((line_no, kind, name, ""))
        else:
            # Legacy captures fallback
            for kind, name, line_no in _ts_from_captures(query, tree.root_node, source, lang):
                key = (name, kind)
                if key in seen:
                    continue
                seen.add(key)
                out.append((line_no, kind, name, ""))

        out.sort(key=lambda s: s[0])
        return out
    except Exception:
        return None


def _ts_matches(query, root_node):
    """Return list of (pattern_index, captures) or None if unsupported."""
    try:
        cursor = _ts_QueryCursor(query)
        return list(cursor.matches(root_node))
    except Exception:
        pass
    try:
        return list(query.matches(root_node))
    except Exception:
        return None


def _normalize_match_caps(caps) -> dict:
    """Normalize match captures to dict[str, list[Node]]."""
    if isinstance(caps, dict):
        out = {}
        for k, v in caps.items():
            if isinstance(v, list):
                out[k] = v
            else:
                out[k] = [v]
        return out
    # list of (name, node) or (node, name)
    out = {}
    if not caps:
        return out
    for item in caps:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        a, b = item
        if isinstance(a, str):
            name, node = a, b
        else:
            node, name = a, b
            if not isinstance(name, str):
                continue
        out.setdefault(name, []).append(node)
    return out


def _ts_from_captures(query, root_node, source: bytes, lang: str):
    """Yield (kind, name, line_no) from flat captures (less accurate)."""
    cursor = _ts_QueryCursor(query)
    try:
        captures = cursor.captures(root_node)
    except TypeError:
        captures = query.captures(root_node)

    if isinstance(captures, dict):
        name_nodes = captures.get("name") or []
        kind_to_nodes = {k: v for k, v in captures.items() if k != "name"}
        for kind, nodes in kind_to_nodes.items():
            for node in nodes:
                # Prefer a name node that is a *direct* child of this node
                name = _direct_child_name(node, name_nodes, source)
                if not name:
                    name = _first_identifier(node, source)
                if not name:
                    continue
                if lang in ("js", "ts") and name in JS_KEYWORDS:
                    continue
                yield kind, name, _line_of(node.start_byte, source)
        return

    by_node = {}
    for item in captures or []:
        if isinstance(item, tuple) and len(item) == 2:
            node, cap = item
        else:
            continue
        by_node.setdefault(id(node), {"node": node, "caps": set()})["caps"].add(cap)
    for entry in by_node.values():
        node = entry["node"]
        caps = entry["caps"]
        kind = next((k for k in _KIND_CAPS if k in caps), None)
        if kind is None and "name" not in caps:
            continue
        kind = kind or "symbol"
        if "name" in caps:
            name = source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        else:
            name = _first_identifier(node, source)
        if not name:
            continue
        if lang in ("js", "ts") and name in JS_KEYWORDS:
            continue
        yield kind, name, _line_of(node.start_byte, source)


def _direct_child_name(parent_node, name_nodes, source: bytes) -> str:
    """Name capture that is an immediate child (or same span) of parent."""
    best = None
    best_span = None
    for n in name_nodes:
        if n.start_byte < parent_node.start_byte or n.end_byte > parent_node.end_byte:
            continue
        # Prefer the earliest, shortest name inside the parent (class name, not body)
        span = n.end_byte - n.start_byte
        if best is None or n.start_byte < best.start_byte or (
            n.start_byte == best.start_byte and span < best_span
        ):
            best = n
            best_span = span
    if best is None:
        return ""
    return source[best.start_byte:best.end_byte].decode("utf-8", errors="replace")


def _first_identifier(node, source: bytes) -> str:
    stack = [node]
    while stack:
        n = stack.pop(0)
        if n.type in ("identifier", "type_identifier", "property_identifier",
                      "field_identifier", "name", "constant", "word", "simple_identifier"):
            return source[n.start_byte:n.end_byte].decode("utf-8", errors="replace")
        stack[0:0] = list(n.children)
    return ""


# ── Regex fallback (original) ──────────────────────────────────────────────

PATTERNS = {
    "js": [
        ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)")),
        ("function", re.compile(r"^\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>")),
        ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(\w+)\s*\(([^)]*)\)\s*\{")),
        ("class", re.compile(r"^\s*(?:export\s+)?class\s+(\w+)")),
        ("export", re.compile(r"^\s*(?:module\.)?exports?\.(\w+)\s*=")),
    ],
    "ts": [
        ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)")),
        ("function", re.compile(r"^\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>")),
        ("class", re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)")),
        ("interface", re.compile(r"^\s*(?:export\s+)?interface\s+(\w+)")),
        ("type", re.compile(r"^\s*(?:export\s+)?type\s+(\w+)")),
    ],
    "py": [
        ("function", re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)")),
        ("class", re.compile(r"^\s*class\s+(\w+)")),
    ],
    "dart": [
        ("function", re.compile(r"^\s*(?:Future<[^>]*>|void|[\w<>?,\s]+)\s+(\w+)\s*\(([^)]*)\)\s*(?:async\s*)?\{")),
        ("class", re.compile(r"^\s*(?:abstract\s+)?class\s+(\w+)")),
    ],
    "rust": [
        ("function", re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)")),
        ("struct", re.compile(r"^\s*(?:pub\s+)?struct\s+(\w+)")),
        ("enum", re.compile(r"^\s*(?:pub\s+)?enum\s+(\w+)")),
        ("trait", re.compile(r"^\s*(?:pub\s+)?trait\s+(\w+)")),
        ("impl", re.compile(r"^\s*impl(?:<[^>]*>)?\s+(\w+)")),
    ],
    "go": [
        ("function", re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)\s*\(([^)]*)\)")),
        ("type", re.compile(r"^\s*type\s+(\w+)\s+(?:struct|interface)")),
    ],
    "java": [
        ("class", re.compile(r"^\s*(?:public|private|protected)?\s*(?:abstract\s+)?class\s+(\w+)")),
        ("interface", re.compile(r"^\s*(?:public)?\s*interface\s+(\w+)")),
        ("function", re.compile(r"^\s*(?:public|private|protected)\s+(?:static\s+)?[\w<>?,\[\]\s]+\s+(\w+)\s*\(([^)]*)\)")),
    ],
}


def _extract_regex(text, lang):
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


def extract(text, lang):
    """Return list of (line_no, kind, name, signature)."""
    if not lang:
        return []
    ts = _extract_tree_sitter(text, lang)
    if ts is not None:
        return ts
    return _extract_regex(text, lang)


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
