#!/usr/bin/env python3
"""Fetch public GitHub metrics for every entry in registry.json.

Produces stats-github.json:
{
  "generated_at": "2026-08-12T10:23:00Z",
  "skills": { "<id>": {"stars": 123, "forks": 4, "downloads_total": 56,
                        "downloads_30d": 12, "pushed_at": "2026-08-01T.."} },
  "mcps":     { ... },   # same shape
  "workflows": { ... }   # same shape
}

Entry values are null when the repository could not be fetched (missing/private/rate
limited) — the app renders "no stats" instead of a fake zero.

Data sources (all public):
  - GET /repos/{owner}/{repo}          -> stars, forks, pushed_at
  - GET /repos/{owner}/{repo}/releases -> release asset download_count

Run from GitHub Actions (GITHUB_TOKEN) or locally (--local, unauthenticated,
60 requests/hour/IP — enough for a handful of entries).

Usage:
  python3 scripts/fetch_stats.py [--local]
"""

import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, "registry.json")
OUTPUT = os.path.join(ROOT, "stats-github.json")


def normalize_repo(raw):
    s = raw.strip().rstrip("/")
    for prefix in ("https://github.com/", "http://github.com/", "git@github.com:"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return s.rstrip(".git")


def api_get(path):
    headers = {
        "User-Agent": "coomi-registry-stats",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request("https://api.github.com" + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:
        print(f"WARN: network error on {path}: {exc}")
        return None, None


def fetch_entry_metrics(repo):
    """Returns metrics dict for one repo, or None if unreachable."""
    status, repo_data = api_get(f"/repos/{repo}")
    if status != 200 or not repo_data:
        print(f"WARN: repo {repo} unreachable (status {status})")
        return None

    # Sum release asset download counts, split total vs last 30 days.
    downloads_total = 0
    downloads_30d = 0
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)
    page = 1
    while True:
        status, releases = api_get(f"/repos/{repo}/releases?per_page=100&page={page}")
        if status != 200 or not releases:
            break
        for release in releases:
            published = release.get("published_at") or release.get("created_at")
            is_recent = False
            if published:
                try:
                    published_dt = datetime.datetime.fromisoformat(
                        published.replace("Z", "+00:00"))
                    is_recent = published_dt >= cutoff
                except ValueError:
                    pass
            for asset in release.get("assets", []):
                downloads_total += asset.get("download_count", 0)
                if is_recent:
                    downloads_30d += asset.get("download_count", 0)
        if len(releases) < 100:
            break
        page += 1

    return {
        "stars": repo_data.get("stargazers_count", 0),
        "forks": repo_data.get("forks_count", 0),
        "downloads_total": downloads_total,
        "downloads_30d": downloads_30d,
        "pushed_at": repo_data.get("pushed_at"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true",
                        help="skip nothing; just use unauthenticated GitHub API")
    args = parser.parse_args()
    del args  # kept for CLI parity; token comes from env either way

    with open(REGISTRY, encoding="utf-8") as fh:
        registry = json.load(fh)

    result = {"generated_at": datetime.datetime.now(
        datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}

    for kind in ("skills", "mcps", "workflows"):
        metrics = {}
        for entry in registry.get(kind, []):
            entry_id = entry.get("id")
            repo = normalize_repo(entry.get("repository", ""))
            if not entry_id or not repo:
                print(f"WARN: {kind} entry missing id/repository, skipped")
                continue
            print(f"fetching {kind}/{entry_id} <- {repo}")
            metrics[entry_id] = fetch_entry_metrics(repo)
        result[kind] = metrics

    with open(OUTPUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
    print(f"wrote {OUTPUT}")
    sys.exit(0)


if __name__ == "__main__":
    main()
