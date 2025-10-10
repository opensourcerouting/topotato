#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2018-2021  David Lamparter for NetDEF, Inc.
"""
FreeBSD jail abstractions.
"""
# pylint: disable=duplicate-code

import subprocess
import time
import asyncio

from typing import (
    List,
)

from .utils import self_or_kwarg


class FreeBSDJail:
    name: str
    process: subprocess.Popen
    jid: int

    def __init__(self, **kw):
        self_or_kwarg(self, kw, "name")
        super().__init__(**kw)

    async def start(self):
        # FIXME: use async subprocess
        # pylint: disable=consider-using-with
        self.process = subprocess.Popen(
            [
                "jail",
                "-i",
                "-c",
                "path=/",
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
if __name__ == "__main__":
    ns = FreeBSDJail(name="test")
    ns.start()
    ns.check_call(["ifconfig", "-a"])
    ns.check_call(["/bin/sh", "-c", "sleep 3"])
    time.sleep(3)
    ns.end()
    print("ended")
    time.sleep(3)
