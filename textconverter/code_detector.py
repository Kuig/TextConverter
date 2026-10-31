from __future__ import annotations
import re
import string

from textconverter.ast import BlockQuote, CodeBlock, CodeInline, Document, Equation, LineBreak, Node, Paragraph, Text, walk
from textconverter.logger import log_info, log_action, log_warning
from textconverter.parsers._office import parse_box_preamble
from textconverter.parsers.markdown_parser import TABLE_SEPARATOR, parse_inline

# Characters that code is made of: ASCII punctuation only (accented letters, "★" or
# typographic quotes in prose are not code).
_SPECIAL = re.compile('[' + re.escape(string.punctuation) + ']')
# Punctuation that prose uses as much as code, left out of the strong-signal override.
_PROSE_PUNCTUATION = set('.,?!-_*"\':')
# Markdown that only prose holds: a link [text](url) or [text][ref] (not an index as in a[i](x)).
_MD_LINK = re.compile(r'(?<![\w\]])\[[^\]\n]+\](?:\([^)\s]+\)|\[[^\]\n]*\])')
# A bibliography entry or a citation marker leading the block: "[12] A. Author, ...".
_REFERENCE_ENTRY = re.compile(r'^\[\d+\]')
# Short bracketed markers inside prose: citation numbers and the superscripts of PDF text ("[1]", "[★]").
_MARKERS = re.compile(r'(?<!\S)\[[^\]\s]{1,4}\](?!\S)')
_URL_OR_EMAIL = re.compile(r'https?://\S+|\S+@\S+\.\w+')
_CODE_INDICATORS = ("=", "(", ")", "[", "]", "{", "}", ";", "import", "print", "def", "return")
# Up to this many words, a paragraph next to code may be a line of it that does not look like code alone.
_SHORT_LINE_WORDS = 6


KEYWORDS = {
    # universal
    "if", "else", "for", "while", "return", "class", "function", "def",
    "import", "from", "include", "new", "null", "true", "false",
    # types/typing
    "int", "str", "bool", "void", "float", "string", "var", "let", "const",
    # OOP / scope
    "self", "this", "public", "private", "static", "extends", "implements",
    # control flow
    "try", "catch", "throw", "switch", "case", "break", "continue",
    # modern keywords
    "async", "await", "type", "interface", "enum", "struct",
    # HTML/markup
    "div", "span", "href", "src", "class", "id", "style",
    # shell/misc
    "echo", "print", "printf", "select", "where", "from",
}


def is_code(text: str, threshold: float = 0.25) -> tuple[bool, float, dict]:
    """Fast deterministic heuristic to detect programming code.

    Args:
        text: The block of text to evaluate.
        threshold: The classification score threshold.

    Returns:
        A tuple of (is_code, score, metrics).
    """
    lines = text.splitlines()
    words = re.findall(r'\S+', text)
    tot_words = max(len(words), 1)
    tot_lines = max(len(lines), 1)

    # s1: special characters
    special = ''.join(_SPECIAL.findall(text))
    s1 = min(len(special) / tot_words, 1.0)

    # s2: keyword density
    lower_words = [w.lower().strip('(){};:,."\'') for w in words]
    kw_count = sum(1 for w in lower_words if w in KEYWORDS)
    s2 = kw_count / tot_words

    # s3: anomalous case (camelCase, snake_case, kebab-case; "E-mail" and "ApJ" are prose)
    weird = sum(
        1 for w in words
        if (re.search(r'[a-z][A-Z]', w) and len(w.strip(string.punctuation)) >= 4)  # camelCase
        or ('_' in w and re.search(r'[a-z]', w))  # snake_case
        or re.search(r'[a-z]-[a-z]', w)  # kebab-case
    )
    s3 = weird / tot_words

    # s4: indentation
    indented = sum(
        1 for line in lines
        if re.match(r'^(\t+| {2,})', line) and line.strip()
    )
    s4 = indented / tot_lines

    # combination
    weights = (0.35, 0.25, 0.20, 0.20)
    score = sum(w * s for w, s in zip(weights, (s1, s2, s3, s4)))

    # Exclude common natural language punctuation from s1 for the override check
    special_for_override = [c for c in special if c not in _PROSE_PUNCTUATION]
    s1_override = min(len(special_for_override) / tot_words, 1.0)

    # override strong signals
    if s1_override > 0.7 or s4 > 0.8:
        score = max(score, 0.6)

    # Penalize blocks with zero programming keywords and zero anomalous casing
    if s2 == 0.0 and s3 == 0.0:
        score = max(0.0, score - 0.15)

    metrics = {"special_chars": s1, "keywords": s2, "case": s3, "indent": s4}
    return score > threshold, round(score, 3), metrics


