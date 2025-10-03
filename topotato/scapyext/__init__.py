#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2021  David Lamparter for NetDEF, Inc.
"""
Scapy extensions for topotato.

Used as * import to get the "normally useful" bits.
"""

import sys

from .pim import PIM_Hdr, PIM_Bootstrap, PIM_CandidateRP

if sys.platform == "linux":
    from .netnssock import NetnsL2Socket
else:
    # this won't work, but it's less wrong :/
    from scapy.arch import L2bpfSocket as NetnsL2Socket

del sys
