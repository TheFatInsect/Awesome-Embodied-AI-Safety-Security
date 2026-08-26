#!/usr/bin/env python3
"""Generate light and dark GitHub star-history charts with no dependencies."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import escape
from pathlib import Path


GRAPHQL_URL = "https://api.github.com/graphql"


def github_graphql(token: str, query: str, variables: dict[str, object]) -> dict:
    payload = json.dumps({"query": query, "variables": variables}).encode()
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "awesome-embodied-ai-star-history",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"GitHub API returned HTTP {error.code}: {detail}") from error
    if result.get("errors"):
        raise RuntimeError(f"GitHub GraphQL error: {result['errors']}")
    return result["data"]


def fetch_star_dates(repository: str, token: str) -> tuple[datetime, list[datetime]]:
    try:
        owner, name = repository.split("/", 1)
    except ValueError as error:
        raise ValueError("repository must use the OWNER/NAME form") from error

    query = """
      query($owner: String!, $name: String!, $cursor: String) {
        repository(owner: $owner, name: $name) {
          createdAt
          stargazers(first: 100, after: $cursor,
                     orderBy: {field: STARRED_AT, direction: ASC}) {
            edges { starredAt }
            pageInfo { hasNextPage endCursor }
          }
        }
      }
    """
    cursor: str | None = None
    created_at: datetime | None = None
    stars: list[datetime] = []
    while True:
        data = github_graphql(
            token,
            query,
            {"owner": owner, "name": name, "cursor": cursor},
        )
        repo = data.get("repository")
        if repo is None:
            raise RuntimeError(f"repository not found or token cannot read it: {repository}")
        if created_at is None:
            created_at = datetime.fromisoformat(repo["createdAt"].replace("Z", "+00:00"))
        connection = repo["stargazers"]
        stars.extend(
            datetime.fromisoformat(edge["starredAt"].replace("Z", "+00:00"))
            for edge in connection["edges"]
        )
        page_info = connection["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]
    assert created_at is not None
    return created_at, stars


def svg_chart(repository: str, created: datetime, stars: list[datetime], dark: bool) -> str:
    width, height = 880, 440
    left, right, top, bottom = 72, 30, 64, 62
    plot_w, plot_h = width - left - right, height - top - bottom
    now = datetime.now(timezone.utc)
    start = min(created, stars[0] if stars else created)
    span = max((now - start).total_seconds(), 1.0)
    y_max = max(len(stars), 1)

    colors = (
        {"bg": "#0d1117", "fg": "#e6edf3", "muted": "#8b949e", "grid": "#30363d", "line": "#f2cc60", "fill": "#f2cc6028"}
        if dark
        else {"bg": "#ffffff", "fg": "#24292f", "muted": "#57606a", "grid": "#d8dee4", "line": "#0969da", "fill": "#0969da20"}
    )

    def x_at(moment: datetime) -> float:
        return left + ((moment - start).total_seconds() / span) * plot_w

    def y_at(count: int) -> float:
        return top + plot_h - (count / y_max) * plot_h

    points: list[tuple[float, float]] = [(left, y_at(0))]
    points.extend((x_at(star), y_at(index)) for index, star in enumerate(stars, 1))
    points.append((left + plot_w, y_at(len(stars))))
    line_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    fill_points = f"{left},{top + plot_h} {line_points} {left + plot_w},{top + plot_h}"

    grid: list[str] = []
    if y_max <= 4:
        y_values = list(range(y_max + 1))
    else:
        step = max(1, math.ceil(y_max / 4))
        y_values = list(range(0, y_max, step)) + [y_max]
    for value in y_values:
        y = y_at(value)
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" />')
        grid.append(f'<text x="{left - 12}" y="{y + 4:.1f}" text-anchor="end">{value}</text>')
    span_days = span / 86_400
    x_tick_count = 2 if span_days < 2 else 6
    date_format = "%m-%d %H:%M" if span_days < 2 else ("%Y-%m-%d" if span_days < 120 else "%Y-%m")
    for index in range(x_tick_count):
        ratio = index / (x_tick_count - 1)
        moment = start.timestamp() + span * ratio
        date = datetime.fromtimestamp(moment, timezone.utc)
        x = left + plot_w * ratio
        grid.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_h}" />')
        grid.append(f'<text x="{x:.1f}" y="{top + plot_h + 27}" text-anchor="middle">{date.strftime(date_format)}</text>')

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">GitHub star history for {escape(repository)}</title>
  <desc id="desc">The repository has {len(stars)} stars as of {now:%Y-%m-%d}.</desc>
  <rect width="100%" height="100%" rx="10" fill="{colors['bg']}"/>
  <style>
    text {{ font: 12px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; fill: {colors['muted']}; }}
    .title {{ font-size: 18px; font-weight: 600; fill: {colors['fg']}; }}
    .grid line {{ stroke: {colors['grid']}; stroke-width: 1; }}
  </style>
  <text class="title" x="{left}" y="34">Star History · {escape(repository)}</text>
  <text x="{width - right}" y="34" text-anchor="end">{len(stars)} stars · updated {now:%Y-%m-%d}</text>
  <g class="grid">{''.join(grid)}</g>
  <polygon points="{fill_points}" fill="{colors['fill']}"/>
  <polyline points="{line_points}" fill="none" stroke="{colors['line']}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>
  <text x="{width / 2}" y="{height - 13}" text-anchor="middle">Date (UTC)</text>
</svg>
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--output-dir", default="assets")
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN")
    if not args.repo:
        parser.error("--repo or GITHUB_REPOSITORY is required")
    if not token:
        parser.error("GITHUB_TOKEN is required")

    created, stars = fetch_star_dates(args.repo, token)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "star-history.svg").write_text(
        svg_chart(args.repo, created, stars, dark=False), encoding="utf-8"
    )
    (output_dir / "star-history-dark.svg").write_text(
        svg_chart(args.repo, created, stars, dark=True), encoding="utf-8"
    )
    print(f"Generated star history for {args.repo}: {len(stars)} stars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
