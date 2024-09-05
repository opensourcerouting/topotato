#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2023  David Lamparter for NetDEF, Inc.
"""
Dummy-ish types for type checking with mypy.
"""

import typing
from typing import (
    Protocol,
)

if typing.TYPE_CHECKING:
    from .control import Control
    from .interactive import Interactive
    from .pretty import PrettySession
    from .frr.core import FRRSetup


class ISession(Protocol):
    """
    Subset of pytest session that is accessed by topotato inner logic

    While pytest has this StashKey mechanism for this, it is in itself useful
    to constrain what pytest parts of the session are accessed by general
    topotato bits.
    """

    control: "Control"
    interactive_session: "Interactive"
    pretty_session: "PrettySession"
    frr: "FRRSetup"
