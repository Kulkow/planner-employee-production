"""Sample the worker's RSS during one job, including native OR-Tools memory."""

from threading import Event, Thread
from time import perf_counter

import psutil

from planner.domain.jobs import PlanningMetrics


class ProcessMemorySampler:
    def __init__(self, interval: float = .05, include_children: bool = False):
        if interval <= 0:
            raise ValueError('Sampling interval must be positive')
        self.interval = interval
        self._stop = Event()
        self._process = psutil.Process()
        self.include_children = include_children

    def _read_rss(self):
        rss = self._process.memory_info().rss
        if self.include_children:
            for child in self._process.children(recursive=True):
                try:
                    rss += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        return rss

    def _sample(self):
        self.peak = max(self.peak, self._read_rss())

    def _run(self):
        while not self._stop.wait(self.interval):
            self._sample()

    def __enter__(self):
        self.started = perf_counter()
        self.memory_start = self._read_rss()
        self.peak = self.memory_start
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._thread.join()
        self._sample()
        self.metrics = PlanningMetrics(perf_counter() - self.started, self.memory_start, self.peak, self.interval,
                                       'process_tree' if self.include_children else 'process')
