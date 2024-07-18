#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2023  David Lamparter for NetDEF, Inc.
"""
gevent-or-not topotato integration
"""


class _FakeGreenlet:
    """
    Pretend to be a gevent.Greenlet when gevent is not available.

    FIXME: deprecated, remove
    """

    def __init__(self, run, *args, **kwargs):
        super().__init__()
        self._run = run
        self._args = args
        self._kwargs = kwargs
        self.value = None

    def start(self):
        self.value = self._run(*self._args, **self._kwargs)

    def join(self):
        return None

    @classmethod
    def spawn(cls, function, *args, **kwargs):
        gl = cls(function, *args, **kwargs)
        gl.start()
        return gl


Greenlet = _FakeGreenlet
spawn = _FakeGreenlet.spawn
