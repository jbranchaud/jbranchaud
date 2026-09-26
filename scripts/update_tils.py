#!/usr/bin/env python3
"""Splice the N most recently *added* TILs into README.md.

Uses `git log --diff-filter=A` against a local clone of the TIL repo so that
edits to existing TILs never resurface them. Also splices in the latest
blogmarks from the VisualMode Atom feed.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import datetime
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
import xml.sax.saxutils as saxutils

TIL_REPO_URL = "https://github.com/jbranchaud/til"
TIL_BRANCH = "master"
LIST_MARKERS = ("<!-- TIL-START -->", "<!-- TIL-END -->")
COUNT_MARKERS = ("<!-- TIL-COUNT-START -->", "<!-- TIL-COUNT-END -->")
TOP_MARKERS = ("<!-- TIL-TOP-START -->", "<!-- TIL-TOP-END -->")
BLOGMARK_MARKERS = ("<!-- BLOGMARKS-START -->", "<!-- BLOGMARKS-END -->")
BLOGMARK_FEED_URL = "https://still.visualmode.dev/feed"
ATOM = "{http://www.w3.org/2005/Atom}"

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


@dataclasses.dataclass(frozen=True)
class Theme:
    """Tile colors for one README color scheme."""

    background: str
    border: str
    label: str
    count: str


THEMES = {
    "light": Theme("#F6F8FA", "#D0D7DE", "#57606A", "#1F2328"),
    "dark": Theme("#161B22", "#30363D", "#8B949E", "#E6EDF3"),
}
TILE_W, TILE_H = 132, 52


@dataclasses.dataclass(frozen=True)
class Til:
    path: str
    added: datetime.date

    @property
    def category(self) -> str:
        return self.path.split("/", 1)[0]

    @property
    def url(self) -> str:
        return f"{TIL_REPO_URL}/blob/{TIL_BRANCH}/{self.path}"


@dataclasses.dataclass(frozen=True)
class TopicCount:
    category: str
    count: int


@dataclasses.dataclass(frozen=True)
class Blogmark:
    title: str
    url: str
    published: datetime.datetime
    tags: list[str]


def added_tils(til_dir: pathlib.Path, count: int) -> list[Til]:
    """Return the `count` most recently added TIL files, newest first."""
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

    results: list[Til] = []
    date = datetime.date.min
    for line in out.splitlines():
        if line.startswith("\x00"):
            date = datetime.datetime.fromisoformat(line[1:]).date()
            continue
        path = line.strip()
        if not path:
            continue
        # A file can be added, deleted, then re-added; keep the newest entry.
        if any(path == til.path for til in results):
            continue
        # Skip files that no longer exist (renamed or deleted since).
        if not (til_dir / path).is_file():
            continue
        results.append(Til(path, date))
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


def top_categories(paths: list[str], count: int) -> list[TopicCount]:
    """Return the `count` biggest TIL directories.

    Ties break alphabetically so the order only moves when the numbers do.
    """
    counts = collections.Counter(path.split("/", 1)[0] for path in paths)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [TopicCount(category, n) for category, n in ranked[:count]]


def title_for(til_dir: pathlib.Path, path: str) -> str:
    for line in (til_dir / path).read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return pathlib.Path(path).stem.replace("-", " ").title()


def link_item(title: str, url: str, tags: list[str], date: datetime.date) -> str:
    """One README list line: linked title, then tags and date in small text."""
    # Brackets in titles would break the markdown link.
    title = title.replace("[", "\\[").replace("]", "\\]")
    meta = " ".join(f"`{tag}`" for tag in tags)
    meta = f"{meta} · {date.isoformat()}" if meta else date.isoformat()
    return f"- [{title}]({url}) <sup>{meta}</sup>"


def render(til_dir: pathlib.Path, tils: list[Til]) -> str:
    return "\n".join(
        link_item(title_for(til_dir, til.path), til.url, [til.category], til.added)
        for til in tils
    )


def fetch_feed(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "jbranchaud-readme"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def parse_entry(entry: ET.Element) -> Blogmark:
    """One Atom <entry>, preferring the alternate link and published stamp."""
    link = entry.find(f"{ATOM}link[@rel='alternate']")
    if link is None:
        link = entry.find(f"{ATOM}link")
    stamp = entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated", "")
    return Blogmark(
        title=(entry.findtext(f"{ATOM}title") or "").strip(),
        url=link.get("href", "") if link is not None else "",
        published=datetime.datetime.fromisoformat(stamp),
        tags=[
            category.get("term")
            for category in entry.findall(f"{ATOM}category")
            if category.get("term")
        ],
    )


def parse_blogmarks(feed: bytes, count: int) -> list[Blogmark]:
    """Return the `count` newest feed entries, newest first."""
    entries = [parse_entry(entry) for entry in ET.fromstring(feed).iter(f"{ATOM}entry")]
    entries.sort(key=lambda blogmark: blogmark.published, reverse=True)
    return entries[:count]


def render_blogmarks(blogmarks: list[Blogmark]) -> str:
    return "\n".join(
        link_item(b.title, b.url, b.tags, b.published.date()) for b in blogmarks
    )


def tile_svg(category: str, count: int, theme: Theme) -> str:
    """One name plate: brand-colored edge, category label, count as numeral."""
    accent = BRAND.get(category, BRAND_FALLBACK)
    label = saxutils.escape(category.upper())
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{TILE_W}" \
height="{TILE_H}" viewBox="0 0 {TILE_W} {TILE_H}" role="img" \
aria-label="{label}: {count} TILs">
  <clipPath id="card">
    <rect x="0" y="0" width="{TILE_W}" height="{TILE_H}" rx="8"/>
  </clipPath>
  <g clip-path="url(#card)">
    <rect x="0" y="0" width="{TILE_W}" height="{TILE_H}" fill="{theme.background}"/>
    <rect x="0" y="0" width="4" height="{TILE_H}" fill="{accent}"/>
  </g>
  <rect x="0.5" y="0.5" width="{TILE_W - 1}" height="{TILE_H - 1}" rx="7.5"
        fill="none" stroke="{theme.border}"/>
  <g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">
    <text x="17" y="21" font-size="10.5" letter-spacing="0.7"
          fill="{theme.label}">{label}</text>
    <text x="17" y="42" font-size="19" font-weight="600"
          fill="{theme.count}">{count:,}</text>
  </g>
</svg>
"""


