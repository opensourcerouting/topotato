#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2022 Nathan Mangar

"""
Test if minimum-holdtime works.
"""

__topotests_file__ = "bgp_minimum_holdtime/test_bgp_minimum_holdtime.py"
__topotests_gitrev__ = "4953ca977f3a5de8109ee6353ad07f816ca1774c"

# pylint: disable=wildcard-import, unused-wildcard-import

from topotato.v1 import *


@topology_fixture()
def topology(topo):
    """
    [ r1 ]
      |
    { s1 }
      |
    [ r2 ]

    """

    topo.router("r1").iface_to("s1").ip4.append("192.168.255.1/24")
    topo.router("r2").iface_to("s1").ip4.append("192.168.255.2/24")


class FRRConfR1(RouterFRR):
    zebra = ""

    bgpd = """
    #% extends "boilerplate.conf"
    #% block main
    router bgp 65000
     bgp minimum-holdtime 20
     neighbor 192.168.255.2 remote-as 65001
     neighbor 192.168.255.2 timers 3 10
     neighbor 192.168.255.2 timers connect 1
    ## this test will fail if r1 is passive!
    !
    #% endblock
    """


class FRRConfR2(RouterFRR):
    zebra = ""

    bgpd = """
    #% extends "boilerplate.conf"
    #% block main
    router bgp 65001
     no bgp ebgp-requires-policy
     neighbor 192.168.255.1 remote-as 65000
     neighbor 192.168.255.1 timers 3 10
     neighbor 192.168.255.1 passive
    !
    #% endblock
    """


class Setup(TopotatoNetwork, topo=topology):
    r1: FRRConfR1
    r2: FRRConfR2


class TestBGPMinimumHoldtime(TestBase, AutoFixture, setup=Setup):
    @topotatofunc
    def bgp_neighbor_check_if_notification_sent(self, _, r1):
        expected = {
            "192.168.255.2": {
                "connectionsEstablished": 0,
                "lastNotificationReason": "OPEN Message Error/Unacceptable Hold Time",
                "lastResetDueTo": "BGP Notification send",
            }
        }
        yield from AssertVtysh.make(
            r1,
            "bgpd",
            "show ip bgp neighbor 192.168.255.2 json",
            maxwait=5.0,
            compare=expected,
        )
