#!/usr/bin/env python3
"""Compatibility entry point: same configuration, lock and journal as the CLI."""
import os
import sys
sys.dont_write_bytecode = True

from diary_cli import main

if __name__ == "__main__":
    sys.exit(main(["resend" if os.environ.get("FORCE_SEND") == "1" else "send", *sys.argv[1:]]))
