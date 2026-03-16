"""hast — AI-native development session manager."""

__version__ = "0.1.0"

from hast.core.config import Config, load_config, resolve_ai_dir, resolve_config_path
from hast.core.result import AutoResult, CoverageReport, DeadCodeEntry, FileCoverage, GoalResult

__all__ = [
    "AutoResult",
    "Config",
    "CoverageReport",
    "DeadCodeEntry",
    "FileCoverage",
    "GoalResult",
    "load_config",
    "resolve_ai_dir",
    "resolve_config_path",
]
