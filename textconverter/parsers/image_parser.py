from __future__ import annotations
import os
import json
from ..ast import Document
from ..logger import log_action
from .markdown_parser import parse_markdown

def parse_image(source: str) -> Document:
    """Parses an image file by generating a markdown description via Ollama and then parsing that markdown."""
    from ..image_describer import _call_ai
    if not os.path.exists(source):
        raise ValueError(f"Image file not found: {source}")
        
    from ..config import load_config
    config = load_config()
    
    # We pass an empty base_dir since we provide the absolute/relative path directly in source
    base_dir = ""
    log_action(f"Generating description for image {source}...")
    markdown_desc, category = _call_ai(source, base_dir, config)
    
    if markdown_desc and markdown_desc.startswith("[Error"):
        # Create a basic document with the error message
        from ..ast import Paragraph, Text
        doc = Document()
        doc.children.append(Paragraph(children=[Text(content=markdown_desc)]))
        return doc
        
    return parse_markdown(markdown_desc)
