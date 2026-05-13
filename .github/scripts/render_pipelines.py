#!/usr/bin/env python3
"""Render the Pipeline Status section of README.md.

Enumerates all repositories in the org, fetches their file-based GitHub Actions
workflows, and rewrites the content between the <!-- pipelines:start --> and
<!-- pipelines:end --> markers in README.md with a table of live workflow badges.

Auth: uses GH_TOKEN from the environment (a PAT with read access to the org's
repos and their actions). When run inside GitHub Actions, set GH_TOKEN to a
secret PAT, not the default GITHUB_TOKEN, since the default token cannot
enumerate sibling repos in the org.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ORG = "cdta-digital-services"
README = pathlib.Path(__file__).resolve().parents[2] / "README.md"
START = "<!-- pipelines:start -->"
END = "<!-- pipelines:end -->"
SELF_REPO = ".github"


def gh(*args: str) -> str:
    result = subprocess.run(
        ["gh", *args],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ},
    )
    return result.stdout


def list_repos() -> list[dict]:
    out = gh("api", "--paginate", f"orgs/{ORG}/repos", "--jq",
             "[.[] | {name, archived, html_url}]")
    repos = []
    for chunk in out.strip().splitlines():
        if chunk:
            repos.extend(json.loads(chunk))
    return sorted(repos, key=lambda r: r["name"].lower())


def list_workflows(repo: str) -> list[dict]:
    try:
        out = gh("api", f"repos/{ORG}/{repo}/actions/workflows",
                 "--jq", ".workflows")
    except subprocess.CalledProcessError:
        return []
    workflows = json.loads(out) if out.strip() else []
    return [
        w for w in workflows
        if w.get("state") == "active"
        and w.get("path", "").startswith(".github/workflows/")
    ]


def has_codeql_default_setup(repo: str) -> bool:
    try:
        out = gh("api", f"repos/{ORG}/{repo}/code-scanning/default-setup",
                 "--jq", ".state")
    except subprocess.CalledProcessError:
        return False
    return out.strip() == "configured"


def codeql_default_badge(repo: str) -> str:
    badge = "https://img.shields.io/badge/CodeQL-default%20setup-2da44e?logo=github"
    href = f"https://github.com/{ORG}/{repo}/security/code-scanning"
    return f"[![CodeQL default setup]({badge})]({href})"


def badge_md(repo: str, workflow: dict) -> str:
    filename = workflow["path"].rsplit("/", 1)[-1]
    raw_name = workflow.get("name") or ""
    if not raw_name or raw_name.startswith(".github/"):
        raw_name = filename.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").title()
    badge = (
        f"https://github.com/{ORG}/{repo}/actions/workflows/{filename}/badge.svg"
    )
    href = f"https://github.com/{ORG}/{repo}/actions/workflows/{filename}"
    return f"[![{raw_name}]({badge})]({href})"


def render() -> str:
    repos = list_repos()
    if not repos:
        raise SystemExit(
            f"error: orgs/{ORG}/repos returned 0 repositories. The PAT either "
            "lacks org access (check Resource owner = org, Metadata: Read, "
            "Actions: Read), is pending org approval, or fine-grained PATs are "
            "not enabled for this org."
        )
    rows = []
    no_pipelines = []
    archived = []
    for repo in repos:
        name = repo["name"]
        if name == SELF_REPO:
            continue
        if repo.get("archived"):
            archived.append(name)
            continue
        workflows = list_workflows(name)
        badge_parts = [badge_md(name, w) for w in workflows]
        if has_codeql_default_setup(name):
            badge_parts.append(codeql_default_badge(name))
        if not badge_parts:
            no_pipelines.append(name)
            continue
        repo_link = f"[`{name}`]({repo['html_url']})"
        rows.append(f"| {repo_link} | {' '.join(badge_parts)} |")

    lines = [
        "| Repository | Pipelines |",
        "| --- | --- |",
        *rows,
    ]
    out = ["\n".join(lines)]

    if no_pipelines:
        out.append(
            "\n**Repositories without configured pipelines:** "
            + ", ".join(f"`{n}`" for n in no_pipelines)
        )
    if archived:
        out.append(
            "\n**Archived (excluded):** "
            + ", ".join(f"`{n}`" for n in archived)
        )

    timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M %Z")
    out.append(f"\n_Last updated: {timestamp}_")
    return "\n".join(out)


def splice(readme: str, body: str) -> str:
    if START not in readme or END not in readme:
        raise SystemExit(
            f"README is missing markers {START!r} / {END!r}; "
            "add them before running this script."
        )
    pre, _, rest = readme.partition(START)
    _, _, post = rest.partition(END)
    return f"{pre}{START}\n{body}\n{END}{post}"


def main() -> int:
    if not os.environ.get("GH_TOKEN") and not os.environ.get("GITHUB_TOKEN"):
        print("error: GH_TOKEN (or GITHUB_TOKEN) must be set", file=sys.stderr)
        return 2
    body = render()
    readme = README.read_text()
    updated = splice(readme, body)
    if updated != readme:
        README.write_text(updated)
        print(f"updated {README}")
    else:
        print("no changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
