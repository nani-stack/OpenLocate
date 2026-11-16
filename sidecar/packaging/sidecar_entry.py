"""Entry point of the standalone helper built by packaging/build.py."""

import sys

from openlocate.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
