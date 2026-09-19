#!/usr/bin/env python3
"""Compatibility launcher; the implementation is bundled inside the Hermes skill."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "diary-fragment" / "scripts"))
from diary_cli import main
if __name__ == "__main__":
    sys.exit(main())
