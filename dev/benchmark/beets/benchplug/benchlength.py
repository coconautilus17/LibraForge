"""Give each mock file its real book duration: the mock audio is 1 s of
silence, and beets scores a candidate on track length."""
import json
import os

from beets.plugins import BeetsPlugin

ROOT = "/audiobooks/"
MINUTES = {b["folder"]: b["minutes"] for b in json.load(open(os.environ["BENCH_BOOKS"]))}


class BenchLength(BeetsPlugin):
    def __init__(self):
        super().__init__()
        self.register_listener("import_task_created", self.set_lengths)

    def set_lengths(self, task, session):
        for item in task.items:
            path = item.path.decode() if isinstance(item.path, bytes) else str(item.path)
            minutes = MINUTES.get(os.path.dirname(path)[len(ROOT):])
            if minutes:
                item.length = minutes * 60
        return [task]
