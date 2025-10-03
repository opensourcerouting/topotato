#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2024  David Lamparter for NetDEF, Inc.
"""
FD leak checks
"""

import sys
import os
import stat
import socket
import fcntl
import errno
import itertools

from typing import (
    Dict,
    Optional,
    Set,
    Tuple,
)

_types_s = ["SOCK_STREAM", "SOCK_DGRAM", "SOCK_SEQPACKET", "SOCK_RAW"]

_afs = {int(getattr(socket, n)): n for n in dir(socket) if n.startswith("AF_")}
_types = {int(getattr(socket, n)): n for n in _types_s if hasattr(socket, n)}
_ipprotos = {
    int(getattr(socket, n)): n for n in dir(socket) if n.startswith("IPPROTO_")
}

if sys.platform == "linux":
    from .nswrap import getnstype

else:

    def getnstype(fd: int) -> Optional[str]:  # pylint: disable=unused-argument
        return None


def _hexbytes(i):
    if not isinstance(i, bytes):
        return i
    return ":".join("%02x" % b for b in i)


def _socknamewrap(fn):
    try:
        name = fn()
    except OSError as e:
        if e.errno == errno.ENOTCONN:
            return "not_connected"
        if e.errno == errno.EOPNOTSUPP:
            return "not_supported"
        return f"E({e!r})"

    if isinstance(name, tuple):
        name = tuple(_hexbytes(i) for i in name)
    return repr(name)


# pylint: disable=too-many-locals,too-many-return-statements,too-many-branches
def fdinfo(fd: int) -> str:
    """
    Give a human-usable string description of an open file descriptor.

    Note this shouldn't raise an exception if something goes wrong since it is
    a debugging aid.
    """

    extra = []

    try:
        st = os.fstat(fd)
    except OSError as e:
        return f"stat_failed({e!r})"

    try:
        fdlink = os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        fdlink = None
    if fdlink:
        extra.append(f", link={fdlink!r}")

    try:
        fdflags = fcntl.fcntl(fd, fcntl.F_GETFD)
    except OSError:
        fdflags = 0
    if fdflags & fcntl.FD_CLOEXEC:
        extra.append(", cloexec")

    extrastr = "".join(extra)

    nstype = getnstype(fd)

    try:
        if stat.S_ISSOCK(st.st_mode):
            with socket.fromfd(fd, family=-1, type=-1) as s:
                # socket.fromfd does a dup() on the fd.  otherwise the fd
                # would be b0rked afterwards when s is closed
                assert s.fileno() != fd

                af = s.getsockopt(socket.SOL_SOCKET, socket.SO_DOMAIN)
                typ = s.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
                protocol = s.getsockopt(socket.SOL_SOCKET, socket.SO_PROTOCOL)

                sockname = _socknamewrap(s.getsockname)
                peername = _socknamewrap(s.getpeername)

            if af in {socket.AF_INET, socket.AF_INET6}:
                protostr = _ipprotos.get(protocol, str(protocol))
            else:
                protostr = str(protocol)

            return f"socket({_afs.get(af, str(af))}, {_types.get(typ, str(typ))}, {protostr}, sockname={sockname}, peername={peername}{extrastr})"

        if nstype is not None:
            major, minor = st.st_dev >> 8, st.st_dev & 0xFF
            return f"nsfd({nstype}, dev={major}:{minor}, inode={st.st_ino}, mode={stat.S_IMODE(st.st_mode):#o}{extrastr})"

        basic = {
            "file": stat.S_ISREG,
            "dir": stat.S_ISDIR,
            "chardev": stat.S_ISCHR,
            "blkdev": stat.S_ISBLK,
        }
        for kind, test in basic.items():
            if test(st.st_mode):
                major, minor = st.st_dev >> 8, st.st_dev & 0xFF
                return f"{kind}(dev={major}:{minor}, inode={st.st_ino}, mode={stat.S_IMODE(st.st_mode):#o}{extrastr})"

        if stat.S_ISFIFO(st.st_mode):
            return (
                f"pipe(inode={st.st_ino}, mode={stat.S_IMODE(st.st_mode):#o}{extrastr})"
            )

        if (fdlink or "").startswith("anon_inode:"):
            anontype = (fdlink or "").split(":", 1)[1]
            if anontype.startswith("[") and anontype.endswith("]"):
                anontype = anontype[1:-1]
            return f"{anontype}(inode={st.st_ino}, mode={stat.S_IMODE(st.st_mode):#o}{extrastr})"

        return f"?({st!r}{extrastr})"

    except OSError as e:
        return f"{st!r} [Exc: {e!r}]"


class FDState(Dict[int, Tuple[int, int, int]]):
    """
    Capture a snapshot of open file descriptor state.

    Does not hold FDs open, that would defeat the purpose.  Just record types
    and dev/ino numbers to compare.
    """

    stop_after = 256

    @staticmethod
    def _key(st: os.stat_result) -> Tuple[int, int, int]:
        return (stat.S_IFMT(st.st_mode), st.st_dev, st.st_ino)

    def __init__(self):
        super().__init__()

        stop = 0
        for fd in itertools.count():
            st = None
            try:
                st = os.fstat(fd)
            except OSError as e:
                if e.errno != errno.EBADF:
                    raise

                stop += 1
                if stop >= self.stop_after:
                    break
                continue

            self[fd] = self._key(st)
            stop = 0


class FDDelta:
    """
    Changes between two :py:class:`FDState`.
    """

    opened: Set[int]
    changed: Set[int]
    closed: Set[int]

    def __init__(self, before: FDState, after: FDState):
        self.before = before
        self.after = after

        k1 = set(before.keys())
        k2 = set(after.keys())
        self.opened = k2 - k1
        self.closed = k1 - k2
        self.changed = set()
        for fd in k1 & k2:
            if before[fd] != after[fd]:
                self.changed.add(fd)

    def __len__(self):
        """
        Cumulative size of constituent sets, mostly for quick boolean checks.
        """
        return len(self.opened) + len(self.closed) + len(self.changed)

    def asdict(self):
        items = ["opened", "changed", "closed"]
        return {k: {fd: fdinfo(fd) for fd in getattr(self, k)} for k in items}
