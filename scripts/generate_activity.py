"""Render contribution cards using GitHub's public calendar; no third-party services."""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from html import escape
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
QUERY = """
query ProfileActivity($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
            contributionLevel
          }
        }
      }
    }
  }
}
"""

PALETTES = {
    "dark": {
        "background": "#0d1117", "panel": "#161b22", "border": "#30363d",
        "text": "#e6edf3", "muted": "#919ba8", "accent": "#58a6ff",
        "heat": ["#21262d", "#0e4429", "#006d32", "#26a641", "#39d353"],
    },
    "light": {
        "background": "#ffffff", "panel": "#f6f8fa", "border": "#d1d9e0",
        "text": "#1f2328", "muted": "#59636e", "accent": "#0969da",
        "heat": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
    },
}
LEVELS = {
    "NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4,
}


def fetch_calendar(login: str) -> dict:
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("GH_TOKEN is required; GitHub Actions supplies github.token.")
    request = Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": login}}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "github-profile-activity"},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise RuntimeError("GitHub could not return the contribution calendar.")
    user = payload["data"].get("user")
    if not user:
        raise RuntimeError("The profile login could not be found.")
    return user["contributionsCollection"]["contributionCalendar"]


def summarize(calendar: dict) -> tuple[list[dict], int, int]:
    days = sorted(
        (day for week in calendar["weeks"] for day in week["contributionDays"]),
        key=lambda day: day["date"],
    )
    if not days:
        raise ValueError("GitHub returned an empty contribution calendar.")
    longest = run = 0
    previous = None
    for day in days:
        current_date = date.fromisoformat(day["date"])
        if day["contributionCount"]:
            run = run + 1 if previous == current_date - timedelta(days=1) else 1
        else:
            run = 0
        longest = max(longest, run)
        previous = current_date
    # An unfinished final day does not break yesterday's streak.
    recent = days[:-1] if days[-1]["contributionCount"] == 0 else days
    current = 0
    expected = date.fromisoformat(recent[-1]["date"]) if recent else None
    for day in reversed(recent):
        current_date = date.fromisoformat(day["date"])
        if not day["contributionCount"] or current_date != expected:
            break
        current += 1
        expected -= timedelta(days=1)
    return days, current, longest


def render(calendar: dict, login: str, theme: str) -> str:
    days, current, longest = summarize(calendar)
    p = PALETTES[theme]
    latest = days[-1]["date"]
    metrics = [
        (f'{calendar["totalContributions"]:,}', "Contributions", "past year", p["accent"]),
        (str(current), "Current streak", "days", "#f0883e"),
        (str(longest), "Longest streak", "days in the past year", p["accent"]),
    ]
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="314" viewBox="0 0 900 314" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(login)} — GitHub activity</title>',
        f'<desc id="desc">{calendar["totalContributions"]} contributions in the past year. Current streak {current} days. Longest streak {longest} days. Calendar through {latest}.</desc>',
        f'<rect x="0.5" y="0.5" width="899" height="313" rx="12" fill="{p["background"]}" stroke="{p["border"]}"/>',
        '<g font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Arial, sans-serif">',
    ]
    for i, (value, label, detail, accent) in enumerate(metrics):
        x = 18 + i * 291
        svg.extend([
            f'<rect x="{x}" y="18" width="282" height="106" rx="8" fill="{p["panel"]}"/>',
            f'<text x="{x + 18}" y="53" font-size="28" font-weight="700" fill="{accent}">{value}</text>',
            f'<text x="{x + 18}" y="79" font-size="14" font-weight="600" fill="{p["text"]}">{label}</text>',
            f'<text x="{x + 18}" y="101" font-size="11" fill="{p["muted"]}">{detail}</text>',
        ])
    svg.append(f'<text x="24" y="153" font-size="13" font-weight="600" fill="{p["text"]}">A year of building</text>')
    svg.append(f'<text x="876" y="153" text-anchor="end" font-size="11" fill="{p["muted"]}">Through {latest} · GitHub calendar</text>')
    weeks = calendar["weeks"]
    # Sunday-first calendar, 53/54 columns depending on the year's alignment.
    step = min(15, 796 / max(len(weeks), 1))
    cell = step - 4
    start_x = 61
    last_month = None
    for i, week in enumerate(weeks):
        for day in week["contributionDays"]:
            parsed = date.fromisoformat(day["date"])
            y = 188 + ((parsed.weekday() + 1) % 7) * 12
            x = start_x + i * step
            fill = p["heat"][LEVELS.get(day["contributionLevel"], 0)]
            count = day["contributionCount"]
            svg.append(f'<rect x="{x:.2f}" y="{y}" width="{cell:.2f}" height="8" rx="2" fill="{fill}"><title>{day["date"]}: {count} contributions</title></rect>')
            month = (parsed.year, parsed.month)
            if month != last_month:
                if i < len(weeks) - 1:
                    svg.append(f'<text x="{x:.2f}" y="179" font-size="10" fill="{p["muted"]}">{parsed.strftime("%b")}</text>')
                last_month = month
    for label, row in [("Mon", 1), ("Wed", 3), ("Fri", 5)]:
        svg.append(f'<text x="24" y="{195 + row * 12}" font-size="10" fill="{p["muted"]}">{label}</text>')
    svg.append(f'<text x="24" y="296" font-size="10" fill="{p["muted"]}">Public contributions · updated daily</text>')
    svg.append(f'<text x="741" y="296" font-size="10" fill="{p["muted"]}">Less</text>')
    for i, color in enumerate(p["heat"]):
        svg.append(f'<rect x="{770 + i * 13}" y="288" width="9" height="9" rx="2" fill="{color}"/>')
    svg.append(f'<text x="841" y="296" font-size="10" fill="{p["muted"]}">More</text>')
    svg.append('</g></svg>')
    return "\n".join(svg) + "\n"


def main() -> None:
    login = os.environ.get("PROFILE_LOGIN", "TrinhQuocDat542005")
    calendar = fetch_calendar(login)
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    for theme in PALETTES:
        (assets / f"activity-{theme}.svg").write_text(render(calendar, login, theme), encoding="utf-8")
    _, current, longest = summarize(calendar)
    print(f'Generated both themes: {calendar["totalContributions"]} public contributions, current streak {current}, longest streak {longest}.')


if __name__ == "__main__":
    main()
