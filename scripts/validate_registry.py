#!/usr/bin/env python3
"""Validate registry.json for the Coomi community registry.

Checks (local, no network):
  1. JSON parses, version == 1
  2. sections skills / mcps / workflows exist and are arrays
  3. per-entry required fields present and well-formed
  4. ids unique and slug-shaped ([a-z0-9][a-z0-9-]*)
  5. `verified` must be false in submissions (maintainers flip it after review)

Checks (network, GitHub API; skipped with --local):
  6. repository exists (owner/repo -> HTTP 200)
  7. for SKILL entries: SKILL.md exists at {subdir}/SKILL.md

Usage:
  python3 scripts/validate_registry.py [--local] [--file registry.json]

Exit code 0 = pass, 1 = fail (prints every problem found).
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

REQUIRED_FIELDS = ("id", "name", "description", "repository", "ref", "license")

problems = []
warnings = []


def fail(msg):
    problems.append(msg)


def warn(msg):
    warnings.append(msg)


def api_get(path):
    """GET a GitHub API endpoint. Returns (status, json) or (status, None)."""
    url = "https://api.github.com" + path
    headers = {
        "User-Agent": "coomi-registry-validator",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, None
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:  # network issue / timeout
        warn(f"network error on {url}: {exc}")
        return None, None


def normalize_repo(raw):
    """Accept 'owner/repo' or 'https://github.com/owner/repo'."""
    s = raw.strip()
    s = s.rstrip("/")
    for prefix in ("https://github.com/", "http://github.com/", "git@github.com:"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return s.rstrip(".git")


def check_entry(entry, kind, index, local):
    if not isinstance(entry, dict):
        fail(f"{kind}[{index}]: entry must be an object")
        return

    # --- required fields ---
    for field in REQUIRED_FIELDS:
        value = entry.get(field)
        if not isinstance(value, str) or not value.strip():
            fail(f"{kind}[{index}]: missing or empty required field '{field}'")
            return

    entry_id = entry["id"].strip()
    if not SLUG_RE.match(entry_id):
        fail(f"{kind}[{index}]: id '{entry_id}' must match ^[a-z0-9][a-z0-9-]*$ "
             "(lowercase letters, digits, hyphens)")

    repo = normalize_repo(entry["repository"])
    if not REPO_RE.match(repo):
        fail(f"{kind}[{index}]: repository '{entry['repository']}' is not owner/repo")

    if not entry.get("ref", "").strip():
        fail(f"{kind}[{index}]: ref is empty")

    license_value = entry.get("license", "").strip()
    if license_value.lower() in ("unknown", "none", "see-repository", "其他"):
        fail(f"{kind}[{index}]: license '{license_value}' is not a concrete license")

    # --- verified flag: submissions must be unverified ---
    verified = entry.get("verified", False)
    if verified is not False:
        fail(f"{kind}[{index}]: 'verified' must be false in submissions; "
             "maintainers set it to true after review")

    # --- optional fields ---
    subdir = entry.get("subdir", "") or ""
    tags = entry.get("tags")
    if tags is not None and (not isinstance(tags, list) or
                             any(not isinstance(t, str) for t in tags)):
        fail(f"{kind}[{index}]: 'tags' must be an array of strings")

    # --- network checks ---
    if local:
        return

    status, data = api_get(f"/repos/{repo}")
    if status == 404:
        fail(f"{kind}[{index}]: repository '{repo}' does not exist (HTTP 404)")
        return
    if status == 200:
        if data is not None:
            if data.get("archived"):
                fail(f"{kind}[{index}]: repository '{repo}' is archived")
            if data.get("private"):
                fail(f"{kind}[{index}]: repository '{repo}' is private")
    else:
        warn(f"{kind}[{index}]: repo check for '{repo}' skipped (status {status})")

    if kind == "skills":
        sk_path = f"{subdir}/SKILL.md" if subdir else "SKILL.md"
        status, _ = api_get(f"/repos/{repo}/contents/{sk_path}")
        if status == 404:
            fail(f"{kind}[{index}]: '{sk_path}' not found in repository '{repo}'")
        elif status != 200:
            warn(f"{kind}[{index}]: SKILL.md check skipped (status {status})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default=os.path.join(ROOT, "registry.json"))
    parser.add_argument("--local", action="store_true",
                        help="skip network checks (repo existence, SKILL.md)")
    args = parser.parse_args()

    with open(args.file, encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            fail(f"registry.json is not valid JSON: {exc}")
            print(f"FAIL: {problems[0]}", file=sys.stderr)
            sys.exit(1)

    if data.get("version") != 1:
        fail(f"version must be 1, got {data.get('version')!r}")

    seen_ids = set()
    for kind in ("skills", "mcps", "workflows"):
        entries = data.get(kind)
        if not isinstance(entries, list):
            fail(f"'{kind}' must be an array, got {type(entries).__name__}")
            continue
        for i, entry in enumerate(entries):
            check_entry(entry, kind, i, args.local)
            if isinstance(entry, dict):
                entry_id = str(entry.get("id", "")).strip()
                if entry_id:
                    if entry_id in seen_ids:
                        fail(f"duplicate id '{entry_id}' across registry")
                    seen_ids.add(entry_id)

    for warning in warnings:
        print(f"WARN: {warning}")
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        print(f"\n{len(problems)} problem(s) found.")
        sys.exit(1)

    counts = ", ".join(
        f"{len(data.get(kind, []))} {kind}" for kind in ("skills", "mcps", "workflows"))
    print(f"OK: {counts} — registry.json is valid")
    sys.exit(0)


if __name__ == "__main__":
    main()
