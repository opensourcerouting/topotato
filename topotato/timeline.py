#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2018-2022  David Lamparter for NetDEF, Inc.
"""
test timeline related utilities
"""

from abc import ABC, abstractmethod
import bisect
import time
import logging
import asyncio
from asyncio.events import AbstractEventLoop
from dataclasses import dataclass

import typing
from typing import (
    Any,
    Callable,
    ClassVar,
    Dict,
    Generator,
    Generic,
    List,
    Optional,
    Self,
    Tuple,
    Type,
    TypeVar,
)
from types import TracebackType

from .pcapng import Context, Block, Sink

if typing.TYPE_CHECKING:
    from typing import Awaitable
    from .base import TopotatoItem


_logger = logging.getLogger(__name__)


@dataclass
class TimingParams:
    delay: float
    maxwait: Optional[float]
    full_history: bool = False

    _start: Callable[[], float] = time.time

    def anchor(self, anchor: Callable[[], float]):
        self._start = anchor
        return self

    def ticks(self):
        now = time.time()

        # immediate tick
        yield float("-inf")

        start = self._start()
        nexttick = start + self.delay
        deadline = start + (self.maxwait or 0.0)

        while nexttick < deadline:
            if nexttick >= now:
                yield nexttick
            nexttick += self.delay

    def evaluate(self):
        start = self._start()
        return (start, start + (self.maxwait or 0.0))


class TimedElement(ABC):
    """
    Abstract base for test report items.

    Sortable by timestamp, and tracks if it fulfilled some test condition.
    """

    match_for: List["TopotatoItem"]
    """
    If this object satisfied some test condition, the test item is recorded here.
    """

    __slots__ = [
        "match_for",
    ]

    def __init__(self):
        super().__init__()
        self.match_for = []

    @property
    @abstractmethod
    def ts(self) -> Tuple[float, int]:
        """
        Timestamp for this item.

        First tuple item is an absolute unix timestamp.  Second is an integer
        sequence number for relative ordering (some log messages used to have
        only second precision, so the sequence number was necessary.
        """
        raise NotImplementedError()

    @abstractmethod
    def serialize(
        self, context: Context
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Block]]:
        """
        Serialize this item for report generation.

        Result tuple is a dict for JSON plus a Block for pcap-ng output.
        """
        raise NotImplementedError()

    def __lt__(self, other):
        return self.ts < other.ts


class FrameworkEvent(TimedElement):
    typ: ClassVar[str]

    def __init__(self):
        super().__init__()
        self._ts = time.time()
        self._data = {"type": self.typ}

    @property
    def ts(self):
        return (self._ts, 0)

    def serialize(self, context: Context):
        return (self._data, None)


class _Dummy(TimedElement):
    def __init__(self, ts: float):
        super().__init__()
        self._ts = ts

    @property
    def ts(self):
        return (self._ts, 0)

    def serialize(self, context: Context):
        return (None, None)


TE_contra = TypeVar("TE_contra", bound=TimedElement, contravariant=True)


class EventDispatch(Generic[TE_contra], ABC):
    @abstractmethod
    def dispatch(self, elements: List[TE_contra]): ...


class EventMux(EventDispatch[TE_contra]):
    history: List[TE_contra]

    _dispatch: List["EventDispatch[TE_contra]"]

    def __init__(self):
        super().__init__()
        self.history = []
        self._dispatch = []

    def dispatch(self, elements: List[TE_contra]):
        for sub in self._dispatch:
            sub.dispatch(elements)
        for element in elements:
            bisect.insort(self.history, element)

    def dispatch_add(
        self, receiver: EventDispatch[TE_contra], backfill: Optional[float] = None
    ):
        if backfill is not None:
            idx = bisect.bisect_left(self.history, _Dummy(backfill))
            receiver.dispatch(self.history[idx:])
        self._dispatch.append(receiver)

    def dispatch_remove(self, receiver: EventDispatch[TE_contra]):
        self._dispatch.remove(receiver)

    def observe(self, backfill: Optional[float] = None) -> "EventIter[TE_contra]":
        return EventIter(self, backfill=backfill)


class EventIter(EventDispatch[TE_contra]):
    source: EventMux[TE_contra]
    _queue: asyncio.Queue[List[TE_contra]]
    _pending: List[TE_contra]
    _backfill: Optional[float]

    def __init__(self, source: EventMux[TE_contra], backfill: Optional[float] = None):
        super().__init__()
        self.source = source
        self._queue = asyncio.Queue()
        self._backfill = backfill
        self._pending = []

    def dispatch(self, elements: List[TE_contra]):
        self._queue.put_nowait(elements)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> TE_contra:
        while not self._pending:
            elements = await self._queue.get()
            # if not elements:
            #    raise StopAsyncIteration()
            self._pending.extend(elements)
        return self._pending.pop(0)

    def __enter__(self) -> Self:
        self.source.dispatch_add(self, self._backfill)
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        tb: Optional["TracebackType"],
    ):
        self.source.dispatch_remove(self)


class EventOrigin:
    # pylint: disable=unused-argument, no-self-use
    def serialize(
        self, context: Context
    ) -> Generator[Tuple[Optional[Dict[str, Any]], Optional[Block]], None, None]:
        """
        Generate possible header blocks for this event source.

        Only pcap-ng is currently handled, dicts for JSON are thrown away.
        """
        yield from []

    async def terminate(self) -> None:
        pass


class Timeline(EventMux[TimedElement]):
    """
    Sorted list of TimedElement|s
    """

    aioloop: AbstractEventLoop
    origins: List[EventOrigin]

    def __init__(self, aioloop: AbstractEventLoop, *args, **kwargs):
        self.aioloop = aioloop
        super().__init__(*args, **kwargs)
        self.origins = []

    def serialize(self, sink: Sink) -> Tuple[List, Dict[str, Any]]:
        ret = []
        toplevel: Dict[str, Any] = {}

        for origin in self.origins:
            for jsdata, block in origin.serialize(sink):
                if block:
                    sink.write(block)
                if jsdata:
                    for k, v in jsdata.items():
                        toplevel.setdefault(k, {}).update(v)

        for item in self.history:
            jsdata, block = item.serialize(sink)
            if jsdata:
                ret.append({"ts": item.ts[0], "data": jsdata})
            if block:
                sink.write(block)
        return ret, toplevel

    def origin_add(self, origin: EventOrigin):
        self.origins.append(origin)
