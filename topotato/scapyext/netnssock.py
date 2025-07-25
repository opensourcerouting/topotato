#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2021  David Lamparter for NetDEF, Inc.
"""
Scapy netns-socket support.
"""
# pylint: disable=protected-access

import struct
import socket
import errno
import threading
from fcntl import ioctl

from typing import cast

import scapy.fields  # type: ignore[import-untyped]
import scapy.arch.linux  # type: ignore[import-untyped]
import scapy.layers.l2  # type: ignore[import-untyped]
from scapy.config import conf  # type: ignore[import-untyped]

SIOCGIFADDR = 0x8915


# pylint: disable=too-many-ancestors
class NetnsL2Socket(scapy.arch.linux.L2Socket):
    """
    scapy L2socket, but with fixups when switching network namespaces

    Note this does not switch namespaces by itself.  It just contains the
    necessary support to create the socket in a specific namespace and work
    with that, e.g.:

    with change_ns(...):
        sock = NetnsL2Socket(iface=...)

    sock.send()

    Should correctly work without having to switch the namespace again to send
    the packet.
    """

    _tls = threading.local()
    _tls.send_socket = None

    def __init__(self, *args, **kwargs):
        # scapy buffers interface data, which is now invalid because wrong ns
        if hasattr(conf, "ifaces") and hasattr(conf.ifaces, "reload"):
            conf.ifaces.reload()

        # this causes exceptions during shutdown if the interface is gone
        kwargs["promisc"] = False
        super().__init__(*args, **kwargs)
        scapy.arch.linux.set_promisc(self.ins, self.iface)

        with socket.socket() as ipsock:
            try:
                req = struct.pack("16s16x", str(self.iface).encode("utf8"))
                self._local_ipv4 = ioctl(ipsock, SIOCGIFADDR, req)[20:24]
            except OSError as e:
                if e.errno != errno.EADDRNOTAVAIL:
                    raise
                self._local_ipv4 = b"\x00\x00\x00\x00"

    def send(self, x):
        try:
            NetnsL2Socket._tls.send_socket = self
            return super().send(x)
        finally:
            NetnsL2Socket._tls.send_socket = None


conf.L2socket = NetnsL2Socket


class _SourceMACFixup:
    """
    Replace "default fill-ins" in SourceMACField with netns-aware ones.

    Otherwise, the code tries to use data from the current netns when the
    packet is built.

    NB: only works correctly when used with send(), building a packet
    separately can't be compatible with netns because the netns to be used is
    not known at all.
    """

    def i2h(self, pkt, x):
        # i2h is inherited, hence Field below rather than MACField.  hacky. :/
        selfc = cast(scapy.fields.Field, self)
        return scapy.layers.l2.MACField.i2h(selfc, pkt, x)

    scapy.layers.l2.SourceMACField.i2h = i2h  # type: ignore

    def i2m(self, pkt, x):
        if x is None:
            nsock = NetnsL2Socket._tls.send_socket
            if nsock:
                return nsock.ins.getsockname()[4]

        selfc = cast(scapy.layers.l2.MACField, self)
        return scapy.layers.l2.MACField.i2m(selfc, pkt, self.i2h(pkt, x))

    scapy.layers.l2.SourceMACField.i2m = i2m  # type: ignore


class _SourceIPFixup:
    """
    Same as _SourceMACFixup, but for source IP
    """

    def i2h(self, pkt, x):
        selfc = cast(scapy.fields.IPField, self)
        return scapy.fields.IPField.i2h(selfc, pkt, x)

    scapy.fields.SourceIPField.i2h = i2h  # type: ignore

    def i2m(self, pkt, x):
        if x is None:
            nsock = NetnsL2Socket._tls.send_socket
            if nsock:
                return nsock._local_ipv4

        selfc = cast(scapy.fields.IPField, self)
        return scapy.fields.IPField.i2m(selfc, pkt, self.i2h(pkt, x))

    scapy.fields.SourceIPField.i2m = i2m  # type: ignore
