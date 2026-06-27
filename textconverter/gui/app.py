from __future__ import annotations
import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import textconverter.logger as logger
from textconverter.api import save_to_file

logger.set_backend("streamlit")

st.set_page_config(page_title="TextConverter", page_icon="📝", layout="wide")
st.title("📝 TextConverter — Document Conversion")
st.caption("Convert between PDF, HTML, Markdown, and LaTeX formats with optional AI features.")

with st.sidebar:
    st.header("⚙️ Options")
    template = st.selectbox("Template", ["plain", "light-theme", "dark-theme"])
    image_handling = st.selectbox(
        "Image handling",
        ["auto", "describe", "embed", "link", "discard"],
    )
    code_parsing = st.checkbox("Enable code detection")
    extract_html = st.checkbox("Clean HTML & extract main content")
    st.divider()
    st.caption("'describe' requires Ollama running locally.")

if "source" not in st.session_state:
    st.session_state.source = ""
if "output" not in st.session_state:
    st.session_state.output = ""

col1, col2 = st.columns(2)
with col1:
    col_src, col_src_btn = st.columns([4, 1])
    with col_src:
        source = st.text_input("Source file path or URL", value=st.session_state.source, placeholder="DocsInput/document.pdf or https://example.com")
        st.session_state.source = source
    with col_src_btn:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        if st.button("📁", key="source_btn", help="Browse for source file", use_container_width=True):
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.wm_attributes('-topmost', 1)
            
            init_dir = str(Path(st.session_state.source).parent) if st.session_state.source else str(Path.cwd())
            if not Path(init_dir).is_absolute():
                init_dir = str(Path.cwd() / init_dir)
                
            selected_file = filedialog.askopenfilename(
                initialdir=init_dir,
                filetypes=[
                    ("All Supported Files", "*.pdf;*.html;*.md;*.tex;*.json;*.txt"),
                    ("PDF Files", "*.pdf"),
                    ("HTML Files", "*.html"),
                    ("Markdown Files", "*.md"),
                    ("LaTeX Files", "*.tex"),
                    ("JSON Files", "*.json"),
                    ("Text Files", "*.txt"),
                    ("All Files", "*.*")
                ]
            )
            if selected_file:
                try:
                    rel_path = Path(selected_file).relative_to(Path.cwd())
                    st.session_state.source = rel_path.as_posix()
                except ValueError:
                    st.session_state.source = Path(selected_file).as_posix()
                st.rerun()

with col2:
    col_out, col_out_btn = st.columns([4, 1])
    with col_out:
        output = st.text_input("Output file path", value=st.session_state.output, placeholder="DocsOutput/document.md")
        st.session_state.output = output
    with col_out_btn:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        if st.button("💾", key="output_btn", help="Browse for output path", use_container_width=True):
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.wm_attributes('-topmost', 1)
            
            init_dir = str(Path(st.session_state.output).parent) if st.session_state.output else str(Path.cwd())
            if not Path(init_dir).is_absolute():
                init_dir = str(Path.cwd() / init_dir)
                
            selected_file = filedialog.asksaveasfilename(
                initialdir=init_dir,
                filetypes=[
                    ("Markdown Files", "*.md"),
                    ("HTML Files", "*.html"),
                    ("LaTeX Files", "*.tex"),
                    ("JSON Files", "*.json"),
                    ("Text Files", "*.txt"),
                    ("All Files", "*.*")
                ]
            )
            if selected_file:
                try:
                    rel_path = Path(selected_file).relative_to(Path.cwd())
                    st.session_state.output = rel_path.as_posix()
                except ValueError:
                    st.session_state.output = Path(selected_file).as_posix()
                st.rerun()

if st.button("Convert", type="primary", use_container_width=True):
    if not source or not output:
        st.error("Source and output paths are required.")
    else:
        with st.spinner("Converting..."):
            try:
                save_to_file(
                    source, output,
                    template=template,
                    image_handling=image_handling,
                    code_parsing=code_parsing,
                    extract_html=extract_html,
                )
                st.success(f"Saved to: `{output}`")
            except Exception as exc:
                st.error(f"Error: {exc}")
