"""Fail when a release tag does not match dictado.__version__."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dictado import __version__
from dictado.updates import release_tag_matches


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: check_release_tag.py <tag>", file=sys.stderr)
        return 2
    tag = args[0]
    if release_tag_matches(tag):
        print(f"{tag} coincide con dictado.__version__ ({__version__})")
        return 0
    print(f"tag {tag} no coincide con dictado.__version__ ({__version__})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
