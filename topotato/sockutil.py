# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026  David Lamparter for NetDEF, Inc.
"""
``socket`` extensions that really should be part of Python proper.
"""

# note imports with underscore prefix to not pollute wildcard import
import sys
import socket
import struct
import time
import asyncio
import contextlib
import functools

import typing as _T

if _T.TYPE_CHECKING:
    from collections.abc import Buffer  # novermin

    R = _T.TypeVar("R")

_sockopts = {
    "linux": {
        "SO_TIMESTAMP": 63,
        "SO_TIMESTAMPNS": 64,
    }
}


def _sockopt(optname: str) -> _T.Optional[int]:
    optval = getattr(socket, optname, None)
    if optval is None:
        optval = _sockopts.get(sys.platform, {}).get(optname)
    return optval


@contextlib.contextmanager
def async_reader(
    fd,
    handler: "_T.Callable[..., None]",
    *args,
    aioloop: _T.Optional[asyncio.AbstractEventLoop] = None,
):
    """
    Register & undo a reader function with aioloop's ``add_reader``.

    Ensures the reader doesn't remain installed if something goes wrong.
    """
    aioloop = aioloop or asyncio.get_running_loop()
    assert aioloop is not None
    aioloop.add_reader(fd, handler, *args)
    try:
        yield fd
    finally:
        aioloop.remove_reader(fd)


@contextlib.contextmanager
def async_writer(
    fd,
    handler: "_T.Callable[..., None]",
    *args,
    aioloop: _T.Optional[asyncio.AbstractEventLoop] = None,
):
    """
    Register & undo a writer function with aioloop's ``add_writer``.

    Ensures the writer doesn't remain installed if something goes wrong.
    """
    aioloop = aioloop or asyncio.get_running_loop()
    assert aioloop is not None
    aioloop.add_writer(fd, handler, *args)
    try:
        yield fd
    finally:
        aioloop.remove_writer(fd)


async def _async_do(
    async_which,
    fd,
    handler: "_T.Callable[[], R]",
    aioloop: _T.Optional[asyncio.AbstractEventLoop] = None,
) -> "R":
    try:
        return handler()
    except (BlockingIOError, InterruptedError):
        pass

    aioloop = aioloop or asyncio.get_running_loop()
    assert aioloop is not None
    fut = aioloop.create_future()

    def _do_read():
        if fut.done():
            return
        try:
            result = handler()
        except (BlockingIOError, InterruptedError):
            return
        # pylint: disable=broad-exception-caught
        except Exception as e:
            fut.set_exception(e)
        else:
            fut.set_result(result)

    with async_which(fd, _do_read, aioloop=aioloop):
        return await fut


async def async_do_read(
    fd,
    handler: "_T.Callable[[], R]",
    aioloop: _T.Optional[asyncio.AbstractEventLoop] = None,
) -> "R":
    """
    Asynchronously run a non-blocking receive function.

    Provides the glue logic to funnel the result through a future, and sets
    up a reader through ``aioloop.add_reader``.
    """
    return await _async_do(async_reader, fd, handler, aioloop)


async def async_do_write(
    fd,
    handler: "_T.Callable[[], R]",
    aioloop: _T.Optional[asyncio.AbstractEventLoop] = None,
) -> "R":
    """
    Asynchronously run a non-blocking transmit function.

    Provides the glue logic to funnel the result through a future, and sets
    up a writer through ``aioloop.add_writer``.
    """
    return await _async_do(async_writer, fd, handler, aioloop)


