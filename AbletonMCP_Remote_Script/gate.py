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
    __slots__ = ("work", "finished", "value", "failure", "abandoned", "due",
                 "started", "done", "late")

    def __init__(self, work, due):
        self.work = work
        self.due = due
        self.finished = threading.Event()
        self.value = None
        self.failure = None
        self.abandoned = False
        self.started = False  # these three change under the gate's lock only
        self.done = False
        self.late = None      # called with the job once it is done, if the caller gave up


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

    def call(self, work, timeout, wait_ticks=0, late=None):
        """Run ``work()`` on the main thread and return what it returns.

        Called from any thread. Exceptions raised by ``work`` are re-raised
        in the caller. If Live does not get to the job in time (a modal
        dialog is open, Live is busy rendering) the caller gets a timeout
        error and the job is dropped if it has not started yet.

        If it has started, it cannot be stopped: it runs to its end, and
        ``late(job)`` is then called on the main thread, so the caller can
        still account for what the job did (the hub journals it). The
        timeout error says so with ``details["still_running"]``.

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
            with self._lock:
                running = job.started and not job.done
                if not job.started:
                    job.abandoned = True
                elif running:
                    job.late = late
            if job.started and not running:
                job.finished.wait()  # it ended just now: a normal result
            else:
                message = "Live did not finish the command within %g s " % timeout
                if running:
                    message += ("and is still working on the current step; that step takes "
                                "effect when Live gets to its end")
                    raise CommandError(TIMEOUT, message, still_running=True)
                message += "(a dialog may be open, or Live is busy); it was not run"
                raise CommandError(TIMEOUT, message)
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
            if job.due >= self._tick and not job.abandoned:
                held_back.append(job)
                continue
            with self._lock:
                if job.abandoned:
                    continue
                job.started = True
            try:
                job.value = job.work()
            except BaseException as failure:  # handed to the waiting thread
                job.failure = failure
            with self._lock:
                job.done = True
                late = job.late
            job.finished.set()
            done += 1
            if late is not None:
                try:
                    late(job)
                except Exception:
                    # the caller is gone; late() logs its own trouble, this only
                    # keeps the main thread going
                    self.late_failures = getattr(self, "late_failures", 0) + 1
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
