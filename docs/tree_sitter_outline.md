# Tree-sitter outline (with regex fallback)

`broker.py outline` and `broker.py read --symbol` use `lib/outline.py`.

## Behavior

1. If **tree-sitter** is importable **and** a language grammar is available,
   symbols are extracted via tree-sitter queries (`backend=tree-sitter`).
2. Otherwise the original **regex** patterns run (`backend=regex`).

```bash
python3 skills/agent_token_usage_optimization/broker.py outline src/auth/session.py
# FILE: ...  lang=py  backend=tree-sitter  symbols=N
```

Public API is unchanged: `extract`, `render`, `slice_symbol`, plus `backend_name()`.

## Optional install (higher accuracy)

Recommended (many languages in one package):

```bash
pip install tree-sitter tree-sitter-language-pack
```

Or install per-language packages, for example:

```bash
pip install tree-sitter tree-sitter-python tree-sitter-javascript tree-sitter-typescript
```

No install is required for the skill to work — regex remains the default
fallback.

## Supported languages (queries)

When grammars are present: Python, JavaScript, TypeScript, Go, Rust, Java,
Dart, C/C++, Ruby, PHP, Kotlin, C#, Swift, Bash. Other extensions still use
regex if patterns exist (`lib/outline.py` `PATTERNS`).

## Accuracy notes

- Tree-sitter handles nested methods, multi-line signatures, and export
  wrappers better than line regex.
- Signature columns may be empty under tree-sitter (name + kind + line are
  primary); slicing still uses brace/indent rules from the symbol start line.
