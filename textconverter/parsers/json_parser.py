from __future__ import annotations
import json
import os
from dataclasses import MISSING, fields

from ..ast import NODE_TYPES, Document
from ..logger import log_warning


def from_dict(d: object) -> object:
    """Rebuild an AST node from its JSON form (the inverse of ``render_json``).

    A dict must carry a ``"type"`` key naming a node class in ``NODE_TYPES``;
    lists are rebuilt item by item and scalars are returned unchanged. Keys the
    node does not define are reported via ``log_warning`` and ignored.

    Args:
        d: A decoded JSON value.

    Returns:
        The rebuilt node, list or scalar.

    Raises:
        ValueError: If a dict has no known ``"type"``, a required field is
            missing, or a child-list field does not hold a list.
    """
    if isinstance(d, list):
        return [from_dict(item) for item in d]
    if not isinstance(d, dict):
        return d

    node_type = d.get("type")
    cls = NODE_TYPES.get(node_type) if isinstance(node_type, str) else None
    if cls is None:
        raise ValueError(f"Unknown or missing node type in JSON: {node_type!r}")

    kwargs = {}
    for f in fields(cls):
        if f.name not in d:
            if f.default is MISSING and f.default_factory is MISSING:
                raise ValueError(f"{node_type} node is missing required field '{f.name}'")
            continue
        value = d[f.name]
        if f.default_factory is list and not isinstance(value, list):
            raise ValueError(f"{node_type}.{f.name} must be a list, got {type(value).__name__}")
        kwargs[f.name] = from_dict(value)

    unknown = sorted(set(d) - {"type"} - {f.name for f in fields(cls)})
    if unknown:
        log_warning(f"Ignoring unknown keys for {node_type}: {', '.join(unknown)}")

    return cls(**kwargs)


def parse_json(source: str) -> Document:
    """Parses a JSON string or file into an AST Document."""
    if os.path.exists(source):
        with open(source, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        try:
            data = json.loads(source)
        except json.JSONDecodeError:
            raise ValueError("Provided source is neither a valid JSON file path nor a valid JSON string.")

    node = from_dict(data)
    if not isinstance(node, Document):
        raise ValueError("Root node of JSON must be a Document.")
    return node
