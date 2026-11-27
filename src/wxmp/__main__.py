# -*- coding: utf-8 -*-
"""Allow ``python -m wxmp``."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())