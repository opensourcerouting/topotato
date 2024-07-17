# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2023  Bruno Bernard for NetDEF, Inc.
"""
FRRouting integration for topotato
"""

from .core import (
    FRRSetupError,
    FRRSetup,
    FRRRouterNS,
    TimedVtysh,
)
from .params import (
    FRRParams,
)

RouterFRR = FRRParams
FRRConfigs = FRRParams