def detect_code(block_text: str) -> tuple[bool, str | None]:
    """Determine if a text block is programming code using a fast heuristic.

    This function wraps the heuristic code detector and performs basic language guessing.

    Args:
        block_text: The text block to analyze.

    Returns:
        Tuple of (is_code, language). Language is None if not detected.
    """
    is_code_val, score, metrics = is_code(block_text)
    
    lang = None
    if is_code_val:
        # Fast, keyword-based language guessing
        lower_text = block_text.lower()
        
        # 1. LaTeX
        if "\\begin{" in lower_text or "\\documentclass" in lower_text or "\\usepackage" in lower_text:
            lang = "latex"
        # 2. HTML / XML
        elif "<html>" in lower_text or "</div>" in lower_text or "<!doctype" in lower_text or "xmlns=" in lower_text:
            lang = "html"
        # 3. SQL
        elif "select " in lower_text and "from " in lower_text:
            lang = "sql"
        # 4. JSON
        elif lower_text.startswith("{") and lower_text.endswith("}") and ":" in lower_text:
            lang = "json"
        # 5. PHP
        elif "<?php" in lower_text or "$this->" in lower_text:
            lang = "php"
        # 6. Python
        elif "def " in lower_text or "import " in lower_text or "print(" in lower_text or "elif " in lower_text:
            lang = "python"
        # 7. Rust
        elif "fn " in lower_text or "let mut " in lower_text or "impl " in lower_text:
            lang = "rust"
        # 8. Go
        elif "package main" in lower_text or "func " in lower_text:
            lang = "go"
        # 9. C++ / C
        elif "#include <" in lower_text or "std::" in lower_text or "cout << " in lower_text:
            lang = "cpp"
        # 10. Java / C#
        elif "public class " in lower_text or "using system;" in lower_text or "namespace " in lower_text or "system.out.print" in lower_text or "console.write" in lower_text:
            lang = "java" if "system.out.print" in lower_text or "public static void main" in lower_text else "csharp"
        # 11. TypeScript
        elif "interface " in lower_text and (": string" in lower_text or ": number" in lower_text or "readonly " in lower_text):
            lang = "typescript"
        # 12. JavaScript
        elif "document.get" in lower_text or "const " in lower_text or "let " in lower_text or "function " in lower_text or "console.log" in lower_text:
            lang = "javascript"
        # 13. CSS
        elif "margin:" in lower_text and "padding:" in lower_text and ("display:" in lower_text or "color:" in lower_text):
            lang = "css"
        # 14. YAML
        elif lower_text.startswith("---") or ("\n  " in block_text and ":" in lower_text and not ("{" in lower_text or "[" in lower_text)):
            lang = "yaml"
        # 15. Shell consoles & Scripts (PowerShell, Bash, Batch, CLI)
        elif "get-" in lower_text or "write-host" in lower_text or "write-output" in lower_text or "write-error" in lower_text:
            lang = "powershell"
        elif "pip install" in lower_text or "npm install" in lower_text or "git clone" in lower_text or "docker run" in lower_text or "cargo build" in lower_text:
            lang = "bash"
        elif "echo " in lower_text or "ls -l" in lower_text or "sudo " in lower_text or "chmod " in lower_text or "mkdir " in lower_text:
            lang = "bash"

    return is_code_val, lang


