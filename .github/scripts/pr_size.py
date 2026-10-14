#!/usr/bin/env python3
"""Notify when a pull request is larger than the change-size threshold.

Notification only: it labels the pull request and posts one comment. It never fails the build
and never blocks a merge. It reads the pull request through the GitHub API and does not
execute any code from the pull request.

Environment:
    GH_TOKEN        token with pull-requests and issues write access
    REPO            owner/name
    PR_NUMBER       pull request number
    PR_AUTHOR       login of the author (bots such as dependabot are skipped)
    SIZE_THRESHOLD  optional, default 400
    DRY_RUN         optional, set to "1" to print the decision without changing anything
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
from collections.abc import Iterable, Mapping
from typing import Any

THRESHOLD_DEFAULT = 400
LABEL = "size/large"
LABEL_COLOR = "D93F0B"
LABEL_DESCRIPTION = "Over the change-size threshold: consider splitting against a plan"
MARKER = "<!-- pr-size-notice -->"

# Files that do not count towards the size: generated, lockfiles. Matched with fnmatch on the
# full path. Pure renames report zero changed lines, so they cost nothing automatically.
EXCLUDE = (
    "tests/providers/**/*.json",
    "uv.lock",
    "*.lock",
)


def counted_lines(
    files: Iterable[Mapping[str, Any]], exclude: tuple[str, ...] = EXCLUDE
) -> tuple[int, int]:
    """Return (counted, excluded) changed lines (additions plus deletions) for a file list."""
    counted = 0
    excluded = 0
    for entry in files:
        changes = int(entry.get("additions", 0)) + int(entry.get("deletions", 0))
        name = str(entry.get("filename", ""))
        if any(fnmatch.fnmatch(name, pattern) for pattern in exclude):
            excluded += changes
        else:
            counted += changes
    return counted, excluded


def _gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], check=True, capture_output=True, text=True)
    return result.stdout


def _pull_request_files(repo: str, number: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = json.loads(
            _gh("api", f"repos/{repo}/pulls/{number}/files?per_page=100&page={page}")
        )
        files.extend(batch)
        if len(batch) < 100:
            return files
        page += 1


def _comment_body(repo: str, counted: int, excluded: int, threshold: int) -> str:
    note = f" ({excluded} generated or lockfile lines are not counted)" if excluded else ""
    url = f"https://github.com/{repo}/blob/main/CONTRIBUTING.md#change-size"
    return (
        f"{MARKER}\n"
        f"**This pull request changes about {counted} lines{note}, over the {threshold}-line "
        "threshold.**\n\n"
        "Please consider splitting it into logical components against a short plan, one pull "
        "request each. If it cannot be split sensibly (for example boilerplate, a mechanical "
        "change or generated code), say why in the description.\n\n"
        f"This is a notification only. It does not block merging. See [Change size]({url}).\n"
    )


def _existing_comment_id(repo: str, number: str) -> str | None:
    comments = json.loads(_gh("api", f"repos/{repo}/issues/{number}/comments?per_page=100"))
    for comment in comments:
        if MARKER in comment.get("body", ""):
            return str(comment["id"])
    return None


def main() -> int:
    repo = os.environ["REPO"]
    number = os.environ["PR_NUMBER"]
    author = os.environ.get("PR_AUTHOR", "")
    threshold = int(os.environ.get("SIZE_THRESHOLD", THRESHOLD_DEFAULT))
    dry_run = os.environ.get("DRY_RUN") == "1"

    if author.endswith("[bot]"):
        print(f"skipping bot author {author}")
        return 0

    counted, excluded = counted_lines(_pull_request_files(repo, number))
    large = counted > threshold
    print(f"PR #{number}: {counted} counted lines, {excluded} excluded, threshold {threshold}")

    if dry_run:
        print("dry run: would", "label and comment" if large else "clear label and comment")
        return 0

    labels = json.loads(_gh("pr", "view", number, "--repo", repo, "--json", "labels"))["labels"]
    has_label = any(label["name"] == LABEL for label in labels)
    comment_id = _existing_comment_id(repo, number)

    if large:
        subprocess.run(
            [
                "gh",
                "label",
                "create",
                LABEL,
                "--repo",
                repo,
                "--color",
                LABEL_COLOR,
                "--description",
                LABEL_DESCRIPTION,
            ],
            check=False,
            capture_output=True,
        )  # fails harmlessly when the label already exists
        if not has_label:
            _gh("pr", "edit", number, "--repo", repo, "--add-label", LABEL)
        body = _comment_body(repo, counted, excluded, threshold)
        if comment_id:
            _gh(
                "api",
                "-X",
                "PATCH",
                f"repos/{repo}/issues/comments/{comment_id}",
                "-f",
                f"body={body}",
            )
        else:
            _gh("api", "-X", "POST", f"repos/{repo}/issues/{number}/comments", "-f", f"body={body}")
    else:
        if has_label:
            _gh("pr", "edit", number, "--repo", repo, "--remove-label", LABEL)
        if comment_id:
            _gh("api", "-X", "DELETE", f"repos/{repo}/issues/comments/{comment_id}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # notification only: never fail the build
        print(f"pr_size: ignored error: {error}")
        sys.exit(0)
