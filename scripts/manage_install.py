#!/usr/bin/env python3
"""Compatibility installer for a local checkout. Prefer Hermes Skills Hub for distribution."""
import argparse
import os
import shlex
import shutil
import sys
sys.dont_write_bytecode = True
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NATIVE = ROOT / "skills" / "diary-fragment"
sys.path.insert(0, str(NATIVE / "scripts"))
import setup_diary
from diary_common import DiaryError, atomic_write, hermes_home


def copy_code(home):
    destination = home / "skills" / "diary-fragment"
    for source in NATIVE.rglob("*"):
        if not source.is_file() or "__pycache__" in source.parts or source.suffix == ".pyc":
            continue
        target = destination / source.relative_to(NATIVE)
        atomic_write(target, source.read_text(encoding="utf-8"))
    # Stable compatibility launcher; all implementation lives in the skill directory.
    entry = destination / "scripts" / "diary_cli.py"
    launcher = home / "bin" / "hermes-diary"
    atomic_write(launcher, "#!/usr/bin/env bash\nset -euo pipefail\n"
                 f"export HERMES_HOME={shlex.quote(str(home))}\n"
                 f"exec {shlex.quote(sys.executable)} {shlex.quote(str(entry))} \"$@\"\n")
    launcher.chmod(0o700)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local-source compatibility installer; prefer hermes skills install for distribution.")
    parser.add_argument("action", choices=("install", "update", "uninstall"))
    args, rest = parser.parse_known_args(argv)
    try:
        home = hermes_home()
        if args.action == "uninstall":
            code = setup_diary.main(["disable"], skill_root=home / "skills" / "diary-fragment")
            if code == 0:
                print("Schedule stopped. Remove Hub-installed skills with hermes skills uninstall diary-fragment.")
                print("For local-source installs, move the skills/diary-fragment directory out. Data and settings are kept separately.")
            return code
        if args.action == "update" and not (home / "diary" / "config.env").exists():
            raise DiaryError("No existing configuration. Install and configure the diary first.")
        destination = copy_code(home)
        return setup_diary.main(["configure", *rest], skill_root=destination)
    except (DiaryError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
