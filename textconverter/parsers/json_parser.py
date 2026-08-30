from __future__ import annotations
import json
import os
from dataclasses import is_dataclass

from ..ast import *
from ..logger import log_warning

def from_dict(d: object) -> object:
    if not isinstance(d, dict):
        return d

    node_type = d.get('type')
    if not node_type:
        return d

    # Get the class from global namespace (imported from ast)
    cls = globals().get(node_type)
    if not cls or not is_dataclass(cls):
        return d

    # Prepare kwargs, tolerating (but reporting) keys the node does not define
    fields = cls.__dataclass_fields__
    kwargs = {}
    unknown = []
    for k, v in d.items():
        if k == 'type':
            continue
        if k not in fields:
            unknown.append(k)
            continue
        if isinstance(v, list):
            kwargs[k] = [from_dict(item) for item in v]
        elif isinstance(v, dict):
            kwargs[k] = from_dict(v)
        else:
            kwargs[k] = v

    if unknown:
        log_warning(f"Ignoring unknown keys for {node_type}: {', '.join(sorted(unknown))}")

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
