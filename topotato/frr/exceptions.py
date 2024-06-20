#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2018-2021  David Lamparter for NetDEF, Inc.
"""
Exceptions raised by topotato FRR integration.
"""
# pylint: disable=duplicate-code

import re
from typing import Optional
import attr

from _pytest._code import ExceptionInfo
from _pytest._code.code import TerminalRepr, ReprFileLocation
from _pytest._io import TerminalWriter

from ..exceptions import TopotatoFail


class FRRStartupVtyshConfigFail(TopotatoFail):
    """
    The initial call to vtysh to load the integrated config failed.

    This will commonly happen if there is a mistake in the config.
    """

    router: str
    returncode: int
    stdout: str
    stderr: str

    # pylint: disable=too-many-arguments
    def __init__(
        self, router: str, returncode: int, stdout: str, stderr: str, config: str
    ):
        self.router = router
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.config = config
        super().__init__()

    def __str__(self):
        return f"{self.router}/startup-config-load"

    @attr.s(eq=False, auto_attribs=True)
    class TopotatoRepr(TerminalRepr):
        excinfo: ExceptionInfo

        @property
        def reprcrash(self) -> Optional["ReprFileLocation"]:
            # FIXME: figure out proper API?
            # pylint: disable=protected-access
            return self.excinfo._getreprcrash()

        def _errlinenos(self):
            exc = self.excinfo.value
            errlinenos = set()
            for line in exc.stderr.splitlines():
                if m := re.match(r"line (\d+):", line):
                    errlinenos.add(int(m.group(1)))
            return errlinenos

        def toterminal(self, tw: TerminalWriter) -> None:
            exc = self.excinfo.value
            tw.line("")
            tw.sep(
                " ",
                f"startup integrated-config load failed on {exc.router} (status {exc.returncode})",
                red=True,
                bold=True,
            )
            tw.line("")

            tw.line("stdout:")
            for line in exc.stdout.splitlines():
                tw.line(f"\t{line}")

            tw.line("stderr:")
            for line in exc.stderr.splitlines():
                tw.line(f"\t{line}")

            errlinenos = self._errlinenos()
            tw.line("configuration:")
            for i, line in enumerate(exc.config.rstrip("\n").splitlines()):
                lineno = i + 1
                tw.line(f"{lineno:4d}\t{line}", red=lineno in errlinenos)
