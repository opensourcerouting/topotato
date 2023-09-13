#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2022-2026  David Lamparter for NetDEF, Inc.
"""
Live-capture syslog messages from virtual systems and feed them into topotato.

.. note:

   This is NOT used for FRR - look at topotato.frr.livelog for that!
"""

import socket
import syslog
import re
import logging

import typing
from typing import (
    Optional,
    Tuple,
)

from .timeline import EventMux, EventOriginSocket, TimedElement, Timeline
from .pcapng import JournalExport, Context

if typing.TYPE_CHECKING:
    from .network import TopotatoNetwork


_logger = logging.getLogger(__name__)


# pylint: disable=too-many-instance-attributes
class SyslogMessage(TimedElement):
    """
    syslog (or rather ``/dev/log``) message received and recorded in topotato"

    This is used to redirect/capture syslog output from things running in
    test hosts.  Note ``/dev/log`` uses a pseudo RFC 3164 format **without**
    the hostname field.  However, some software uses its own code to write to
    that socket, and then gets the format "wrong" (which considering there's
    no spec for it isn't exactly surprising).
    """

    # pylint: disable=duplicate-code
    _prios = {
        syslog.LOG_EMERG: "emerg",
        syslog.LOG_ALERT: "alert",
        syslog.LOG_CRIT: "crit",
        syslog.LOG_ERR: "error",
        syslog.LOG_WARNING: "warn",
        syslog.LOG_NOTICE: "notif",
        syslog.LOG_INFO: "info",
        syslog.LOG_DEBUG: "debug",
    }

    rawmsg: bytes
    """
    Message as received on ``/dev/log``.
    """

    text: str
    """
    Syslog message body/text
    """

    _ts: float
    _prio: int
    _facility: Optional[int]

    router: "TopotatoNetwork.RouterNS"
    """
    Host this message was captured on
    """

    prio_re = re.compile(r"^<(?P<prio>\d+)>")
    ts_re = re.compile(r"^[A-Z][a-z][a-z] [1-3 ][0-9] \d\d:\d\d:\d\d ")
    tag_re = re.compile(r"^(?P<tag>[^ :\[]+)(?:\[(?P<pid>\d+)\])?: ")

    def __init__(self, router: "TopotatoNetwork.RouterNS", rawmsg: bytes, ts: int):
        super().__init__()

        self._ts_ns = ts
        self._ts = ts * 1e-9

        self.router = router
        self.rawmsg = rawmsg

        rawtext = rawmsg.rstrip(b"\0").decode("UTF-8")

        if m := self.prio_re.match(rawtext):
            raw_prio = int(m.group("prio"))
            self._prio = raw_prio & 0x7
            self._facility = raw_prio >> 3

            rawtext = rawtext[m.end() :]
        else:
            self._prio = 3
            self._facility = None

        if m := self.ts_re.match(rawtext):
            rawtext = rawtext[m.end() :]

        if m := self.tag_re.match(rawtext):
            self._tag = m.group("tag")
            self._pid = m.group("pid")
            if self._pid:
                self._pid = int(self._pid)
            rawtext = rawtext[m.end() :]
        else:
            self._tag = None
            self._pid = None

        self.text = rawtext

    @property
    def ts(self) -> Tuple[float, int]:
        return (self._ts, 0)

    def serialize(self, context: Context):
        """
        Output log message to JSON and pcap-ng for test report.
        """
        _ = context.take_frame_num()

        data = {}
        data.update(
            {
                "type": "syslog",
                "router": self.router.name,
                "text": self.text,
                "prio": self.prio_text,
            }
        )

        ts_usec = int(self._ts * 1000000)

        sde_fields = {
            "__REALTIME_TIMESTAMP": "%d" % (ts_usec,),
            "MESSAGE": self.text,
            "PRIORITY": self._prio,
            "_HOSTNAME": self.router.name,
            "_COMM": self._tag or "unknown",
            #    "RAWMSG": self.rawmsg,
        }
        if self._tag:
            sde_fields["SYSLOG_IDENTIFIER"] = self._tag
        if self._pid is not None:
            sde_fields["SYSLOG_PID"] = self._pid
        if self._facility is not None:
            sde_fields["SYSLOG_FACILITY"] = self._facility

        sde = JournalExport(sde_fields)

        # NB: wireshark currently can't decode comments on systemd journal
        # items, the pcap-ng block has no options field...
        for match in self.match_for:
            sde.options.append(sde.OptComment("match for %r" % match))

        return (data, sde)

    @property
    def prio_text(self) -> str:
        """
        Shortened textual representation of log message priority.
        """
        return self._prios.get(self._prio & 7, "???")

    def __str__(self):
        return self.text

    def __repr__(self):
        return "<%s @%.6f %r>" % (self.__class__.__name__, self._ts, self.text)


class LiveSyslog(EventOriginSocket, EventMux[SyslogMessage]):
    """
    Handles a syslog UNIX socket, receive messages and dispatch into topotato.

    This is instantiated with a fd that should refer to a ``SOCK_DGRAM`` (or
    possibly ``SOCK_SEQPACKET``) socket.  Normally that socket would be bound
    to ``/dev/log`` in the target system.

    Note ``SOCK_DGRAM`` sockets won't flag EOF on the last "connection" drop
    (because there are no connections), so the receiver task needs to be
    terminated explicitly.
    """

    _router: "TopotatoNetwork.RouterNS"

    def __init__(
        self,
        router: "TopotatoNetwork.RouterNS",
        timeline: Timeline,
        rdfd: "socket.socket",
    ):
        super().__init__(rdfd)

        self._router = router

        self._rdfd.setsockopt_buf(socket.SO_RCVBUF)
        for opt in ["SO_TIMESTAMPNS", "SO_TIMESTAMP"]:
            if self._rdfd.setsockopt_platformdefault(socket.SOL_SOCKET, opt, 1):
                break

        self._start(timeline)

    def __repr__(self):
        return f"<{self.__class__.__name__} for {self._router.name}>"

    async def _run(self) -> bool:
        rddata, cmsg, _, _ = await self._rdfd.recvmsg_async(16384, 512)
        ts = self._rdfd.cmsg_fill_timestamp_ns(cmsg)
        logmsg = SyslogMessage(self._router, rddata, ts)
        self.dispatch([logmsg])

        return True
