from . import outline, languages

def summarize_file(text, path, max_symbols=20):
    """Cheap extractive summary: header comment + top N symbols."""
    lang = languages.detect(path)
    lines = text.splitlines()
    loc = len(lines)
    header = _leading_comment(lines, lang)
    symbols = outline.extract(text, lang) if lang else []
    top = symbols[:max_symbols]
    more = len(symbols) - len(top)

    out = [f"FILE: {path}  ({loc} loc, lang={lang or 'unknown'})"]
    if header:
        out.append("")
        out.append(header)
    if top:
        out.append("")
        out.append("SYMBOLS:")
        out.append(outline.render(top))
        if more > 0:
            out.append(f"  ... and {more} more")
    return "\n".join(out)

def _leading_comment(lines, lang):
    if not lines:
        return ""
    collected = []
    i = 0
    while i < len(lines) and i < 40:
        s = lines[i].strip()
        if not s:
            if collected:
                break
            i += 1
            continue
        if lang == "py" and s.startswith("#"):
            collected.append(s.lstrip("# ").rstrip())
        elif lang in ("js", "ts", "dart", "rust", "go", "java") and (s.startswith("//") or s.startswith("/*") or s.startswith("*")):
            collected.append(s.lstrip("/* ").rstrip("*/ ").strip())
        else:
            break
        i += 1
    text = " ".join(c for c in collected if c)
    return text[:400]
