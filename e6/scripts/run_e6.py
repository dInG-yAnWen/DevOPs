#!/usr/bin/env python3
"""Repository-local entry point for the DRAFT service CLI (Python stdlib)."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "draft"))

from draft.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
