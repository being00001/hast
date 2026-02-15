"""Language profile helpers for multi-language RED/GREEN and gate logic."""

from __future__ import annotations

import fnmatch
import shlex
from pathlib import Path

from devf.core.config import Config, GateConfig
from devf.core.goals import Goal

_LANGUAGE_ORDER = ("python", "rust")


def language_from_path(path: str) -> str | None:
    if path.endswith(".py"):
        return "python"
    if path.endswith(".rs"):
        return "rust"
    return None


def resolve_goal_languages(
    root: Path,
    goal: Goal,
    config: Config,
    changed_files: list[str] | None = None,
) -> list[str]:
    if goal.languages:
        return [lang for lang in goal.languages if _is_enabled(config, lang)]

    detected: set[str] = set()

    for rel in changed_files or []:
        lang = language_from_path(rel)
        if lang and _is_enabled(config, lang):
            detected.add(lang)

    if not detected:
        if _is_enabled(config, "rust") and _looks_like_rust_repo(root):
            detected.add("rust")
        if _is_enabled(config, "python") and _looks_like_python_repo(root):
            detected.add("python")

    if not detected and _is_enabled(config, "python"):
        detected.add("python")

    return [lang for lang in _LANGUAGE_ORDER if lang in detected]


def collect_test_files(
    changed_files: list[str],
    config: Config,
    languages: list[str],
) -> list[str]:
    selected: list[str] = []
    for rel in changed_files:
        for lang in languages:
            profile = config.language_profiles.get(lang)
            if not profile or not profile.enabled:
                continue
            if any(fnmatch.fnmatch(rel, pattern) for pattern in profile.test_file_globs):
                selected.append(rel)
                break
    return sorted(set(selected))


def assertion_patterns(config: Config, languages: list[str]) -> list[str]:
    patterns: list[str] = []
    for lang in languages:
        profile = config.language_profiles.get(lang)
        if not profile or not profile.enabled:
            continue
        patterns.extend(profile.assertion_patterns)
    return patterns


def trivial_assertions(config: Config, languages: list[str]) -> list[str]:
    patterns: list[str] = []
    for lang in languages:
        profile = config.language_profiles.get(lang)
        if not profile or not profile.enabled:
            continue
        patterns.extend(profile.trivial_assertions)
    return patterns


def build_targeted_test_commands(
    config: Config,
    languages: list[str],
    test_files: list[str],
) -> list[tuple[str, str]]:
    by_language = _split_files_by_language(test_files)
    commands: list[tuple[str, str]] = []
    for idx, lang in enumerate(languages):
        profile = config.language_profiles.get(lang)
        if not profile or not profile.enabled:
            continue
        command = profile.targeted_test_command.strip()
        if not command:
            continue

        lang_files = by_language.get(lang, [])
        if "{files}" in command:
            if not lang_files:
                continue
            command = command.replace("{files}", " ".join(shlex.quote(path) for path in lang_files))
        name = f"{lang}_targeted_{idx + 1}"
        commands.append((name, command))
    return commands


def gate_commands_for_languages(
    config: Config,
    languages: list[str],
) -> list[tuple[str, str]]:
    checks: list[tuple[str, str]] = []
    seen: set[str] = set()
    for lang in languages:
        profile = config.language_profiles.get(lang)
        if not profile or not profile.enabled:
            continue
        for idx, command in enumerate(profile.gate_commands, start=1):
            cmd = command.strip()
            if not cmd:
                continue
            name = _guess_check_name(lang, cmd, idx, config)
            key = f"{name}:{cmd}"
            if key in seen:
                continue
            seen.add(key)
            checks.append((name, cmd))
    return checks


def apply_pytest_reliability_flags(
    command: str,
    gate: GateConfig,
    *,
    include_reruns: bool,
) -> str:
    """Append pytest reliability flags when configured and applicable."""
    raw = command.strip()
    if not raw:
        return command

    try:
        tokens = shlex.split(raw)
    except ValueError:
        return command

    if not _is_pytest_invocation(tokens):
        return command

    if gate.pytest_parallel and not _has_option(tokens, "-n", "--numprocesses"):
        tokens.extend(["-n", gate.pytest_workers])

    if gate.pytest_random_order and not _has_option(tokens, "--random-order"):
        tokens.append("--random-order")

    if (
        include_reruns
        and gate.pytest_reruns_on_flaky > 0
        and not _has_option(tokens, "--reruns")
    ):
        tokens.extend(["--reruns", str(gate.pytest_reruns_on_flaky)])

    return shlex.join(tokens)


def _split_files_by_language(test_files: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for rel in test_files:
        lang = language_from_path(rel)
        if lang is None:
            continue
        grouped.setdefault(lang, []).append(rel)
    for lang_files in grouped.values():
        lang_files.sort()
    return grouped


def _is_pytest_invocation(tokens: list[str]) -> bool:
    if not tokens:
        return False
    first = tokens[0].lower()
    if first.endswith("pytest") or first == "pytest":
        return True
    if (
        len(tokens) >= 3
        and first.startswith("python")
        and tokens[1] == "-m"
        and tokens[2] == "pytest"
    ):
        return True
    return False


def _has_option(tokens: list[str], *options: str) -> bool:
    option_set = set(options)
    for token in tokens:
        if token in option_set:
            return True
        for option in option_set:
            if token.startswith(f"{option}="):
                return True
            if option == "-n" and token.startswith("-n") and token != "-n":
                return True
    return False


def _is_enabled(config: Config, language: str) -> bool:
    profile = config.language_profiles.get(language)
    return bool(profile and profile.enabled)


def _looks_like_python_repo(root: Path) -> bool:
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        return True
    if any(root.glob("requirements*.txt")):
        return True
    return (root / "src").exists() and any((root / "src").glob("**/*.py"))


def _looks_like_rust_repo(root: Path) -> bool:
    if (root / "Cargo.toml").exists():
        return True
    return (root / "src").exists() and any((root / "src").glob("**/*.rs"))


def _guess_check_name(language: str, command: str, idx: int, config: Config) -> str:
    lowered = command.lower()
    if language == "python":
        if command.strip() == config.test_command.strip():
            return "pytest"
        if "ruff" in lowered:
            return "ruff"
        if "mypy" in lowered:
            return "mypy"
        return f"python_check_{idx}"

    if language == "rust":
        if lowered.startswith("cargo test"):
            return "rust_test"
        if lowered.startswith("cargo fmt"):
            return "rust_fmt"
        if lowered.startswith("cargo clippy"):
            return "rust_clippy"
        return f"rust_check_{idx}"

    return f"{language}_check_{idx}"
