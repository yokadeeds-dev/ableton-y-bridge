# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
"""Hand-over of work from socket threads into Live's main thread.

Live's Python API may only be touched from the thread Live itself calls the
script on. Socket threads therefore never call the API. They put a job on
this gate and sleep; the control surface empties the gate from
``update_display`` (Live calls that on its main thread about ten times a
second) and wakes the sleeper with the outcome.
"""

import collections
import threading

from .errors import BUSY, TIMEOUT, CommandError


class _Job(object):
    __slots__ = ("work", "finished", "value", "failure", "abandoned", "due")

    def __init__(self, work, due):
        self.work = work
        self.due = due
        self.finished = threading.Event()
        self.value = None
        self.failure = None
        self.abandoned = False


class MainThreadGate(object):
    def __init__(self):
        self._jobs = collections.deque()
        self._lock = threading.Lock()
        self._home = None
        self._open = True
        self._tick = 0

    def adopt_current_thread(self):
        """Declare the calling thread to be Live's main thread."""
        self._home = threading.get_ident()

    def on_home_thread(self):
        return self._home is not None and threading.get_ident() == self._home

    def pending(self):
        with self._lock:
            return len(self._jobs)

    def call(self, work, timeout, wait_ticks=0):
        """Run ``work()`` on the main thread and return what it returns.

        Called from any thread. Exceptions raised by ``work`` are re-raised
        in the caller. If Live does not get to the job in time (a modal
        dialog is open, Live is busy rendering) the caller gets a timeout
        error and the job is dropped if it has not started yet.

        ``wait_ticks`` holds the job back for that many further display
        ticks, for reading state Live only updates after the current one.
        """
        if self.on_home_thread():
            return work()
        job = _Job(work, self._tick + wait_ticks)
        with self._lock:
            if not self._open:
                raise CommandError(BUSY, "the bridge is shutting down")
            self._jobs.append(job)
        if not job.finished.wait(timeout):
            job.abandoned = True
            raise CommandError(
                TIMEOUT,
                "Live did not finish the command within %.0f s "
                "(a dialog may be open, or Live is busy)" % timeout,
            )
        if job.failure is not None:
            raise job.failure
        return job.value

    def drain(self, limit=32):
        """Run queued jobs. Must be called on the main thread only."""
        self._tick += 1
        done = 0
        held_back = []
        while done < limit:
            with self._lock:
                if not self._jobs:
                    break
                job = self._jobs.popleft()
            if job.abandoned:
                continue
            if job.due >= self._tick:
                held_back.append(job)
                continue
            try:
                job.value = job.work()
            except BaseException as failure:  # handed to the waiting thread
                job.failure = failure
            job.finished.set()
            done += 1
        if held_back:
            with self._lock:
                self._jobs.extendleft(reversed(held_back))
        return done

    def close(self):
        """Refuse new jobs and release everybody who is still waiting."""
        with self._lock:
            self._open = False
            stranded = list(self._jobs)
            self._jobs.clear()
        for job in stranded:
            job.failure = CommandError(BUSY, "the bridge was shut down")
            job.finished.set()
