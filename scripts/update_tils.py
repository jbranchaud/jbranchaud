#!/usr/bin/env python3
"""Splice the N most recently *added* TILs into README.md.

Uses `git log --diff-filter=A` against a local clone of the TIL repo so that
edits to existing TILs never resurface them.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

TIL_REPO_URL = "https://github.com/jbranchaud/til"
TIL_BRANCH = "master"
START_MARKER = "<!-- TIL-START -->"
END_MARKER = "<!-- TIL-END -->"


def added_tils(til_dir: pathlib.Path, count: int) -> list[tuple[str, str]]:
    """Return [(path, iso_date)] for the `count` most recently added TIL files."""
    out = subprocess.run(
        [
            "git",
            "-C",
            str(til_dir),
            "log",
            "--diff-filter=A",
            "--name-only",
            "--pretty=format:%x00%aI",
            "--",
            "*/*.md",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    results: list[tuple[str, str]] = []
    date = ""
    for line in out.splitlines():
        if line.startswith("\x00"):
            date = line[1:]
            continue
        path = line.strip()
        if not path:
            continue
        # A file can be added, deleted, then re-added; keep the newest entry.
        if any(path == p for p, _ in results):
            continue
        # Skip files that no longer exist (renamed or deleted since).
        if not (til_dir / path).is_file():
            continue
        results.append((path, date))
        if len(results) == count:
            break
    return results


def title_for(til_dir: pathlib.Path, path: str) -> str:
    for line in (til_dir / path).read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return pathlib.Path(path).stem.replace("-", " ").title()


def render(til_dir: pathlib.Path, entries: list[tuple[str, str]]) -> str:
    lines = []
    for path, date in entries:
        category = path.split("/", 1)[0]
        url = f"{TIL_REPO_URL}/blob/{TIL_BRANCH}/{path}"
        lines.append(
            f"- [{title_for(til_dir, path)}]({url}) "
            f"<sup>`{category}` · {date[:10]}</sup>"
        )
    return "\n".join(lines)


def splice(readme: pathlib.Path, body: str) -> bool:
    original = readme.read_text(encoding="utf-8")
    pattern = re.compile(
        f"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}", re.DOTALL
    )
    if not pattern.search(original):
        sys.exit(f"error: {readme} is missing {START_MARKER}/{END_MARKER} markers")

    updated = pattern.sub(f"{START_MARKER}\n{body}\n{END_MARKER}", original)
    if updated == original:
        return False
    readme.write_text(updated, encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--til-dir", default="til-repo", type=pathlib.Path)
    parser.add_argument("--readme", default="README.md", type=pathlib.Path)
    parser.add_argument("--count", default=5, type=int)
    args = parser.parse_args()

    entries = added_tils(args.til_dir, args.count)
    if not entries:
        sys.exit("error: no TILs found")

    changed = splice(args.readme, render(args.til_dir, entries))
    print("README updated" if changed else "no changes")


if __name__ == "__main__":
    main()
