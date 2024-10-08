#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2018-2021  David Lamparter for NetDEF, Inc.
"""
FreeBSD jail abstractions.
"""

import subprocess
import time

from .utils import self_or_kwarg


class FreeBSDJail:
    name: str
    process: subprocess.Popen
    jid: int

    def __init__(self, **kw):
        self_or_kwarg(self, kw, "name")
        super().__init__(**kw)

    def start(self):
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

    def end(self):
        assert self.process.stdin is not None

        subprocess.check_call(["jail", "-r", "%d" % self.jid])

        self.process.stdin.close()
        self.process.wait()
        del self.process

    def prefix(self):
        return ["jexec", str(self.jid)]

    def popen(self, cmdline, *args, **kwargs):
        # pylint: disable=consider-using-with
        return subprocess.Popen(self.prefix() + cmdline, *args, **kwargs)

    def check_call(self, cmdline, *args, **kwargs):
        return subprocess.check_call(self.prefix() + cmdline, *args, **kwargs)

    def check_output(self, cmdline, *args, **kwargs):
        return subprocess.check_output(self.prefix() + cmdline, *args, **kwargs)


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
