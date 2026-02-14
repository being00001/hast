import time
from hyperqueue.broker.base import Broker
from hyperqueue.core.task import Task

class Processor:
    def __init__(self, broker: Broker):
        self.broker = broker

    def start(self):
        while True:
            task = self.broker.pop()
            if task:
                self.process(task)

    def process(self, task: Task):
        print(f"Processing {task.id}")
        # TODO: Implement retry logic here