def _is_candidate(stripped: str) -> bool:
    """Whether a block may be unfenced code: not a structure Markdown already reads, and not plain prose."""
    lines = stripped.split("\n")
    if stripped.startswith(("<!--CODEBLOCK:", "```", "~~~")):
        return False
    if re.match(r"^(#{1,6})\s+", stripped) and "\n" not in stripped:
        return False
    if re.match(r"^[-*+•●○■]\s+", stripped) or re.match(r"^[_*]*\d+(\.\d+)*\.?\s+", stripped):
        return False
    if all(line.lstrip().startswith(">") for line in lines):  # a quote
        return False
    if _REFERENCE_ENTRY.match(stripped) or _MD_LINK.search(stripped):
        return False
    if "|" in stripped and "\n" in stripped:
        has_separator = len(lines) >= 2 and "|" in lines[0] and bool(TABLE_SEPARATOR.match(lines[1]))
        is_strict_table = all(line.strip().startswith("|") and line.strip().endswith("|") for line in lines)
        if has_separator or is_strict_table:
            return False
    # A short line, or one line that introduces what follows ("List:"), needs a code indicator
    # outside its code spans
    if len(stripped.split()) < 3 or (len(lines) == 1 and stripped.endswith(":")):
        outside_spans = re.sub(r'`+[^`]*`+', '', stripped)
        if not any(indicator in outside_spans for indicator in _CODE_INDICATORS):
            return False
    return True


def _prose_copy(block: str) -> str:
    """The block as a reader of the Markdown sees it, line by line, for the second detection check.

    Emphasis markers, link syntax, code spans, inline math, URLs, e-mail
    addresses and short bracketed markers (``[1]``) are left out, since their
    characters look like code in prose; indentation is kept.
    """
    lines = []
    for line in block.split("\n"):
        nodes = parse_inline(line.strip())
        shown = ''.join(n.content for node in nodes for n in walk(node)
                        if isinstance(n, Text) and not isinstance(node, (CodeInline, Equation)))
        shown = _MARKERS.sub('', _URL_OR_EMAIL.sub('', shown))
        lines.append(line[:len(line) - len(line.lstrip())] + shown.strip())
    return "\n".join(lines)


def _code_block(block: str) -> tuple[bool, str | None]:
    """Whether a block is unfenced code, and its language.

    Second check on the text a reader would see (the block itself is kept as
    is: removing "emphasis" from real code turned __init__ into init).
    """
    if not _is_candidate(block.strip()):
        return False, None
    is_code, lang = detect_code(block)
    if not is_code:
        return False, None
    still_code, still_lang = detect_code(_prose_copy(block))
    return still_code, (still_lang or lang) if still_code else None


def pre_process_markdown_code(text: str) -> str:
    """Detect and wrap code blocks in a Markdown text using a heuristic algorithm.

    Splits the text into blocks, uses a deterministic heuristic to classify
    paragraph candidates, merges consecutive detected code blocks, and returns
    the modified text.

    Args:
        text: Raw Markdown text to process.

    Returns:
        Modified Markdown text with heuristic-detected code blocks wrapped in fences.
    """
    blocks = re.split(r"\n\s*\n", text)
    classified_blocks: list[tuple[bool, str | None, str]] = []

    log_info(f"Analyzing {len(blocks)} candidate blocks for semantic code detection...")

    for block in blocks:
        stripped = block.strip()
        if not stripped:
            classified_blocks.append((False, None, block))
            continue

        is_code, lang = _code_block(block)
        if is_code:
            log_action(f"Detected code block (language: {lang or 'unknown'}) for: {block[:60]}...")
        classified_blocks.append((is_code, lang, block))

    # Merge consecutive code blocks
    merged_blocks: list[str] = []
    current_code_group: list[str] = []
    current_lang: str | None = None

    for is_code, lang, block_content in classified_blocks:
        if is_code:
            current_code_group.append(block_content)
            if lang and not current_lang:
                current_lang = lang
        else:
            if current_code_group:
                merged_code = "\n\n".join(current_code_group)
                lang_str = current_lang if current_lang else ""
                merged_blocks.append(f"```{lang_str}\n{merged_code}\n```")
                current_code_group = []
                current_lang = None
            merged_blocks.append(block_content)

    # Flush remaining code group
    if current_code_group:
        merged_code = "\n\n".join(current_code_group)
        lang_str = current_lang if current_lang else ""
        merged_blocks.append(f"```{lang_str}\n{merged_code}\n```")

    return "\n\n".join(merged_blocks)


