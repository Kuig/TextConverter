import os
import json
from ..ast import Document
from .markdown_parser import parse_markdown

def parse_image(source: str) -> Document:
    """Parses an image file by generating a markdown description via Ollama and then parsing that markdown."""
    from ..image_describer import _call_ollama
    if not os.path.exists(source):
        raise ValueError(f"Image file not found: {source}")
        
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    else:
        config = {
            "ollama": {
                "url": "http://localhost:11434/api/generate",
                "model": "gemma4:e2b",
                "prompt": "Analyze the image and reply in structured markdown based on its type: 1) Photo/Drawing/Screenshot/Comic: Accurate description of scene and subjects. 2) Diagram: Detailed description. 3) Text/Formula/Table: Transcription only, strictly preserving the original layout and formatting (e.g. use markdown tables). 4) Chart: Extract key trends. Create a data table ONLY if exact numerical values are clearly readable; do NOT guess or hallucinate numbers."
            }
        }
    
    # We pass an empty base_dir since we provide the absolute/relative path directly in source
    base_dir = ""
    print(f"Generating description for image {source}...")
    markdown_desc, category = _call_ollama(source, base_dir, config)
    
    if markdown_desc and markdown_desc.startswith("[Error"):
        # Create a basic document with the error message
        from ..ast import Paragraph, Text
        doc = Document()
        doc.children.append(Paragraph(children=[Text(content=markdown_desc)]))
        return doc
        
    return parse_markdown(markdown_desc)
