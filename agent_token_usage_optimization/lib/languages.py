EXT_TO_LANG = {
    ".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "js",
    ".ts": "ts", ".tsx": "ts",
    ".py": "py",
    ".dart": "dart",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".sh": "shell", ".bash": "shell",
}

BRACE_LANGS = {"js", "ts", "dart", "rust", "go", "java", "kotlin", "c", "cpp", "csharp", "swift", "php"}
INDENT_LANGS = {"py", "ruby"}

def detect(path):
    for ext, lang in EXT_TO_LANG.items():
        if path.endswith(ext):
            return lang
    return None
