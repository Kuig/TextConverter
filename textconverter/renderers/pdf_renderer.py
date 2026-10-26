"""Print rendered HTML to PDF.

The preferred engine is an installed Chromium browser (Edge or Chrome) in
headless mode: full CSS support and MathJax-typeset formulas, with no Python
dependency. Without one, PyMuPDF's Story (already a dependency) lays the HTML
out itself, with a CSS subset and formulas left as TeX source.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from ..logger import log_action, log_warning

PDF_ENGINES = ("auto", "browser", "story")
# Virtual time the browser may spend loading scripts (MathJax) before printing.
_BROWSER_SCRIPT_BUDGET_MS = 15000
_BROWSER_TIMEOUT_S = 120
_STORY_PAGE = "a4"
_STORY_MARGIN_PT = 50
# Story ignores `overflow`, so long code lines would run off the page.
_STORY_CSS = "pre { white-space: pre-wrap; }"

_WINDOWS_BROWSERS = (
    r"Microsoft\Edge\Application\msedge.exe",
    r"Google\Chrome\Application\chrome.exe",
)
_MAC_BROWSERS = (
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)
_PATH_BROWSERS = (
    "msedge", "microsoft-edge", "google-chrome", "google-chrome-stable",
    "chromium", "chromium-browser", "chrome",
)


def find_browser() -> str | None:
    """Return the path of an installed Edge, Chrome or Chromium, or None."""
    for root_var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        root = os.environ.get(root_var)
        for relative in _WINDOWS_BROWSERS if root else ():
            candidate = os.path.join(root, relative)
            if os.path.isfile(candidate):
                return candidate
    for candidate in _MAC_BROWSERS:
        if os.path.isfile(candidate):
            return candidate
    for name in _PATH_BROWSERS:
        found = shutil.which(name)
        if found:
            return found
    return None


def render_pdf(html: str, output_path: str, base_dir: str | None = None, engine: str = "auto") -> None:
    """Write ``html`` as a PDF file.

    Args:
        html: A complete HTML document; images should be embedded as data URLs.
        output_path: Destination PDF path.
        base_dir: Directory that relative image paths resolve against.
        engine: ``"auto"`` uses a browser when one is installed and falls back
            to Story if there is none or printing fails; ``"browser"`` and
            ``"story"`` force one engine.

    Raises:
        ValueError: If ``engine`` is unknown.
        RuntimeError: If ``engine="browser"`` and no browser is found or printing fails.
    """
    if engine not in PDF_ENGINES:
        raise ValueError(f"Unknown PDF engine '{engine}'; expected one of {', '.join(PDF_ENGINES)}.")
    if engine != "story":
        browser = find_browser()
        if browser:
            try:
                _print_with_browser(browser, html, output_path, base_dir)
                return
            except RuntimeError as exc:
                if engine == "browser":
                    raise
                log_warning(f"Browser PDF printing failed, using the built-in renderer: {exc}")
        elif engine == "browser":
            raise RuntimeError("No Edge, Chrome or Chromium installation found.")
        else:
            log_warning("No Edge, Chrome or Chromium found: using the built-in PDF renderer (simpler layout).")
    _render_with_story(html, output_path, base_dir)


def _print_with_browser(browser: str, html: str, output_path: str, base_dir: str | None) -> None:
    """Print the HTML with a headless browser in an isolated temporary profile.

    The page is written into ``base_dir`` (when given) so relative image paths resolve.
    """
    log_action(f"Printing PDF with {os.path.basename(browser)}...")
    with tempfile.TemporaryDirectory(prefix="textconverter_print_") as tmp:
        page = Path(base_dir or tmp) / "textconverter_print.html"
        page.write_text(html, encoding="utf-8")
        pdf = Path(tmp) / "document.pdf"
        command = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-pdf-header-footer",
            f"--virtual-time-budget={_BROWSER_SCRIPT_BUDGET_MS}",
            f"--user-data-dir={Path(tmp) / 'profile'}",
            f"--print-to-pdf={pdf}",
            page.as_uri(),
        ]
        try:
            subprocess.run(command, capture_output=True, timeout=_BROWSER_TIMEOUT_S, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(str(exc)) from exc
        finally:
            page.unlink(missing_ok=True)
        if not pdf.is_file() or pdf.stat().st_size == 0:
            raise RuntimeError("the browser produced no PDF")
        shutil.move(str(pdf), output_path)


def _render_with_story(html: str, output_path: str, base_dir: str | None) -> None:
    """Lay the HTML out with PyMuPDF's Story: a CSS subset, formulas stay TeX."""
    import pymupdf

    log_action("Rendering PDF with the built-in renderer...")
    if 'class="math' in html:
        log_warning("The built-in PDF renderer cannot typeset formulas: they are shown as TeX source.")
    story = pymupdf.Story(html=html, user_css=_STORY_CSS, archive=base_dir)
    mediabox = pymupdf.paper_rect(_STORY_PAGE)
    margin = _STORY_MARGIN_PT
    content_area = mediabox + (margin, margin, -margin, -margin)
    writer = pymupdf.DocumentWriter(output_path)
    try:
        more = True
        while more:
            device = writer.begin_page(mediabox)
            more, _ = story.place(content_area)
            story.draw(device)
            writer.end_page()
    finally:
        writer.close()
