from __future__ import annotations
import json
import os
from ..ast import *

def from_dict(d):
    if not isinstance(d, dict):
        return d
        
    node_type = d.get('type')
    if not node_type:
        return d
        
    # Get the class from global namespace (imported from ast)
    cls = globals().get(node_type)
    if not cls:
        return d
        
    # Prepare kwargs
    kwargs = {}
    for k, v in d.items():
        if k == 'type':
            continue
        if isinstance(v, list):
            kwargs[k] = [from_dict(item) for item in v]
        elif isinstance(v, dict):
            kwargs[k] = from_dict(v)
        else:
            kwargs[k] = v
            
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
