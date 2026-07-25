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
LIST_MARKERS = ("<!-- TIL-START -->", "<!-- TIL-END -->")
COUNT_MARKERS = ("<!-- TIL-COUNT-START -->", "<!-- TIL-COUNT-END -->")


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


def til_count(til_dir: pathlib.Path) -> int:
    """Count every TIL file, matching the `*/*.md` shape used for discovery."""
    out = subprocess.run(
        ["git", "-C", str(til_dir), "ls-files", "*/*.md"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return len([line for line in out.splitlines() if line.strip()])


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


def splice(text: str, markers: tuple[str, str], body: str, inline: bool = False) -> str:
    start, end = markers
    pattern = re.compile(f"{re.escape(start)}.*?{re.escape(end)}", re.DOTALL)
    if not pattern.search(text):
        sys.exit(f"error: README is missing {start}/{end} markers")

    sep = "" if inline else "\n"
    # Lambda replacement so backslashes in TIL titles aren't read as backrefs.
    return pattern.sub(lambda _: f"{start}{sep}{body}{sep}{end}", text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--til-dir", default="til-repo", type=pathlib.Path)
    parser.add_argument("--readme", default="README.md", type=pathlib.Path)
    parser.add_argument("--count", default=5, type=int)
    args = parser.parse_args()

    entries = added_tils(args.til_dir, args.count)
    if not entries:
        sys.exit("error: no TILs found")

    original = args.readme.read_text(encoding="utf-8")
    updated = splice(original, LIST_MARKERS, render(args.til_dir, entries))
    updated = splice(
        updated,
        COUNT_MARKERS,
        f"{til_count(args.til_dir):,}",
        inline=True,
    )

    if updated == original:
        print("no changes")
        return
    args.readme.write_text(updated, encoding="utf-8")
    print("README updated")


if __name__ == "__main__":
    main()
