#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2022  David Lamparter for NetDEF, Inc.
"""
basic tests for topotato.leaks FD checks
"""

import sys
import os
import socket
import pytest

from topotato.leaks import fdinfo, FDState, FDDelta


def test_fdinfo_pipe():
    a, b = os.pipe()
    try:
        assert fdinfo(a).startswith("pipe")
    finally:
        os.close(a)
        os.close(b)


def test_fdinfo_socket():
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        i = fdinfo(a.fileno())
    finally:
        a.close()
        b.close()

    assert i.startswith("socket")
    assert "AF_UNIX" in i
    assert "SOCK_STREAM" in i


def test_fdinfo_sockaddr():
    with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as fd:
        fd.bind(("::1", 0))
        i = fdinfo(fd.fileno())

    assert i.startswith("socket")
    assert "AF_INET6" in i
    assert "SOCK_DGRAM" in i
    assert "IPPROTO_UDP" in i
    assert "'::1'" in i


def test_fdinfo_dev():
    with open("/dev/null", "r") as fd:
        assert fdinfo(fd.fileno()).startswith("chardev")


def test_fdinfo_ns():
    if sys.platform != "linux":
        pytest.skip("Linux only test")

    with open("/proc/self/ns/mnt", "r") as fd:
        i = fdinfo(fd.fileno())
    assert i.startswith("nsfd")
    assert "mnt" in i


def test_fdstate():
    state = FDState()
    assert 1 in state


def test_fddelta():
    state0 = FDState()
    state1 = FDState()

    a, b = os.pipe()

    state2 = FDState()

    c, d = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    os.dup2(d.fileno(), b)
    os.close(a)

    state3 = FDState()

    delta01 = FDDelta(state0, state1)
    assert len(delta01) == 0

    delta12 = FDDelta(state1, state2)
    assert a in delta12.opened
    assert b in delta12.opened

    delta23 = FDDelta(state2, state3)
    assert a in delta23.closed
    assert b in delta23.changed

    c.close()
    d.close()