def render_tiles(topics: list[TopicCount], assets: pathlib.Path) -> str:
    """Write a light/dark SVG pair per category, return the linked markup.

    The count rides in the filename so GitHub's image proxy can't serve a
    stale tile after the numbers move.
    """
    shutil.rmtree(assets, ignore_errors=True)
    assets.mkdir(parents=True, exist_ok=True)

    lines = []
    for topic in topics:
        category, count = topic.category, topic.count
        paths = {}
        for theme_name, theme in THEMES.items():
            name = f"{category}-{count}-{theme_name}.svg"
            (assets / name).write_text(
                tile_svg(category, count, theme), encoding="utf-8"
            )
            paths[theme_name] = f"{assets.as_posix()}/{name}"
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
    parser.add_argument("--feed", default=BLOGMARK_FEED_URL)
    args = parser.parse_args()

    tils = added_tils(args.til_dir, args.count)
    if not tils:
        sys.exit("error: no TILs found")

    paths = til_paths(args.til_dir)
    original = args.readme.read_text(encoding="utf-8")
    updated = splice(original, LIST_MARKERS, render(args.til_dir, tils))
    updated = splice(updated, COUNT_MARKERS, f"{len(paths):,}", inline=True)
    updated = splice(
        updated,
        TOP_MARKERS,
        render_tiles(top_categories(paths, args.top), args.assets),
    )

    # A flaky feed shouldn't block the TIL update; keep the last good list.
    try:
        blogmarks = parse_blogmarks(fetch_feed(args.feed), args.count)
    except Exception as error:  # noqa: BLE001
        print(f"warning: skipping blogmarks: {error}", file=sys.stderr)
        blogmarks = []
    if blogmarks:
        updated = splice(updated, BLOGMARK_MARKERS, render_blogmarks(blogmarks))

    if updated == original:
        print("no changes")
        return
    args.readme.write_text(updated, encoding="utf-8")
    print("README updated")


if __name__ == "__main__":
    main()
