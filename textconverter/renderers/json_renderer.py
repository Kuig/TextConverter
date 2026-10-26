from __future__ import annotations
import json
from dataclasses import fields, is_dataclass
from ..ast import Document

def to_dict(node: object) -> object:
    """Convert an AST node (or list, or scalar) to plain JSON-ready values.

    Each node becomes a dict with a ``"type"`` key holding its class name
    (see ``ast.NODE_TYPES``) plus one key per dataclass field.

    Args:
        node: A node, a list of nodes, or a scalar field value.

    Returns:
        The JSON-ready value.
    """
    if isinstance(node, list):
        return [to_dict(v) for v in node]
    if is_dataclass(node):
        d = {'type': node.__class__.__name__}
        for f in fields(node):
            d[f.name] = to_dict(getattr(node, f.name))
        return d
    return node

def render_json(doc: Document) -> str:
    """Renders the AST Document to a JSON string, including node types."""
    ast_dict = to_dict(doc)
    return json.dumps(ast_dict, indent=2, ensure_ascii=False)
