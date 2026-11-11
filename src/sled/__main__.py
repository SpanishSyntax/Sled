"""Module entrypoint for `python3 -m sled`."""

import sys

from sled.main import main

if __name__ == "__main__":
    sys.exit(main())
