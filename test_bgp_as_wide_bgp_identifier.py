#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2022 Nathan Mangar

"""
rfc6286: Autonomous-System-Wide Unique BGP Identifier for BGP-4
Test if 'Bad BGP Identifier' notification is sent only to
internal peers (autonomous-system-wide). eBGP peers are not
affected and should work.
"""

__topotests_file__ = "bgp_as_wide_bgp_identifier/test_bgp_as_wide_bgp_identifier.py"
__topotests_gitrev__ = "4953ca977f3a5de8109ee6353ad07f816ca1774c"

# pylint: disable=wildcard-import, unused-wildcard-import

from topotato.v1 import *


@topology_fixture()
def topology(topo):
    """
    [ r1 ]
      |
    { s1 }--[ r3 ]
      |
    [ r2 ]

    """

    topo.router("r1").iface_to("s1").ip4.append("192.168.255.2/24")
    topo.router("r2").iface_to("s1").ip4.append("192.168.255.1/24")
    topo.router("r3").iface_to("s1").ip4.append("192.168.255.3/24")


class FRRConfR1(RouterFRR):
    zebra = ""

    bgpd = """
    #% extends "boilerplate.conf"
    #% block main
    router bgp 65001
     bgp router-id 10.10.10.10
     no bgp ebgp-requires-policy
     neighbor 192.168.255.1 remote-as 65002
     neighbor 192.168.255.1 timers 3 10
     neighbor 192.168.255.1 timers connect 1
    !
    #% endblock
    """


class FRRConfR2(RouterFRR):
    zebra = ""

    bgpd = """
    #% extends "boilerplate.conf"
    #% block main
    router bgp 65002
     bgp router-id 10.10.10.10
     no bgp ebgp-requires-policy
     neighbor 192.168.255.2 remote-as 65001
     neighbor 192.168.255.2 passive
     neighbor 192.168.255.2 timers 3 10
     neighbor 192.168.255.2 timers connect 1
     neighbor 192.168.255.3 remote-as 65002
     neighbor 192.168.255.3 passive
     neighbor 192.168.255.3 timers 3 10
     neighbor 192.168.255.3 timers connect 1
    !
    #% endblock
    """


class FRRConfR3(RouterFRR):
    zebra = ""

    bgpd = """
    #% extends "boilerplate.conf"
    #% block main
    router bgp 65002
     bgp router-id 10.10.10.10
     no bgp ebgp-requires-policy
     neighbor 192.168.255.1 remote-as 65002
     neighbor 192.168.255.1 timers 3 10
     neighbor 192.168.255.1 timers connect 1
    !
    #% endblock
    """


class Setup(TopotatoNetwork, topo=topology):
    r1: FRRConfR1
    r2: FRRConfR2
    r3: FRRConfR3


class TestBGPAsWideBGPIdentifier(TestBase, AutoFixture, setup=Setup):
    @topotatofunc
    def bgp_converge(self, _, r1):
        expected = {"192.168.255.1": {"bgpState": "Established"}}
        yield from AssertVtysh.make(
            r1,
            "bgpd",
            "show ip bgp neighbor 192.168.255.1 json",
            maxwait=5.0,
            compare=expected,
        )

    @topotatofunc
    def bgp_failed(self, _, r3):
        expected = {
            "192.168.255.1": {
                "lastNotificationReason": "OPEN Message Error/Bad BGP Identifier"
            }
        }
        yield from AssertVtysh.make(
            r3,
            "bgpd",
            "show ip bgp neighbor 192.168.255.1 json",
            maxwait=2.0,
            compare=expected,
        )
