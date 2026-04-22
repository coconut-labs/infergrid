"""Enable ``python -m kvwarden`` as a CLI entry point.

Equivalent to invoking the installed ``kvwarden`` script, but works even
if the package was installed without console-script shims (e.g. ``uv pip
install --system .`` in a restricted environment).
"""

from __future__ import annotations

from kvwarden.cli import main

if __name__ == "__main__":
    main()
