#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2021  David Lamparter for NetDEF, Inc.
"""
Utility for running a live scapy packet capture in the background.
"""

import time
import logging
import asyncio

from typing import (
    Callable,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
)

from scapy.supersocket import SuperSocket
from scapy.packet import Raw, Packet

from .timeline import EventMux, EventOrigin, EventDispatch, TimedElement, Timeline
from .pcapng import EnhancedPacket, IfDesc, Context

_logger = logging.getLogger(__name__)


class TimedScapy(TimedElement):
    __slots__ = [
        "_pkt",
        "_final_future",
        "_local_emit",
    ]

    def __init__(self, pkt):
        super().__init__()
        self._pkt = pkt
        self._final_future = None
        self._local_emit = False

    def __repr__(self):
        return f"<TimedScapy @{self._pkt.time}: {self._pkt!r}>"

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
            "local_emit": self._local_emit,
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

    def packet_observer(self) -> "PacketObserver":
        """
        Create :py:class:`PacketObserver` for this interface.
        """
        return PacketObserver(self)

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


_PacketSubclass = TypeVar("_PacketSubclass", bound="Packet")


class PacketObserver(EventDispatch[TimedScapy]):
    """
    Entry point for programmatic packet TX/RX in tests.

    This is used in an async function as async context manager to follow along
    a sequence of packets.  It looks something like this::

        from scapy.layers.l2 import Ether
        from scapy.layers.inet import IP, TCP
        from topotato.topobase import NetworkInstance
        from topotato.livescapy import LiveScapy

        async def packets_test(net: NetworkInstance):
            lscapy: LiveScapy = net.scapys["lan123"].live

            async with lscapy.packet_observer() as obs:
                # wait for a SYN
                await obs([(TCP, lambda tcp: tcp.flags.S)])
                # send SYN-ACK (values omitted)
                obs.send(Ether() / IP() / TCP())
                # wait for ACK
                await obs([(TCP, lambda tcp: tcp.flags.A)])
                # ...
                obs.send(Ether() / IP() / TCP())
    """

    _queue: asyncio.Queue[TimedScapy]

    def __init__(self, live: LiveScapy):
        self._live = live
        self._queue = asyncio.Queue()

    async def __aenter__(self) -> "PacketObserver":
        """
        Start this packet observer - register live scapy RX handler

        :return: always self
        """
        self._live.dispatch_add(self)
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        """
        Stop this packet observer - undo registration from start
        """
        self._live.dispatch_remove(self)

    async def __call__(
        self,
        conds: Optional[
            List[Tuple[Type[_PacketSubclass], Callable[[_PacketSubclass], bool]]]
        ] = None,
    ) -> TimedScapy:
        """
        Wait for a RX packet matching given conditions.

        Internally queued, i.e. all packets since the last call are checked to
        find a match (there is no race condition losing packets that arrive
        while the code is doing other things.)

        :param conds: list of requirements on the packet, each item a tuple of
            a scapy layer class and an evaluation function.  All conditions in
            the list have to match on the packet.
        """
        conds = conds or []

        while tpkt := await self._queue.get():
            if tpkt._local_emit:
                continue
            for layercls, fn in conds:
                layer = tpkt.pkt.getlayer(layercls)
                if layer is None:
                    break
                if not fn(layer):
                    break
            else:
                return tpkt

        raise RuntimeError("packet queue unexpectedly terminated")

    # pylint: disable=protected-access
    def send(self, pkt: Packet) -> None:
        """
        Send - and record in the log - a packet

        Since injected packets are not received back on packet sockets, this
        function must be used in order to have the sent packet show up on the
        HTML report.
        """
        assert self._live._sock

        t = time.time_ns()

        self._live._sock.send(pkt)
        pkt.sniffed_on = self._live._ifname
        pkt.time_ns = t
        pkt.time = t * 1e-9
        tpkt = TimedScapy(pkt)
        tpkt._local_emit = True
        self._live._queue.put_nowait(tpkt)

    def dispatch(self, elements: List[TimedScapy]):
        """
        :py:class:`LiveScapy` hook point to throw received packets onto queue

        Do not call this directly, the context manager enter/exit will register
        appropriately for this to be called from the live scapy listening code.
        """
        for e in elements:
            self._queue.put_nowait(e)
