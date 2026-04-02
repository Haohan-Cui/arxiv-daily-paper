from __future__ import annotations

import threading
from dataclasses import dataclass


class PipelineCancelled(Exception):
    pass


@dataclass
class ProgressEvent:
    stage: str
    message: str
    state: str = "info"
    percent: float | None = None


class PipelineController:
    def __init__(self) -> None:
        self._pause_event = threading.Event()
        self._cancel_event = threading.Event()

    @property
    def paused(self) -> bool:
        return self._pause_event.is_set()

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def pause(self) -> None:
        self._pause_event.set()

    def resume(self) -> None:
        self._pause_event.clear()

    def cancel(self) -> None:
        self._cancel_event.set()
        self._pause_event.clear()

    def checkpoint(self) -> None:
        if self._cancel_event.is_set():
            raise PipelineCancelled("pipeline cancelled by user")
        while self._pause_event.is_set():
            if self._cancel_event.is_set():
                raise PipelineCancelled("pipeline cancelled by user")
            self._cancel_event.wait(0.1)
