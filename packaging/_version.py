"""Print the package version. Used by packaging/build_mac.sh (CI-safe, no
nested shell quoting)."""

import re
from pathlib import Path

text = Path(__file__).resolve().parents[1].joinpath("src", "dictado", "__init__.py").read_text(encoding="utf-8")
match = re.search(r'__version__ = "(.*)"', text)
print(match.group(1) if match else "")
