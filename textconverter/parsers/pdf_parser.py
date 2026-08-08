from __future__ import annotations
import os
from ..ast import Document, Image
from .markdown_parser import parse_markdown

def parse_pdf(file_path: str, output_dir: str | None = None, image_dir_name: str | None = None, write_images: bool = True, code_parsing: bool = False) -> Document:
    """Parses a PDF into an AST Document using pymupdf4llm layout engine."""
    try:
        import pymupdf4llm
    except ImportError:
        raise ImportError("pymupdf4llm is required to parse PDF files. Install it with `pip install pymupdf4llm`.")
        
    # Extrae il markdown salvando le immagini nella cartella di destinazione
    kwargs = {'write_images': write_images}
    created_dir = None
    if write_images and output_dir:
        target_dir = output_dir
        if image_dir_name:
            target_dir = os.path.join(output_dir, image_dir_name)
            os.makedirs(target_dir, exist_ok=True)
            created_dir = target_dir
        kwargs['image_path'] = target_dir
    md_text = pymupdf4llm.to_markdown(file_path, **kwargs)
    
    # Clean up created_dir if it was created but remains empty (no images in PDF)
    if created_dir and os.path.exists(created_dir):
        try:
            if not os.listdir(created_dir):
                os.rmdir(created_dir)
        except Exception:
            pass
    
    if not write_images:
        import re
        md_text = re.sub(r'\*\*==>\s*picture.*?<==\*\*\n?', '', md_text)
    
    # Lo riconverte tramite il nostro parser garantendo coerenza nell'AST
    doc = parse_markdown(md_text, code_parsing=code_parsing)
    
    # Rimuove il prefisso della cartella dalle immagini affinché il riferimento sia relativo al documento
    def _fix_image_paths(node):
        if isinstance(node, Image):
            basename = os.path.basename(node.src)
            node.src = f"{image_dir_name}/{basename}" if image_dir_name else basename
        if hasattr(node, 'children'):
            for child in node.children:
                _fix_image_paths(child)
        elif hasattr(node, 'items'):
            for item in node.items:
                _fix_image_paths(item)
        elif hasattr(node, 'rows'):
            for row in node.rows:
                _fix_image_paths(row)
        elif hasattr(node, 'cells'):
            for cell in node.cells:
                _fix_image_paths(cell)
        elif hasattr(node, 'content') and isinstance(node.content, list):
            for child in node.content:
                _fix_image_paths(child)
                
    _fix_image_paths(doc)
    return doc
