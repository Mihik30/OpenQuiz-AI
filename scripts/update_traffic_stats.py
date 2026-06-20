#!/usr/bin/env python3
"""Update saved GitHub repository traffic stats and render a README SVG graph."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "docs" / "traffic.json"
SVG_PATH = ROOT / "docs" / "traffic.svg"
API_ROOT = "https://api.github.com"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def api_get(path: str, token: str) -> dict:
    request = urllib.request.Request(
        f"{API_ROOT}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "openquiz-ai-traffic-updater",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API error {exc.code} for {path}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach GitHub API for {path}: {exc}") from exc


def load_existing(repository: str) -> dict:
    if not DATA_PATH.exists():
        return {"repository": repository, "updated_at": None, "days": {}}

    with DATA_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)

    data.setdefault("repository", repository)
    data.setdefault("updated_at", None)
    data.setdefault("days", {})
    return data


def merge_series(days: dict, items: list, total_key: str, unique_key: str) -> None:
    for item in items:
        date = item.get("timestamp", "")[:10]
        if not date:
            continue

        record = days.setdefault(
            date,
            {"views": 0, "unique_views": 0, "clones": 0, "unique_clones": 0},
        )
        record[total_key] = int(item.get("count", 0))
        record[unique_key] = int(item.get("uniques", 0))


def save_json(data: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DATA_PATH.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(data, file, indent=2, sort_keys=True)
        file.write("\n")


def points_for(values: list[int], x0: int, y0: int, width: int, height: int, max_value: int) -> str:
    if len(values) == 1:
        return f"{x0 + width},{y0 + height - scale(values[0], height, max_value)}"

    step = width / max(1, len(values) - 1)
    points = []
    for index, value in enumerate(values):
        x = x0 + round(index * step, 2)
        y = y0 + height - scale(value, height, max_value)
        points.append(f"{x},{y}")
    return " ".join(points)


def scale(value: int, height: int, max_value: int) -> int:
    if max_value <= 0:
        return 0
    return round((value / max_value) * height)


def render_svg(data: dict) -> str:
    days = data.get("days", {})
    ordered_dates = sorted(days.keys())
    recent_dates = ordered_dates[-30:]
    recent = [days[date] for date in recent_dates]

    views = [int(day.get("views", 0)) for day in recent]
    clones = [int(day.get("clones", 0)) for day in recent]
    max_value = max(views + clones + [1])

    total_views = sum(int(day.get("views", 0)) for day in days.values())
    total_unique_views = sum(int(day.get("unique_views", 0)) for day in days.values())
    total_clones = sum(int(day.get("clones", 0)) for day in days.values())
    total_unique_clones = sum(int(day.get("unique_clones", 0)) for day in days.values())

    width = 820
    height = 300
    graph_x = 54
    graph_y = 88
    graph_width = 712
    graph_height = 132
    updated = escape(str(data.get("updated_at") or "not updated yet"))
    repository = escape(str(data.get("repository") or "repository"))
    date_label = "No saved traffic yet"
    if recent_dates:
        date_label = f"{recent_dates[0]} to {recent_dates[-1]}"

    view_points = points_for(views or [0], graph_x, graph_y, graph_width, graph_height, max_value)
    clone_points = points_for(clones or [0], graph_x, graph_y, graph_width, graph_height, max_value)

    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
  <title id="title">Repository traffic graph</title>
  <desc id="desc">Daily GitHub views and clones for {repository}. Last updated {updated}.</desc>
  <rect width="{width}" height="{height}" rx="8" fill="#0f172a"/>
  <text x="32" y="38" fill="#f8fafc" font-family="Segoe UI, Arial, sans-serif" font-size="24" font-weight="700">Repository Traffic</text>
  <text x="32" y="62" fill="#94a3b8" font-family="Segoe UI, Arial, sans-serif" font-size="13">{repository} - {escape(date_label)}</text>
  <line x1="{graph_x}" y1="{graph_y + graph_height}" x2="{graph_x + graph_width}" y2="{graph_y + graph_height}" stroke="#334155" stroke-width="1"/>
  <line x1="{graph_x}" y1="{graph_y}" x2="{graph_x}" y2="{graph_y + graph_height}" stroke="#334155" stroke-width="1"/>
  <polyline points="{view_points}" fill="none" stroke="#38bdf8" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
  <polyline points="{clone_points}" fill="none" stroke="#34d399" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="608" cy="38" r="5" fill="#38bdf8"/>
  <text x="620" y="43" fill="#cbd5e1" font-family="Segoe UI, Arial, sans-serif" font-size="13">Views</text>
  <circle cx="682" cy="38" r="5" fill="#34d399"/>
  <text x="694" y="43" fill="#cbd5e1" font-family="Segoe UI, Arial, sans-serif" font-size="13">Clones</text>
  <text x="32" y="252" fill="#f8fafc" font-family="Segoe UI, Arial, sans-serif" font-size="18" font-weight="700">{total_views}</text>
  <text x="32" y="272" fill="#94a3b8" font-family="Segoe UI, Arial, sans-serif" font-size="13">saved views ({total_unique_views} unique)</text>
  <text x="272" y="252" fill="#f8fafc" font-family="Segoe UI, Arial, sans-serif" font-size="18" font-weight="700">{total_clones}</text>
  <text x="272" y="272" fill="#94a3b8" font-family="Segoe UI, Arial, sans-serif" font-size="13">saved clones ({total_unique_clones} unique)</text>
  <text x="564" y="252" fill="#f8fafc" font-family="Segoe UI, Arial, sans-serif" font-size="18" font-weight="700">{len(days)}</text>
  <text x="564" y="272" fill="#94a3b8" font-family="Segoe UI, Arial, sans-serif" font-size="13">saved days</text>
  <text x="32" y="292" fill="#64748b" font-family="Segoe UI, Arial, sans-serif" font-size="11">Updated: {updated}</text>
</svg>
"""


def save_svg(data: dict) -> None:
    SVG_PATH.parent.mkdir(parents=True, exist_ok=True)
    SVG_PATH.write_text(render_svg(data), encoding="utf-8", newline="\n")


def main() -> int:
    token = os.getenv("TRAFFIC_TOKEN", "").strip()
    if not token:
        print("TRAFFIC_TOKEN is required to read GitHub repository traffic.", file=sys.stderr)
        return 2

    repository = os.getenv("GITHUB_REPOSITORY", "Mihik30/OpenQuiz-AI").strip()
    if "/" not in repository:
        print("GITHUB_REPOSITORY must look like OWNER/REPO.", file=sys.stderr)
        return 2

    views = api_get(f"/repos/{repository}/traffic/views", token)
    clones = api_get(f"/repos/{repository}/traffic/clones", token)

    data = load_existing(repository)
    data["repository"] = repository
    data["updated_at"] = utc_now_iso()
    days = data.setdefault("days", {})

    merge_series(days, views.get("views", []), "views", "unique_views")
    merge_series(days, clones.get("clones", []), "clones", "unique_clones")

    save_json(data)
    save_svg(data)

    print(f"Updated {DATA_PATH.relative_to(ROOT)} and {SVG_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
