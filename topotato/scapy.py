#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2018-2021  David Lamparter for NetDEF, Inc.
"""
Scapy packet-sending integration for topotato.
"""

import logging
import asyncio

import typing
from typing import (
    cast,
    Any,
    Optional,
)

import pytest

from .assertions import TopotatoModifier

if typing.TYPE_CHECKING:
    from .nswrap import LinuxNamespace

_logger = logging.getLogger(__name__)

try:
    # pylint: disable=no-name-in-module
    from scapy.layers.l2 import Ether  # type: ignore[import-untyped]
    from .scapyext import NetnsL2Socket

    scapy_exc = None

except ImportError as e:
    _logger.error("scapy not available: %r", e)
    Ether = None  # type: ignore
    NetnsL2Socket = None  # type: ignore
    scapy_exc = e

__all__ = ["ScapySend"]


class ScapySend(TopotatoModifier):
    _rtr: Any
    _iface: str
    _pkt: Any
    _repeat: Optional[int]
    _interval: Optional[float]

    posargs = ["rtr", "iface", "pkt"]

    # pylint: disable=too-many-arguments
    def __init__(self, *, name, rtr, iface, pkt, repeat=None, interval=None, **kwargs):
        path = "/".join([l.__name__ for l in pkt.layers()])
        name = "%s:%s/scapy[%s/%s]" % (name, rtr.name, iface, path)
        super().__init__(name=name, **kwargs)

        self._rtr = rtr
        self._iface = iface
        self._repeat = repeat
        self._interval = interval

        # this is intentionally here so we don't have a hard dependency on
        # scapy.

        if not isinstance(pkt, Ether):
            pkt = Ether() / pkt

        self._pkt = pkt

    async def _async(self):
        if scapy_exc:
            pytest.skip(str(scapy_exc))

        router = cast("LinuxNamespace", self.instance.routers[self._rtr.name])
        with router:
            sock = NetnsL2Socket(iface=self._iface, promisc=False)
            sock.send(self._pkt)

        if self._repeat:
            for _ in range(1, self._repeat):
                await asyncio.sleep(self._interval or 0.0)
                with router:
                    sock.send(self._pkt)

        sock.close()

    def __call__(self):
        self.timeline.aioloop.run_until_complete(self._async())
