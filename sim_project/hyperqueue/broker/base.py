from abc import ABC, abstractmethod
from hyperqueue.core.task import Task

class Broker(ABC):
    @abstractmethod
    def push(self, task: Task) -> None: ...
    @abstractmethod
    def pop(self) -> Task | None: ...