class sockext(socket.socket):
    """
    Wrapper that adds a few methods to a socket.socket.
    """

    __slots__ = [
        "_sockext_socket",
    ]

    _sockext_socket: socket.socket

    # pylint: disable=super-init-not-called
    def __init__(self, wrap: socket.socket):
        # __init__ will be called again even if __new__ returns an existing object
        if not hasattr(self, "_sockext_socket"):
            self._sockext_socket = wrap

    def __new__(cls, wrap: _T.Union[socket.socket, "sockext"]):
        """
        Get a ``sockext`` for a ``socket``.

        This may be called opportunistically, so don't double-wrap.
        """
        if isinstance(wrap, sockext):
            return wrap
        return super().__new__(cls)

    def __getattribute__(self, k):
        """
        ``socket.socket`` can't be subclassed, no ``__dict__`` :(
        """
        if k in ["_sockext_socket", "__class__"] or k in sockext.__dict__:
            return object.__getattribute__(self, k)
        _sockext_socket = object.__getattribute__(self, "_sockext_socket")
        return getattr(_sockext_socket, k)

    async def recv_async(self, bufsize: int, flags: int = 0) -> bytes:
        recv = functools.partial(self.recv, bufsize, flags)
        return await async_do_read(self, recv)

    async def recv_into_async(
        self, buffer: "Buffer", nbytes: int = 0, flags: int = 0
    ) -> int:
        recv_into = functools.partial(self.recv_into, buffer, nbytes, flags)
        return await async_do_read(self, recv_into)

    async def recvfrom_async(
        self, bufsize: int, flags: int = 0
    ) -> _T.Tuple[bytes, _T.Any]:
        recvfrom = functools.partial(self.recvfrom, bufsize, flags)
        return await async_do_read(self, recvfrom)

    async def recvfrom_into_async(
        self, buffer: "Buffer", nbytes: int = 0, flags: int = 0
    ) -> _T.Tuple[int, _T.Any]:
        recvfrom_into = functools.partial(self.recvfrom_into, buffer, nbytes, flags)
        return await async_do_read(self, recvfrom_into)

    async def recvmsg_async(
        self, bufsize: int, ancbufsize: int = 0, flags: int = 0
    ) -> _T.Tuple[bytes, _T.List[_T.Tuple[int, int, bytes]], int, _T.Any]:
        recvmsg = functools.partial(self.recvmsg, bufsize, ancbufsize, flags)
        return await async_do_read(self, recvmsg)

    async def recvmsg_into_async(
        self, buffers: "_T.Iterable[Buffer]", ancbufsize: int = 0, flags: int = 0
    ) -> _T.Tuple[int, _T.List[_T.Tuple[int, int, bytes]], int, _T.Any]:
        recvmsg_into = functools.partial(self.recvmsg_into, buffers, ancbufsize, flags)
        return await async_do_read(self, recvmsg_into)

    async def send_async(self, data: "Buffer", flags: int = 0) -> int:
        send = functools.partial(self.send, data, flags)
        return await async_do_write(self, send)

    async def sendall_async(self, data: "Buffer", flags: int = 0) -> None:
        buf = memoryview(data)

        while buf:
            try:
                sent = self.send(buf, flags)
            except (BlockingIOError, InterruptedError):
                break
            else:
                buf = buf[sent:]
        else:
            return

        aioloop = asyncio.get_running_loop()
        fut = aioloop.create_future()

        def _do_send():
            nonlocal buf

            if fut.done():
                return
            try:
                sent = self.send(buf, flags)
            except (BlockingIOError, InterruptedError):
                return
            # pylint: disable=broad-exception-caught
            except Exception as e:
                fut.set_exception(e)
            else:
                buf = buf[sent:]
                if not buf:
                    fut.set_result(None)

        with async_writer(self, _do_send, aioloop=aioloop):
            return await fut

    def cmsg_fill_timestamp_ns(self, cmsgs: _T.List[_T.Tuple[int, int, bytes]]) -> int:
        """
        Retrieve timestamp from cmsg data, or fill in ``time_ns()``.

        Attempts to use the best value carried in the supplied cmsg, otherwise
        uses ``time.time_ns()`` to get the current timestamp.
        """
        ret: _T.Optional[int] = None

        for level, opt, data in cmsgs:
            if level != socket.SOL_SOCKET:
                continue
            if opt == _sockopt("SO_TIMESTAMPNS"):
                tv_sec, tv_nsec = struct.unpack("@QI", data[: struct.calcsize("@QI")])
                return tv_sec * 1000000000 + tv_nsec
            if opt == _sockopt("SO_TIMESTAMP"):
                tv_sec, tv_usec = struct.unpack("@QI", data[: struct.calcsize("@QI")])
                ret = tv_sec * 1000000000 + tv_usec * 1000
                # wait and see if we get nanoseconds

        if ret is None:
            ret = time.time_ns()
        return ret

    def setsockopt_platformdefault(
        self, level: int, optname: str, value: _T.Union[bytes, int]
    ) -> bool:
        """
        Set a platform-specific sockopt, or do nothing if it's not available.
        """
        optval = _sockopt(optname)
        if optval is None:
            return False
        self.setsockopt(level, optval, value)
        return True

    def setsockopt_buf(self, bufoption: int, size: int = 8388608) -> int:
        """
        Set socket send/receive buffer size, going down exponentially if rejected

        :param bufoption: Which option to set, should be either
            ``socket.SO_RCVBUF`` or ``socket.SO_SNDBUF``.
        :return: actual size set.
        """
        orig_size = size
        bufdflt = self.getsockopt(socket.SOL_SOCKET, bufoption)
        while size > bufdflt:
            try:
                self.setsockopt(socket.SOL_SOCKET, bufoption, size)
                break
            except OSError:
                try:
                    # half step
                    self.setsockopt(socket.SOL_SOCKET, bufoption, size >> 1 | size >> 2)
                    break
                except OSError:
                    size >>= 1
                    if size == 0 or size < (orig_size >> 6):
                        raise

        return self.getsockopt(socket.SOL_SOCKET, bufoption)
