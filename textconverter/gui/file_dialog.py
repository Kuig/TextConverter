"""Native open/save file dialogs for the Streamlit GUI.

Each dialog runs tkinter in a short-lived child process. Streamlit executes the
script on a different thread at every rerun, and a Tk interpreter touched or
garbage-collected from a thread other than its creator fails with "main thread
is not in main loop"; a separate process never shares Tcl with those threads.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

_DIALOG_SCRIPT = """
import json, sys, tkinter as tk
from tkinter import filedialog
args = json.loads(sys.argv[1])
root = tk.Tk()
root.withdraw()
root.wm_attributes("-topmost", 1)
ask = filedialog.asksaveasfilename if args["save"] else filedialog.askopenfilename
selected = ask(initialdir=args["initial_dir"], filetypes=[tuple(t) for t in args["filetypes"]])
root.destroy()
sys.stdout.write(selected or "")
"""


def ask_path(current: str, filetypes: list[tuple[str, str]], save: bool = False) -> str | None:
    """Show a native file dialog and return the chosen path, or None if cancelled.

    Args:
        current: The path currently in the field; its folder opens first.
        filetypes: ``(label, pattern)`` pairs, e.g. ``("PDF Files", "*.pdf")``.
        save: Show a save-as dialog instead of an open dialog.

    Returns:
        The chosen path, relative to the working directory when it lies inside
        it, as a POSIX string; None when the dialog was cancelled or failed.
    """
    initial_dir = Path.cwd() / Path(current).parent if current else Path.cwd()
    args = {"initial_dir": str(initial_dir), "filetypes": filetypes, "save": save}
    try:
        result = subprocess.run(
            [sys.executable, "-c", _DIALOG_SCRIPT, json.dumps(args)],
            capture_output=True, text=True, check=False,
        )
    except OSError:
        return None
    selected = result.stdout.strip()
    if not selected:
        return None
    try:
        return Path(selected).relative_to(Path.cwd()).as_posix()
    except ValueError:
        return Path(selected).as_posix()