def _plain_paragraph(node: Node) -> str | None:
    """The text of a paragraph of unformatted text and line breaks; None for anything else."""
    if not isinstance(node, Paragraph) or not node.children:
        return None
    parts = []
    for child in node.children:
        if isinstance(child, LineBreak):
            parts.append("\n")
        elif isinstance(child, Text) and not (child.bold or child.italic or child.strikethrough or child.script):
            parts.append(child.content)
        else:
            return None
    return "".join(parts)


def _is_code_paragraph(text: str) -> bool:
    """Whether a paragraph is code: ``_code_block``, with a keyword or indentation besides.

    Slides are full of short text heavy in punctuation and capitals ("Parameters;",
    "the runtime (AOT/JIT)") that the punctuation alone would pass.
    """
    if not _code_block(text)[0]:
        return False
    metrics = is_code(text)[2]
    return metrics["keywords"] > 0 or metrics["indent"] > 0


def _absorb_short_lines(texts: list[str | None], code: list[bool]) -> None:
    """Mark as code the short paragraphs around code: lines like ``x = 1`` or ``else:`` are not code alone.

    One line per paragraph is how code usually sits in Word and PowerPoint.
    From a line of code, the short paragraphs that follow (and, likewise, those
    before it) join up to the last one with a code indicator, or all of them
    when they end at more code.
    """
    def short(i: int) -> bool:
        return texts[i] is not None and 0 < len(texts[i].split()) <= _SHORT_LINE_WORDS

    last = len(texts) - 1
    for step, starts in ((1, range(last + 1)), (-1, range(last, -1, -1))):
        for start in starts:
            if not code[start]:
                continue
            i, join_to = start + step, None
            while 0 <= i <= last and not code[i] and short(i):
                if any(indicator in texts[i] for indicator in _CODE_INDICATORS):
                    join_to = i
                i += step
            if 0 <= i <= last and code[i]:
                join_to = i
            if join_to is not None:
                for i in range(start, join_to + step, step):
                    code[i] = True


def _without_indentation(block: Node) -> Node:
    """The block with no leading spaces, as a paragraph that is not code has."""
    if isinstance(block, Paragraph) and block.children and isinstance(block.children[0], Text):
        block.children[0].content = block.children[0].content.lstrip()
    return block


def _fence_blocks(blocks: list[Node]) -> list[Node]:
    """The blocks with each run of code paragraphs merged into a CodeBlock."""
    texts = [_plain_paragraph(block) for block in blocks]
    code = [text is not None and _is_code_paragraph(text) for text in texts]
    _absorb_short_lines(texts, code)
    fenced: list[Node] = []
    run: list[str] = []
    for block, text, is_code in zip([*blocks, None], [*texts, None], [*code, False]):
        if is_code:
            run.append(text)
            continue
        if run:
            source = "\n".join(run).rstrip()
            log_action(f"Detected code block for: {source[:60]}...")
            fenced.append(CodeBlock(code=source, language=detect_code(source)[1]))
            run = []
        if block is not None:
            fenced.append(_without_indentation(block))
    return fenced


def fence_code_paragraphs(doc: Document) -> None:
    """Turn the unformatted paragraphs that read as code into code blocks, in place.

    For sources without Markdown text to read (Word, PowerPoint). Only the
    document's blocks and its quotes are looked at, and only paragraphs of
    plain text; the frame line of a text box stays.
    """
    doc.children[:] = _fence_blocks(doc.children)
    for quote in doc.children:
        if isinstance(quote, BlockQuote) and quote.children:
            first = _plain_paragraph(quote.children[0]) or ""
            kept = 1 if parse_box_preamble(first) else 0
            quote.children[kept:] = _fence_blocks(quote.children[kept:])
