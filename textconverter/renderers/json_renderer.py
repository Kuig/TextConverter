from __future__ import annotations
import json
from ..ast import Node, Document

def to_dict(node):
    if hasattr(node, '__dataclass_fields__'):
        d = {'type': node.__class__.__name__}
        for f in getattr(node, '__dataclass_fields__'):
            val = getattr(node, f)
            if isinstance(val, list):
                d[f] = [to_dict(v) for v in val]
            elif hasattr(val, '__dataclass_fields__'):
                d[f] = to_dict(val)
            else:
                d[f] = val
        return d
    return node

def render_json(doc: Document) -> str:
    """Renders the AST Document to a JSON string, including node types."""
    ast_dict = to_dict(doc)
    return json.dumps(ast_dict, indent=2, ensure_ascii=False)
