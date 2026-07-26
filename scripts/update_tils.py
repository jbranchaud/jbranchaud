#!/usr/bin/env python3
"""Splice the N most recently *added* TILs into README.md.

Uses `git log --diff-filter=A` against a local clone of the TIL repo so that
edits to existing TILs never resurface them.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import re
import shutil
import subprocess
import sys
import xml.sax.saxutils as saxutils

TIL_REPO_URL = "https://github.com/jbranchaud/til"
TIL_BRANCH = "master"
LIST_MARKERS = ("<!-- TIL-START -->", "<!-- TIL-END -->")
COUNT_MARKERS = ("<!-- TIL-COUNT-START -->", "<!-- TIL-COUNT-END -->")
TOP_MARKERS = ("<!-- TIL-TOP-START -->", "<!-- TIL-TOP-END -->")

# Brand accent per category; anything unlisted falls back to GitHub's gray.
BRAND = {
    "rails": "#D30001",
    "unix": "#4EAA25",
    "postgres": "#4169E1",
    "ruby": "#CC342D",
    "vim": "#019733",
    "git": "#F05032",
    "javascript": "#F7DF1E",
    "react": "#61DAFB",
    "python": "#3776AB",
    "elixir": "#4B275F",
    "mac": "#A2AAAD",
    "tmux": "#1BB91F",
    "workflow": "#8957E5",
    "reason": "#DD4B39",
    "go": "#00ADD8",
    "css": "#663399",
    "typescript": "#3178C6",
    "devops": "#326CE5",
    "clojure": "#5881D8",
    "chrome": "#4285F4",
}
BRAND_FALLBACK = "#6E7781"

# (background, border, label, count) per README color scheme.
THEMES = {
    "light": ("#F6F8FA", "#D0D7DE", "#57606A", "#1F2328"),
    "dark": ("#161B22", "#30363D", "#8B949E", "#E6EDF3"),
}
TILE_W, TILE_H = 132, 52


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


def til_paths(til_dir: pathlib.Path) -> list[str]:
    """Every TIL file, matching the `*/*.md` shape used for discovery."""
    out = subprocess.run(
        ["git", "-C", str(til_dir), "ls-files", "*/*.md"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def top_categories(paths: list[str], count: int) -> list[tuple[str, int]]:
    """Return [(category, til_count)] for the `count` biggest directories.

    Ties break alphabetically so the order only moves when the numbers do.
    """
    counts = collections.Counter(path.split("/", 1)[0] for path in paths)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:count]


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


def tile_svg(category: str, count: int, theme: str) -> str:
    """One name plate: brand-colored edge, category label, count as numeral."""
    background, border, label_fill, count_fill = THEMES[theme]
    accent = BRAND.get(category, BRAND_FALLBACK)
    label = saxutils.escape(category.upper())
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{TILE_W}" \
height="{TILE_H}" viewBox="0 0 {TILE_W} {TILE_H}" role="img" \
aria-label="{label}: {count} TILs">
  <clipPath id="card">
    <rect x="0" y="0" width="{TILE_W}" height="{TILE_H}" rx="8"/>
  </clipPath>
  <g clip-path="url(#card)">
    <rect x="0" y="0" width="{TILE_W}" height="{TILE_H}" fill="{background}"/>
    <rect x="0" y="0" width="4" height="{TILE_H}" fill="{accent}"/>
  </g>
  <rect x="0.5" y="0.5" width="{TILE_W - 1}" height="{TILE_H - 1}" rx="7.5"
        fill="none" stroke="{border}"/>
  <g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">
    <text x="17" y="21" font-size="10.5" letter-spacing="0.7"
          fill="{label_fill}">{label}</text>
    <text x="17" y="42" font-size="19" font-weight="600"
          fill="{count_fill}">{count:,}</text>
  </g>
</svg>
"""


def render_tiles(entries: list[tuple[str, int]], assets: pathlib.Path) -> str:
    """Write a light/dark SVG pair per category, return the linked markup.

    The count rides in the filename so GitHub's image proxy can't serve a
    stale tile after the numbers move.
    """
    shutil.rmtree(assets, ignore_errors=True)
    assets.mkdir(parents=True, exist_ok=True)

    lines = []
    for category, count in entries:
        paths = {}
        for theme in THEMES:
            name = f"{category}-{count}-{theme}.svg"
            (assets / name).write_text(
                tile_svg(category, count, theme), encoding="utf-8"
            )
            paths[theme] = f"{assets.as_posix()}/{name}"
        lines.append(
            f'<a href="{TIL_REPO_URL}/tree/{TIL_BRANCH}/{category}">'
            f"<picture>"
            f'<source media="(prefers-color-scheme: dark)" srcset="{paths["dark"]}">'
            f'<img alt="{category}: {count} TILs" src="{paths["light"]}">'
            f"</picture></a>"
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
    parser.add_argument("--top", default=10, type=int)
    parser.add_argument("--assets", default="assets/tiles", type=pathlib.Path)
    args = parser.parse_args()

    entries = added_tils(args.til_dir, args.count)
    if not entries:
        sys.exit("error: no TILs found")

    paths = til_paths(args.til_dir)
    original = args.readme.read_text(encoding="utf-8")
    updated = splice(original, LIST_MARKERS, render(args.til_dir, entries))
    updated = splice(updated, COUNT_MARKERS, f"{len(paths):,}", inline=True)
    updated = splice(
        updated,
        TOP_MARKERS,
        render_tiles(top_categories(paths, args.top), args.assets),
    )

    if updated == original:
        print("no changes")
        return
    args.readme.write_text(updated, encoding="utf-8")
    print("README updated")


if __name__ == "__main__":
    main()
