from hyperqueue.core.task import Task
from hyperqueue.worker.processor import Processor

def test_exponential_backoff():
    task = Task("1", "func", [], retries=0, max_retries=3)
    # ... verification logic ...

