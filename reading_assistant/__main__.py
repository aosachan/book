from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path


def _configure_bundled_tk() -> None:
    # Keep a short SUBST/launcher path intact; resolve() expands it back to the
    # long workspace path that Tcl cannot initialize in some sandboxes.
    runtime = Path(os.path.abspath(sys.executable)).parent
    tcl = runtime / "tcl" / "tcl8.6"
    tk = runtime / "tcl" / "tk8.6"
    if (tcl / "init.tcl").exists() and (tk / "tk.tcl").exists():
        # Tcl on this portable Windows runtime requires slash-normalized paths.
        os.environ.setdefault("TCL_LIBRARY", tcl.as_posix())
        os.environ.setdefault("TK_LIBRARY", tk.as_posix())


_configure_bundled_tk()

import tkinter as tk

from .ui import ReadingAssistantApp, run_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Reading Assistant")
    parser.add_argument("--smoke-test", action="store_true", help="UIを構築して即終了する")
    args = parser.parse_args()
    if not args.smoke_test:
        run_app()
        return
    with tempfile.TemporaryDirectory(prefix="lra-smoke-") as temp_dir:
        os.environ["LRA_DATA_DIR"] = temp_dir
        root = tk.Tk()
        root.withdraw()
        app = ReadingAssistantApp(root)
        root.update_idletasks()
        app.hotkey.unregister()
        app.memory.close()
        root.destroy()
        print("UI_SMOKE_OK")


if __name__ == "__main__":
    main()
