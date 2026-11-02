#!/usr/bin/env python3
"""Repository-local DRAFT entry point, including the E7 quality gate."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/draft"))
from draft.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
