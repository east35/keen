#!/usr/bin/env python3

import argparse
import os
import plistlib
import sys
from pathlib import Path


REPO_REQUIRED = [
    "AppIcon.icns",
    "iconTemplate.png",
    "iconTemplate@2x.png",
    "assets/app-icon.png",
    "assets/menubar-icon.svg",
    "Keen.spec",
]


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def check_repo_assets(repo_root: Path) -> None:
    missing = []
    for rel in REPO_REQUIRED:
        p = repo_root / rel
        if not p.exists():
            missing.append(rel)
    if missing:
        die("Missing required repo assets:\n" + "\n".join(f"- {m}" for m in missing))


def read_info_plist(app_path: Path) -> dict:
    plist_path = app_path / "Contents" / "Info.plist"
    if not plist_path.exists():
        die(f"Missing Info.plist at {plist_path}")
    with plist_path.open("rb") as f:
        return plistlib.load(f)


def check_built_app(app_path: Path) -> None:
    if not app_path.exists():
        die(f"App not found: {app_path}")

    resources = app_path / "Contents" / "Resources"
    if not resources.exists():
        die(f"Missing Resources dir: {resources}")

    # Menu bar template icons should be in Resources
    for name in ("iconTemplate.png", "iconTemplate@2x.png"):
        if not (resources / name).exists():
            die(f"Missing bundled menu bar icon: {resources / name}")

    # App icon should be referenced by Info.plist and present on disk
    info = read_info_plist(app_path)
    icon_file = info.get("CFBundleIconFile")
    if not icon_file:
        die("Info.plist missing CFBundleIconFile")

    # CFBundleIconFile may omit extension
    candidates = [resources / icon_file]
    if not icon_file.endswith(".icns"):
        candidates.append(resources / f"{icon_file}.icns")

    if not any(c.exists() for c in candidates):
        die(
            "App icon referenced in Info.plist but not found in Resources. "
            f"CFBundleIconFile={icon_file}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify icon assets are present and bundled")
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Path to repo root (default: inferred)",
    )
    parser.add_argument(
        "--app",
        default="dist/Keen.app",
        help="Path to built app bundle (default: dist/Keen.app)",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    app_path = Path(args.app).expanduser().resolve()

    check_repo_assets(repo_root)
    check_built_app(app_path)

    print("OK: icon assets present in repo and bundled in app")


if __name__ == "__main__":
    main()
