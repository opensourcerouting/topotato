# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026  David Lamparter for NetDEF, Inc.

# pylint: disable=too-many-arguments,too-many-positional-arguments
# pylint: disable=missing-module-docstring,duplicate-code

from typing import (
    Callable,
    Dict,
    Optional,
)

class Event:
    wd: int
    mask: int
    maskname: str
    path: str
    name: str
    pathname: str
    src_pathname: Optional[str]
    cookie: int
    dir: bool

class WatchManager:
    def add_watch(
        self,
        path: str,
        mask: int,
        proc_fun: Optional[Callable[[Event], None]] = None,
        rec: bool = False,
        auto_add: bool = False,
        do_glob: bool = False,
        quiet: bool = False,
        exclude_filter: Optional[Callable[[str], bool]] = None,
    ) -> Dict[str, int]:
        pass

    def get_fd(self) -> int:
        pass

class Notifier:
    def __init__(self, watch_manager: WatchManager):
        pass

    def read_events(self) -> None:
        pass

    def process_events(self) -> None:
        pass

IN_CREATE = 0
IN_MOVED_TO = 0
IN_DELETE = 0
