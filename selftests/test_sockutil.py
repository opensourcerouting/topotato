#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2022  David Lamparter for NetDEF, Inc.
"""
test topotato.sockutil
"""

# pylint: disable=redefined-outer-name
# pylint: disable=disallowed-name,import-error

import socket
import time
import asyncio
from dataclasses import dataclass
import pytest

from topotato.sockutil import sockext


@pytest.fixture
def sockpair():
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET, 0)
    return sockext(a), sockext(b)


@pytest.fixture
def sockpair_stream():
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM, 0)
    a, b = sockext(a), sockext(b)
    a.setsockopt_buf(socket.SO_SNDBUF, 8192)
    b.setsockopt_buf(socket.SO_RCVBUF, 8192)
    return a, b


def test_basic(sockpair):
    a, b = sockpair
    a.send(b"test")
    assert b.recv(4096) == b"test"


def test_doublewrap(sockpair):
    a, b = sockpair
    a, b = sockext(a), sockext(b)
    a.send(b"test")
    assert b.recv(4096) == b"test"


def test_bufsize(sockpair):
    a, b = sockpair
    a.setsockopt_buf(socket.SO_SNDBUF)
    b.setsockopt_buf(socket.SO_RCVBUF)
    a.send(b"test")
    assert b.recv(4096) == b"test"


@pytest.mark.parametrize("opt", [None, "SO_TIMESTAMP", "SO_TIMESTAMPNS"])
def test_stamp(sockpair, opt):
    a, b = sockpair
    if opt:
        b.setsockopt_platformdefault(socket.SOL_SOCKET, opt, 1)
    a.send(b"test")
    data, cmsg, _, _ = b.recvmsg(4096, 512)
    t = time.time_ns()

    assert data == b"test"
    ts = b.cmsg_fill_timestamp_ns(cmsg)
    assert t - 10_000_000_000 < ts < t + 1_000_000


@dataclass
class MonkeySocket:
    orig: socket.socket
    level: int
    optname: int
    failcount: int

    def __getattr__(self, k):
        return getattr(self.orig, k)

    def __post_init__(self):
        self.fails = []

    def setsockopt(self, level, optname, value):
        if level == self.level and optname == self.optname and self.failcount:
            self.failcount -= 1
            self.fails.append(value)
            raise OSError("injected failure")
        return self.orig.setsockopt(level, optname, value)


def test_buf_backoff():
    ar, br = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET, 0)
    am = MonkeySocket(ar, socket.SOL_SOCKET, socket.SO_SNDBUF, 3)
    a = sockext(am)  # type: ignore[arg-type]
    bm = MonkeySocket(br, socket.SOL_SOCKET, socket.SO_RCVBUF, 3)
    b = sockext(bm)  # type: ignore[arg-type]

    a.setsockopt_buf(socket.SO_SNDBUF, 2**22)
    assert am.fails == [2**22, 2**21 + 2**20, 2**21]
    b.setsockopt_buf(socket.SO_RCVBUF, 2**21)
    assert bm.fails == [2**21, 2**20 + 2**19, 2**20]
    a.send(b"test")
    assert b.recv(4096) == b"test"


def test_buf_hardfail():
    ar, _ = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET, 0)
    am = MonkeySocket(ar, socket.SOL_SOCKET, socket.SO_SNDBUF, 9999)
    a = sockext(am)  # type: ignore[arg-type]

    cur_size = a.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF)
    with pytest.raises(OSError):
        a.setsockopt_buf(socket.SO_SNDBUF, cur_size << 7)


def test_aio_recv(sockpair):
    a, b = sockpair

    async def aio_send():
        await asyncio.sleep(0.25)
        a.send(b"msg1")
        a.send(b"msg2")

    async def aio_recv():
        b.setblocking(False)

        assert await b.recv_async(4096, socket.MSG_PEEK) == b"msg1"
        rf = await b.recvfrom_async(4096, socket.MSG_PEEK)
        assert rf[0] == b"msg1"
        rm = await b.recvmsg_async(4096, 512, socket.MSG_PEEK)
        assert rm[0] == b"msg1"

        buf = bytearray(4096)

        blen = await b.recv_into_async(buf, flags=socket.MSG_PEEK)
        assert buf[:blen] == b"msg1"
        blen, _ = await b.recvfrom_into_async(buf, flags=socket.MSG_PEEK)
        assert buf[:blen] == b"msg1"
        blen, _, _, _ = await b.recvmsg_into_async([buf], 512, 0)
        assert buf[:blen] == b"msg1"

    async def aio():
        async with asyncio.timeout(5):
            async with asyncio.TaskGroup() as tg:
                tg.create_task(aio_recv())
                tg.create_task(aio_send())

    asyncio.run(aio())


def test_aio_recv_eof(sockpair):
    a, b = sockpair

    a.close()

    async def aio():
        async with asyncio.timeout(5):
            b.setblocking(False)
            assert await b.recv_async(4096, socket.MSG_PEEK) == b""

    asyncio.run(aio())


def test_aio_send_broken(sockpair):
    a, b = sockpair

    a.close()

    async def aio():
        async with asyncio.timeout(5):
            b.setblocking(False)
            with pytest.raises(BrokenPipeError):
                await b.sendall_async(b"test")

    asyncio.run(aio())


@pytest.mark.parametrize("sendfunc", ["send_async", "sendall_async"])
def test_aio_send_broken_delayed(sockpair_stream, sendfunc):
    a, b = sockpair_stream

    b.setblocking(False)
    b.send(bytes(262144))

    async def aio_delay_close():
        await asyncio.sleep(0.25)
        a.close()

    async def aio_send():
        with pytest.raises(BrokenPipeError):
            await getattr(b, sendfunc)(bytes(8192))

    async def aio():
        async with asyncio.timeout(5):
            async with asyncio.TaskGroup() as tg:
                tg.create_task(aio_delay_close())
                tg.create_task(aio_send())

    asyncio.run(aio())


def test_aio_sendall(sockpair_stream):
    a, b = sockpair_stream

    async def aio_send():
        a.setblocking(False)
        data = bytes(262144)
        await a.send_async(b"te")
        await a.sendall_async(b"st")
        await a.sendall_async(data)
        a.close()

    async def aio_recv():

        await asyncio.sleep(0.25)
        b.setblocking(False)
        initial = await b.recv_async(8)
        assert initial == b"test\0\0\0\0"

        total_read = len(initial)
        while rdd := await b.recv_async(4096):
            total_read += len(rdd)
        assert total_read == 262144 + 4

    async def aio():
        async with asyncio.timeout(5):
            async with asyncio.TaskGroup() as tg:
                tg.create_task(aio_recv())
                tg.create_task(aio_send())

    asyncio.run(aio())
