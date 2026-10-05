"""Entry point PyInstaller freezes into the flexTri app."""

import sys

from flextri.launcher import main

if __name__ == "__main__":
    sys.exit(main())
