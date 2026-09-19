#!/usr/bin/env python3
import os
import sys
sys.dont_write_bytecode = True
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "diary-fragment" / "scripts"))
from diary_cli import main
if __name__ == "__main__":
    sys.exit(main(["resend" if os.environ.get("FORCE_SEND") == "1" else "send", *sys.argv[1:]]))
