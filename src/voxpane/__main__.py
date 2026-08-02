"""Enable ``python -m voxpane`` as an alias for the ``voxpane`` CLI."""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
