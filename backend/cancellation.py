"""Cancellation is a control signal, not a recoverable research failure."""
import re
import threading


class JobCancelled(BaseException):
    pass


class JobControl:
    def __init__(self):
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.reports, self.outputs, self.runs = set(), set(), set()
        self.closers = set()
        self.future = None

    def check(self):
        if self.cancelled.is_set():raise JobCancelled()

    def record(self, sql, args, rowid):
        table = re.search(r'INSERT(?:\s+OR\s+\w+)?\s+INTO\s+(\w+)', sql, re.I)
        if not table:return
        name = table.group(1).lower()
        if name == 'reports':self.reports.add(rowid)
        elif name == 'research_outputs':self.outputs.add(rowid)
        elif name == 'research_runs':self.runs.add(args[0])

    def register(self, closer):
        with self.lock:
            self.check()
            self.closers.add(closer)

    def unregister(self, closer):
        with self.lock:self.closers.discard(closer)

    def discard(self, db):
        for rid in self.reports:db.execute('DELETE FROM reports WHERE id=?', (rid,))
        for oid in self.outputs:db.execute('DELETE FROM research_outputs WHERE id=?', (oid,))
        for run in self.runs:
            db.execute('DELETE FROM research_sections WHERE run_id=?', (run,))
            db.execute('DELETE FROM research_runs WHERE id=?', (run,))
