#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2018-2021  David Lamparter for NetDEF, Inc.
"""
Topotato topology/config fixtures
"""

import functools

from .parse import Topology
from .toponom import Network


# this is * imported for all tests
__all__ = [
    "mkfixture",
    "mkfixture_pytest",
    "topology_fixture",
    "AutoFixture",
]


def mkfixture_pytest(*args, **kwargs):
    """
    wrap pytest.fixture to allow loading test classes without pulling in
    all of pytest.  Intended to be overridden/replaced when writing a
    standalone script that imports some test class.
    """
    # pylint: disable=import-outside-toplevel
    from pytest import fixture

    return fixture(*args, **kwargs)


mkfixture = mkfixture_pytest


def topology_fixture():
    """
    Fixture to use for defining a test topology

    The topology is immediately instantiated from the docstring, and only one
    instance is created.  The function can modify the result topology (e.g.
    to change IP addresses) through its function parameter.
    """

    def getwrap(fn):
        topo = Topology(fn.__doc__)

        net = Network()
        net.load_parse(topo)

        # partial() used here so fnwrap() doesn't have the topo arg in its
        # function signature.  (would otherwise be visible on
        # inspect.signature() which pytest uses for fixtures)

        fnwrap = functools.partial(fn, net)
        fnwrap()

        net.auto_num()
        net.auto_ifnames()
        net.auto_ip4()
        net.auto_ip6()

        @functools.wraps(fnwrap)
        def wrap():
            return net

        wrap.__module__ = fn.__module__
        wrap.__doc__ = fn.__doc__

        fixture = mkfixture(scope="module")(wrap)
        fixture.net = net
        return fixture

    return getwrap


class AutoFixture:
    pass
