"""Tests for Codeberg feedback publisher."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from devf.core.feedback import save_feedback_backlog
from devf.core.feedback_policy import FeedbackPolicy, FeedbackPublishPolicy
from devf.core.feedback_publish import create_codeberg_issue, publish_feedback_backlog


def _sample_backlog_item() -> dict:
    return {
        "feedback_key": "k1",
        "title": "[workflow_friction] retries are too high",
        "summary": "Repeated retries needed.",
        "first_seen": "2026-02-14T10:00:00+00:00",
        "last_seen": "2026-02-14T12:00:00+00:00",
        "count": 4,
        "max_impact": "high",
        "avg_confidence": 0.8,
        "sample_note_ids": ["n1", "n2"],
        "status": "accepted",
        "decision_reason": "meets gate",
        "recommended_change": "Improve retry context",
        "owner": "manager",
    }


def test_publish_feedback_backlog_dry_run(tmp_path: Path) -> None:
    save_feedback_backlog(tmp_path, [_sample_backlog_item()])
    policy = FeedbackPolicy(
        publish=FeedbackPublishPolicy(
            enabled=True,
            backend="codeberg",
            repository="owner/repo",
        )
    )

    result = publish_feedback_backlog(tmp_path, policy, limit=10, dry_run=True)
    assert result.attempted == 1
    assert result.published == 1
    assert result.failed == 0
    assert result.urls == ["dry-run://codeberg/issue"]


def test_publish_feedback_backlog_updates_backlog(monkeypatch, tmp_path: Path) -> None:
    save_feedback_backlog(tmp_path, [_sample_backlog_item()])
    policy = FeedbackPolicy(
        publish=FeedbackPublishPolicy(
            enabled=True,
            backend="codeberg",
            repository="owner/repo",
            token_env="CB_TOKEN",
        )
    )

    monkeypatch.setenv("CB_TOKEN", "token")
    monkeypatch.setattr(
        "devf.core.feedback_publish.create_codeberg_issue",
        lambda **_kwargs: "https://codeberg.org/owner/repo/issues/1",
    )

    result = publish_feedback_backlog(tmp_path, policy, limit=10, dry_run=False)
    assert result.published == 1
    backlog = (tmp_path / ".ai" / "feedback" / "backlog.yaml").read_text(encoding="utf-8")
    assert "published_issue_url" in backlog
    assert "https://codeberg.org/owner/repo/issues/1" in backlog


def test_publish_feedback_backlog_fallbacks_to_berg(monkeypatch, tmp_path: Path) -> None:
    save_feedback_backlog(tmp_path, [_sample_backlog_item()])
    policy = FeedbackPolicy(
        publish=FeedbackPublishPolicy(
            enabled=True,
            backend="codeberg",
            repository="owner/repo",
            token_env="MISSING_TOKEN",
        )
    )
    monkeypatch.delenv("MISSING_TOKEN", raising=False)

    called: dict[str, list[str]] = {}

    def _fake_run(cmd, capture_output, text, check):  # type: ignore[no-untyped-def]
        called["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=json.dumps({"html_url": "https://codeberg.org/owner/repo/issues/2"}),
            stderr="",
        )

    monkeypatch.setattr("devf.core.feedback_publish.subprocess.run", _fake_run)
    result = publish_feedback_backlog(tmp_path, policy, limit=10, dry_run=False)
    assert result.published == 1
    assert called["cmd"][:4] == ["berg", "--non-interactive", "issue", "create"]
    backlog = (tmp_path / ".ai" / "feedback" / "backlog.yaml").read_text(encoding="utf-8")
    assert "https://codeberg.org/owner/repo/issues/2" in backlog


def test_create_codeberg_issue_berg_fallback_error(monkeypatch) -> None:
    def _fake_run(cmd, capture_output, text, check):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="auth required")

    monkeypatch.setattr("devf.core.feedback_publish.subprocess.run", _fake_run)
    try:
        create_codeberg_issue(
            base_url="https://codeberg.org",
            repository="owner/repo",
            token="",
            title="x",
            body="y",
            labels=[],
        )
    except Exception as exc:  # noqa: BLE001
        assert "berg" in str(exc)
    else:
        raise AssertionError("expected berg fallback error")
