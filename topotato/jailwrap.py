#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2018-2021  David Lamparter for NetDEF, Inc.
"""
FreeBSD jail abstractions.
"""
# pylint: disable=duplicate-code

import os
import subprocess
import time
import pathlib
import re
import tempfile
import logging
import asyncio

from typing import (
    List,
)

from .utils import self_or_kwarg


_logger = logging.getLogger(__name__)

_paths_not_needed = {
    pathlib.Path("/boot"),
    pathlib.Path("/tmp"),
    pathlib.Path("/var"),
    # separate volumes on ZFS images
    pathlib.Path("/usr/obj"),
    pathlib.Path("/usr/ports"),
    pathlib.Path("/usr/src"),
}


class FreeBSDJail:
    name: str
    process: subprocess.Popen
    jid: int

    _umount: List[str]

    def __init__(self, **kw):
        self_or_kwarg(self, kw, "name")
        super().__init__(**kw)
        self.basedir = None
        self.rootdir = None

    async def start(self):
        # FIXME: use async subprocess

        mounts = subprocess.check_output(["mount"], encoding="ASCII").splitlines()
        binds: List[str] = []
        for mount in mounts:
            m = re.match(r"^.*? on (?P<path>.*) \((?P<fs>[^ ]+)[,)]", mount)
            if m is None:
                _logger.warning("failed to parse mount output: %r", mount)
                continue

            path, fs = m.group("path"), m.group("fs")
            if fs in ["cd9660", "devfs"]:
                continue

            pathobj = pathlib.Path(path)
            for not_needed in _paths_not_needed:
                if pathobj.is_relative_to(not_needed):
                    break
            else:
                binds.append(path)

        binds.sort()

        self.basedir = tempfile.mkdtemp(prefix="topo_")
        self.rootdir = self.basedir + "/root"
        os.mkdir(self.rootdir)

        _logger.info("nullfs mounts: %s", ", ".join(binds))

        self._umount = []
        for bind in binds:
            dest = self.rootdir + bind
            subprocess.check_call(["mount", "-t", "nullfs", bind, dest])
            self._umount.insert(0, dest)

            union = f"{self.basedir}/_{str(bind).replace('/', '__')}"
            os.mkdir(union)
            subprocess.check_call(
                ["mount", "-t", "unionfs", "-o", "noatime", union, dest]
            )
            # alternatively, -o union:
            # subprocess.check_call(["mount", "-t", "nullfs", "-o", "union", union, dest])
            self._umount.insert(0, dest)

        subprocess.check_call(["mount", "-t", "nullfs", "/tmp", self.rootdir + "/tmp"])
        self._umount.insert(0, self.rootdir + "/tmp")
        subprocess.check_call(["mount", "-t", "nullfs", "/dev", self.rootdir + "/dev"])
        self._umount.insert(0, self.rootdir + "/dev")

        # pylint: disable=consider-using-with
        self.process = subprocess.Popen(
            [
                "jail",
                "-i",
                "-c",
                f"path={self.rootdir}",
                "host.hostname=%s" % self.name,
                "vnet=new",
                "command=/bin/sh",
                "-c",
                "echo IGN; read IGN || true",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            shell=False,
        )
        assert self.process.stdout is not None

        self.jid = int(self.process.stdout.readline())
        self.process.stdout.readline()

    async def end(self):
        assert self.process.stdin is not None

        subprocess.check_call(["jail", "-r", "%d" % self.jid])

        self.process.stdin.close()
        self.process.wait()
        del self.process

        # unfortunately, there seem to be some file system reference leaks
        # somewhere in FreeBSD that randomly make this umount not work :(
        # give it a few tries, at least
        umount_next = self._umount
        for _ in range(0, 3):
            umount = umount_next
            umount_next = []

            while umount:
                path = umount.pop(0)
                try:
                    subprocess.check_call(["umount", path])
                except subprocess.CalledProcessError as e:
                    _logger.warning("failed to umount %r: %r", path, e)
                    umount_next.append(path)
            if not umount_next:
                break

            await asyncio.sleep(0.5)

    def prefix(self, kwargs) -> List[str]:
        ret = ["jexec"]
        if "cwd" in kwargs:
            cwd = kwargs.pop("cwd")
            ret.extend(["-d", cwd])
        ret.append(str(self.jid))

        # LD_PRELOAD'ing jexec is... not helpful.  Run "env" inside instead.
        if kwargs.get("env", {}).get("LD_PRELOAD"):
            ld_preload = kwargs["env"].pop("LD_PRELOAD")
            ret.extend(["env", f"LD_PRELOAD={ld_preload}"])
        return ret

    def popen(self, cmdline, *args, **kwargs):
        # pylint: disable=consider-using-with
        return subprocess.Popen(self.prefix(kwargs) + cmdline, *args, **kwargs)

    async def popen_async(self, cmdline: List[str], *args, **kwargs):
        # pylint: disable=consider-using-with
        return await asyncio.create_subprocess_exec(
            *(self.prefix(kwargs) + cmdline), *args, **kwargs
        )

    def check_call(self, cmdline, *args, **kwargs):
        return subprocess.check_call(self.prefix(kwargs) + cmdline, *args, **kwargs)

    def check_output(self, cmdline, *args, **kwargs):
        return subprocess.check_output(self.prefix(kwargs) + cmdline, *args, **kwargs)


# pylint: disable=duplicate-code
async def _test():
    ns = FreeBSDJail(name="test")
    await ns.start()
    ns.check_call(["ifconfig", "-a"])
    ns.check_call(["mount"])
    ns.check_call(["/bin/sh", "-c", "sleep 3"])
    time.sleep(3)
    await ns.end()
    print("ended")
    time.sleep(3)


if __name__ == "__main__":
    asyncio.run(_test())
