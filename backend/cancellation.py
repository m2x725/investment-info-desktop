"""Cancellation is a control signal, not a recoverable research failure."""
import re
import threading
import time


class JobCancelled(BaseException):
    pass


class JobControl:
    def __init__(self):
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.reports, self.outputs, self.runs = set(), set(), set()
        self.closers = set()
        self.future = None
        self.started = time.monotonic()
        self.phase_started = self.started
        self.phase = "queued"
        self.timings = {}
        self.preview_run = None
        self.cleanup_pending = False
        self.cancel_started = None

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

    def phase_change(self, phase):
        now=time.monotonic()
        with self.lock:
            if phase!=self.phase:
                self.timings[self.phase]=round(self.timings.get(self.phase,0)+now-self.phase_started,3)
                self.phase_started=now;self.phase=phase

    def metadata(self):
        with self.lock:
            now=time.monotonic();timings=dict(self.timings)
            timings[self.phase]=round(timings.get(self.phase,0)+now-self.phase_started,3)
            return {'phase':self.phase,'stage_seconds':timings,'elapsed_seconds':round(now-self.started,3),
                    'preview_run':self.preview_run,'cleanup_pending':self.cleanup_pending,
                    'cancel_cleanup_seconds':round(now-self.cancel_started,3) if self.cancel_started else None}
