from dataclasses import dataclass
from typing import Any

@dataclass
class Task:
    id: str
    func_name: str
    args: list[Any]
    retries: int = 0
    max_retries: int = 3

