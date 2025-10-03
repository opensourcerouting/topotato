#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2025  David Lamparter for NetDEF, Inc.
"""
python log capturing for inclusion in HTML reports
"""

import os
import logging
import warnings

import typing
from typing import (
    cast,
    ClassVar,
    Optional,
)

import pytest

from .timeline import FrameworkEvent

if typing.TYPE_CHECKING:
    from .timeline import Timeline


_basepath = os.path.dirname(os.path.dirname(__file__))


class PyLogEvent(FrameworkEvent):
    """
    A captured python log message, as seen on a timeline's events.
    """

    typ = "pylog"
    pass_js = [
        "funcName",
        "levelname",
        "lineno",
        "module",
        "processName",
        "threadName",
        "taskName",
    ]

    __slots__ = []  # type: ignore

    def __init__(self, record: logging.LogRecord):
        super().__init__()
        self._ts = record.created
        self._data["pathname"] = os.path.relpath(record.pathname, _basepath)
        self._data["msg"] = record.getMessage()

        for key in self.pass_js:
            self._data[key] = cast(Optional[str], getattr(record, key, None))


class TimelineLogHandler(logging.Handler):
    """
    python `logging` handler that records log messages to timeline events

    This handler is attached once, on start of a session, and then for each
    test class gets "bound" to that test class' network instance's timeline.
    Inbetween, it's not bound to anything and won't do anything.

    There shouldn't be more than one instance of this object in existence.
    """

    _timeline: Optional["Timeline"]
    _session_handler: ClassVar["TimelineLogHandler"]
    """
    This class variable stores the one global instance of this class, for
    retrieval with :py:meth:`get`.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._timeline = None

    def emit(self, record: logging.LogRecord):
        if self._timeline:
            self._timeline.dispatch([PyLogEvent(record)])

    def bind(self, timeline: "Timeline"):
        """
        Direct recorded messages to the given timeline's event log.  Called
        on each test class' network instance startup.
        """
        if self._timeline is not None:
            warnings.warn(
                f"previous Timeline {self._timeline!r} still attached for logging"
            )

        self._timeline = timeline

    def unbind(self, timeline: "Timeline"):
        """
        Undo the binding to this timeline.  (The timeline is only used to check
        nothing went wrong somewhere inbetween.)
        """
        assert self._timeline == timeline
        self._timeline = None

    @classmethod
    def get(cls):
        """
        Retrieve the global instance of this class.  This is the correct way to
        access it from topotato code.
        """
        return cls._session_handler

    @pytest.hookimpl()
    @classmethod
    def pytest_sessionstart(cls, session):
        cls._session_handler = TimelineLogHandler(logging.DEBUG)
        # pylint: disable=protected-access
        session._topotato_log_handler = cls._session_handler

        rootlog = logging.getLogger("root")
        rootlog.addHandler(cls._session_handler)

        if rootlog.level > logging.DEBUG:
            for handler in rootlog.handlers:
                if handler.level == logging.NOTSET:
                    handler.setLevel(rootlog.level)
            rootlog.setLevel(logging.DEBUG)
