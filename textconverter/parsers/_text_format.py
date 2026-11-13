"""The conventions of the plain text format, shared by its parser and its renderer."""
from __future__ import annotations

import re
import unicodedata

# The character under a heading of each level (index 0 is level 1), as reStructuredText orders them.
UNDERLINES = '=-~^"\''
# The line above and below the document title.
TITLE_RULE = '='
# A horizontal rule: a line no heading underline can be mistaken for.
RULE = "* * *"
# Spaces before each line of a code block, past the container's own indentation.
CODE_INDENT = 4
# The metadata lines under the title, by Document field.
METADATA_LABELS = {"author": "Author:", "date": "Date:"}
# A footnote marker in the text, and the start of its definition at the end of the document.
NOTE_MARKER = re.compile(r'\[(\d+)\]')
NOTE_DEFINITION = re.compile(r'\[(\d+)\] ')


def char_width(ch: str) -> int:
    """How many columns a character takes in a monospaced font: 2 for wide East Asian ones, 0 for combining marks."""
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1


def display_width(text: str) -> int:
    """How many columns ``text`` takes in a monospaced font."""
    return sum(char_width(ch) for ch in text)
