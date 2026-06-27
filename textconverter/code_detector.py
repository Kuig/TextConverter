from __future__ import annotations
import re

from textconverter.logger import log_info, log_action, log_warning


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

    # s1 — special characters
    special = re.sub(r'[a-zA-Z0-9\s]', '', text)
    s1 = min(len(special) / tot_words, 1.0)

    # s2 — keyword density
    lower_words = [w.lower().strip('(){};:,."\'') for w in words]
    kw_count = sum(1 for w in lower_words if w in KEYWORDS)
    s2 = kw_count / tot_words

    # s3 — anomalous case (camelCase, snake_case, kebab-case)
    weird = sum(
        1 for w in words
        if re.search(r'[a-z][A-Z]', w)        # camelCase
        or ('_' in w and re.search(r'[a-z]', w))  # snake_case
        or ('-' in w and re.search(r'[a-z]', w))  # kebab-case
    )
    s3 = weird / tot_words

    # s4 — indentation
    indented = sum(
        1 for line in lines
        if re.match(r'^(\t+| {2,})', line) and line.strip()
    )
    s4 = indented / tot_lines

    # combination
    weights = (0.35, 0.25, 0.20, 0.20)
    score = sum(w * s for w, s in zip(weights, (s1, s2, s3, s4)))

    # Exclude common natural language punctuation from s1 for the override check
    special_for_override = re.sub(r'[.,°?!\-_*"\']', '', special)
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

        # Heuristic filter: skip blocks that are clearly not plain paragraphs
        is_candidate = True
        if stripped.startswith("<!--CODEBLOCK:"):
            is_candidate = False
        elif len(stripped.split()) < 3:
            code_indicators = ["=", "(", ")", "[", "]", "{", "}", ":", ";", "import", "print", "def", "return"]
            if not any(indicator in stripped for indicator in code_indicators):
                is_candidate = False
        elif stripped.startswith("```"):
            is_candidate = False
        elif re.match(r"^(#{1,6})\s+", stripped) and "\n" not in stripped:
            is_candidate = False
        elif re.match(r"^[-*+•●○■]\s+", stripped) or re.match(r"^[_*]*\d+(\.\d+)*\.?\s+", stripped):
            is_candidate = False
        elif "|" in stripped and "\n" in stripped:
            lines = stripped.split("\n")
            has_separator = len(lines) >= 2 and "|" in lines[0] and "-" in lines[1]
            is_strict_table = len(lines) >= 1 and all(
                line.strip().startswith("|") and line.strip().endswith("|") for line in lines
            )
            if has_separator or is_strict_table:
                is_candidate = False

        # Exclude blocks consisting entirely of markdown images or links
        if is_candidate:
            temp_stripped = re.sub(r'!\[.*?\]\(.*?\)', '', stripped, flags=re.DOTALL).strip()
            temp_stripped = re.sub(r'\[.*?\]\(.*?\)', '', temp_stripped, flags=re.DOTALL).strip()
            if not temp_stripped:
                is_candidate = False

        if is_candidate:
            is_code, lang = detect_code(block)
            if is_code:
                # Double-pass validation:
                # 1. We strip markdown formatting AND URLs to check if it's genuinely code.
                # 2. We keep the URL in the final text, but remove bold/italic formatting.
                clean_code_block = re.sub(r'\*\*(.*?)\*\*|__(.*?)__', lambda m: m.group(1) or m.group(2) or '', block)
                clean_code_block = re.sub(r'\*(.*?)\*|_(.*?)_', lambda m: m.group(1) or m.group(2) or '', clean_code_block)
                
                # Strip URLs only for the validation check to avoid false positives from URL characters
                stripped_block_for_detection = re.sub(r'https?://\S+', '', clean_code_block)
                
                still_code, still_lang = detect_code(stripped_block_for_detection)
                if still_code:
                    log_action(f"Detected code block (language: {still_lang or lang or 'unknown'}) for: {clean_code_block[:60]}...")
                    classified_blocks.append((True, still_lang or lang, clean_code_block))
                else:
                    classified_blocks.append((False, None, block))
            else:
                classified_blocks.append((False, None, block))
        else:
            classified_blocks.append((False, None, block))

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
