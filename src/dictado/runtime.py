"""Process setup shared by the module entry and the frozen executable."""

from __future__ import annotations

import multiprocessing
import os
import sys
from pathlib import Path


def prepare_runtime() -> None:
    multiprocessing.freeze_support()
    if not getattr(sys, "frozen", False):
        return
    exe_dir = Path(sys.executable).resolve().parent
    os.chdir(exe_dir)
