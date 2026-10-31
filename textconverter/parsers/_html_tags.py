"""The sets of HTML tags shared by the page cleanup and the AST parser."""

INLINE_TAGS = frozenset([
    'a', 'b', 'strong', 'i', 'em', 'span', 'code', 'img', 'br', 'sub', 'sup',
    'small', 'mark', 'ins', 'del', 'cite', 'dfn', 'kbd', 'samp', 'var', 'q',
    'time', 'ruby', 'rt', 'rp', 'data', 'abbr', 's', 'strike', 'u', 'font', 'big', 'tt'
])
VOID_TAGS = frozenset([
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
    'link', 'meta', 'param', 'source', 'track', 'wbr'
])
# Block tags that end an open paragraph.
PARAGRAPH_CLOSERS = frozenset([
    'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'table', 'tr', 'td', 'th',
    'pre', 'blockquote', 'hr',
])
