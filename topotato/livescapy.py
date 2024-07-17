#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2021  David Lamparter for NetDEF, Inc.
"""
Utility for running a live scapy packet capture in the background.
"""

import time
import logging
import asyncio

from typing import Optional

from scapy.supersocket import SuperSocket
from scapy.packet import Raw, Packet

from .timeline import EventMux, EventOrigin, TimedElement, Timeline
from .pcapng import EnhancedPacket, IfDesc, Context

_logger = logging.getLogger(__name__)


class TimedScapy(TimedElement):
    __slots__ = [
        "_pkt",
        "_final_future",
    ]

    def __init__(self, pkt):
        super().__init__()
        self._pkt = pkt
        self._final_future = None

    @property
    def ts(self):
        return (self._pkt.time, 0)

    @property
    def pkt(self):
        return self._pkt

    def serialize(self, context: Context):
        assert self._pkt.sniffed_on in context.ifaces

        frame_num = context.take_frame_num()
        ts = getattr(self._pkt, "time_ns", int(self._pkt.time * 1e9))

        epb = EnhancedPacket(context.ifaces[self._pkt.sniffed_on], ts, bytes(self._pkt))
        for match in self.match_for:
            epb.options.append(epb.OptComment("match_for: %r" % match))

        jsdata = {
            "type": "packet",
            "iface": self._pkt.sniffed_on,
            "dump": self._pkt.show(dump=True),
            "frame_num": frame_num,
        }

        return (jsdata, epb)


class LiveScapy(EventMux[TimedScapy], EventOrigin):
    """
    DOCME
    """

    _ifname: str
    _sock: Optional[SuperSocket]
    _task: asyncio.Task
    _queue: asyncio.Queue[TimedScapy]

    def __init__(self, ifname: str, sock: SuperSocket, timeline: Timeline):
        super().__init__()

        self._ifname = ifname
        self._sock = sock
        self._queue = asyncio.Queue()
        self._task = timeline.aioloop.create_task(self._taskfn(), name=repr(self))
        timeline.origin_add(self)

    def __repr__(self):
        return f"<{self.__class__.__name__} for {self._ifname}>"

    def _readable(self):
        maxdelay = time.time() + 0.1
        if self._sock is None:
            return

        while time.time() < maxdelay:
            try:
                pkt = self._sock.recv()
            except BlockingIOError:
                break

            assert pkt is not None

            if isinstance(pkt, Raw):
                # not exactly sure why/when this happens, scapy bug?
                rawpkt = pkt

                LLcls = getattr(self._sock, "LL", None)
                assert LLcls is not None and issubclass(LLcls, Packet)

                pkt = LLcls(bytes(rawpkt))
                assert pkt is not None

                if hasattr(rawpkt, "time"):
                    pkt.time = rawpkt.time
                if hasattr(rawpkt, "time_ns"):
                    pkt.time_ns = rawpkt.time_ns

            pkt.sniffed_on = self._ifname
            self._queue.put_nowait(TimedScapy(pkt))

    async def _taskfn(self):
        assert self._sock

        aioloop = asyncio.get_running_loop()
        try:
            aioloop.add_reader(self._sock.fileno(), self._readable)
            while True:
                event = await self._queue.get()
                self.dispatch([event])
        except asyncio.CancelledError:
            if self._sock is not None and self._sock.fileno() != -1:
                aioloop.remove_reader(self._sock.fileno())

    def close(self):
        assert self._sock is not None
        self._sock.close()
        self._sock = None

    async def terminate(self) -> None:
        self._task.cancel()
        await self._task

    def serialize(self, context: Context):
        """
        Plop out Interface Description Block for pcap-ng.
        """
        if self._ifname in context.ifaces:
            return

        context.ifaces[self._ifname] = len(context.ifaces)

        ifd = IfDesc()
        ifd.options.append(ifd.OptName(self._ifname))
        ifd.options.append(ifd.OptTSResol(9))
        yield (None, ifd)
