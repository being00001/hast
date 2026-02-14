"""Manager-only feedback backlog publisher for Codeberg issues."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
from typing import Any
from urllib import error, request

from devf.core.errors import DevfError
from devf.core.feedback import load_feedback_backlog, save_feedback_backlog
from devf.core.feedback_policy import FeedbackPolicy


@dataclass(frozen=True)
class PublishResult:
    attempted: int
    published: int
    skipped: int
    failed: int
    urls: list[str]


def publish_feedback_backlog(
    root: Path,
    policy: FeedbackPolicy,
    *,
    limit: int = 20,
    dry_run: bool = False,
) -> PublishResult:
    publish_cfg = policy.publish
    if publish_cfg.backend != "codeberg":
        raise DevfError(f"unsupported publish backend: {publish_cfg.backend}")
    if not publish_cfg.repository:
        raise DevfError("feedback publish requires publish.repository in feedback_policy.yaml")

    backlog = load_feedback_backlog(root)
    eligible = [
        item for item in backlog
        if item.get("owner") == "manager"
        and item.get("status") == publish_cfg.min_status
        and not item.get("published_issue_url")
    ]
    to_publish = eligible[:max(0, limit)]
    if not to_publish:
        return PublishResult(attempted=0, published=0, skipped=len(backlog), failed=0, urls=[])

    token = os.environ.get(publish_cfg.token_env, "").strip()

    published_count = 0
    failed_count = 0
    urls: list[str] = []
    now_iso = datetime.now().astimezone().isoformat()

    index = {str(item.get("feedback_key", "")): item for item in backlog}
    for item in to_publish:
        key = str(item.get("feedback_key", ""))
        if not key:
            failed_count += 1
            continue

        title = _build_issue_title(item)
        body = _build_issue_body(item)
        issue_url = "dry-run://codeberg/issue"

        if not dry_run:
            try:
                issue_url = create_codeberg_issue(
                    base_url=publish_cfg.base_url,
                    repository=publish_cfg.repository,
                    token=token,
                    title=title,
                    body=body,
                    labels=publish_cfg.labels,
                )
            except DevfError:
                failed_count += 1
                continue

        current = index.get(key)
        if current is None:
            failed_count += 1
            continue
        current["published_issue_url"] = issue_url
        current["published_at"] = now_iso
        current["published_backend"] = publish_cfg.backend
        current["status"] = "accepted"
        urls.append(issue_url)
        published_count += 1

    if published_count > 0:
        save_feedback_backlog(root, backlog)

    return PublishResult(
        attempted=len(to_publish),
        published=published_count,
        skipped=max(0, len(backlog) - len(to_publish)),
        failed=failed_count,
        urls=urls,
    )


def create_codeberg_issue(
    *,
    base_url: str,
    repository: str,
    token: str,
    title: str,
    body: str,
    labels: list[str],
) -> str:
    if "/" not in repository:
        raise DevfError("publish.repository must be '<owner>/<repo>'")
    owner, repo = repository.split("/", 1)
    owner = owner.strip()
    repo = repo.strip()
    if not owner or not repo:
        raise DevfError("publish.repository must be '<owner>/<repo>'")

    if not token.strip():
        return _create_issue_via_berg(repository, title, body, labels)

    api = f"{base_url.rstrip('/')}/api/v1/repos/{owner}/{repo}/issues"
    payload = {
        "title": title,
        "body": body,
        "labels": labels,
    }
    req = request.Request(
        api,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise DevfError(f"codeberg publish failed ({exc.code}): {detail[:240]}") from exc
    except error.URLError as exc:
        raise DevfError(f"codeberg publish failed: {exc.reason}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DevfError("codeberg publish failed: invalid JSON response") from exc

    url = parsed.get("html_url") or parsed.get("url")
    if not isinstance(url, str) or not url.strip():
        raise DevfError("codeberg publish failed: missing issue URL in response")
    return url


def _create_issue_via_berg(
    repository: str,
    title: str,
    body: str,
    labels: list[str],
) -> str:
    cmd = [
        "berg",
        "--non-interactive",
        "issue",
        "create",
        "--owner-repo",
        repository,
        "--title",
        title,
        "--description",
        body,
        "--output-mode",
        "json",
    ]
    # berg label assignment can fail if labels are not pre-created in the target repo.
    # For the fallback path, prioritize reliable issue creation over label fidelity.
    _ = labels

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        detail = stderr or stdout or "unknown berg error"
        raise DevfError(
            "codeberg publish via berg failed: "
            f"{detail[:240]} (run `berg auth login` or set CODEBERG_TOKEN)"
        )

    raw = (proc.stdout or "").strip()
    if not raw:
        raise DevfError("codeberg publish via berg failed: empty response")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DevfError("codeberg publish via berg failed: invalid JSON response") from exc

    url = parsed.get("html_url") or parsed.get("url")
    if not isinstance(url, str) or not url.strip():
        raise DevfError("codeberg publish via berg failed: missing issue URL in response")
    return url


def _build_issue_title(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "devf feedback item").strip()
    return f"[devf-feedback] {title}"[:200]


def _build_issue_body(item: dict[str, Any]) -> str:
    lines = [
        "## Feedback Summary",
        f"- Key: `{item.get('feedback_key')}`",
        f"- Count: {item.get('count')}",
        f"- Max impact: {item.get('max_impact')}",
        f"- Avg confidence: {item.get('avg_confidence')}",
        f"- First seen: {item.get('first_seen')}",
        f"- Last seen: {item.get('last_seen')}",
        "",
        "## Problem",
        str(item.get("summary") or "").strip() or "(none)",
        "",
        "## Recommended Change",
        str(item.get("recommended_change") or "").strip() or "(none)",
        "",
        "## Decision Context",
        str(item.get("decision_reason") or "").strip() or "(none)",
        "",
        "_Generated by devf manager feedback publisher._",
    ]
    return "\n".join(lines)
