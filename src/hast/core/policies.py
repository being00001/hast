"""Policy bundle loading for auto loop."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hast.core.retry_policy import RetryPolicy, load_retry_policy
from hast.core.risk_policy import RiskPolicy, load_risk_policy
from hast.core.triage import TRIAGE_POLICY_VERSION


@dataclass(frozen=True)
class AutoPolicies:
    retry: RetryPolicy
    risk: RiskPolicy
    triage_version: str = TRIAGE_POLICY_VERSION

    @property
    def version(self) -> str:
        return f"triage:{self.triage_version}|retry:{self.retry.version}|risk:{self.risk.version}"


def load_auto_policies(root: Path) -> AutoPolicies:
    return AutoPolicies(
        retry=load_retry_policy(root),
        risk=load_risk_policy(root),
    )
