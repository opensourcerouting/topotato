#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2022 Nathan Mangar

"""
Test if default-originate works with match operations.
And verify if set operations work as well.
"""

__topotests_file__ = "bgp_default_route_route_map_match_set/test_bgp_default-originate_route-map_match_set.py"
__topotests_gitrev__ = "acddc0ed3ce0833490b7ef38ed000d54388ebea4"

# pylint: disable=invalid-name, missing-class-docstring, missing-function-docstring, line-too-long, consider-using-f-string, wildcard-import, unused-wildcard-import, f-string-without-interpolation

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


class FRRConfR1(RouterFRR):
    zebra = ""

    bgpd = """
    #% extends "boilerplate.conf"
    #% block main
    router bgp 65000
     no bgp ebgp-requires-policy
     neighbor {{ routers.r2.ifaces[0].ip4[0].ip }} remote-as 65001
     neighbor {{ routers.r2.ifaces[0].ip4[0].ip }} timers connect 1
     neighbor {{ routers.r2.ifaces[0].ip4[0].ip }} timers 3 10
     address-family ipv4 unicast
      network 192.168.13.0/24 route-map internal
      neighbor {{ routers.r2.ifaces[0].ip4[0].ip }} default-originate route-map default
    !
    bgp community-list standard default seq 5 permit 65000:1
    !
    route-map default permit 10
     match community default
     set metric 123
     set as-path prepend 65000 65000 65000
    !
    route-map internal permit 10
     set community 65000:1
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
     neighbor {{ routers.r1.ifaces[0].ip4[0].ip }} remote-as 65000
     neighbor {{ routers.r1.ifaces[0].ip4[0].ip }} passive
     neighbor {{ routers.r1.ifaces[0].ip4[0].ip }} timers 3 10
    !
    #% endblock
    """


class Setup(TopotatoNetwork, topo=topology):
    r1: FRRConfR1
    r2: FRRConfR2


class BGPDefaultOriginateRouteMapMatchSet(TestBase, AutoFixture, setup=Setup):
    # Establish BGP connection
    @topotatofunc
    def bgp_converge(self, _, r1, r2):
        expected = {
            str(r1.ifaces[0].ip4[0].ip): {
                "bgpState": "Established",
                "addressFamilyInfo": {"ipv4Unicast": {"acceptedPrefixCounter": 1}},
            }
        }
        yield from AssertVtysh.make(
            r2,
            "bgpd",
            f"show ip bgp neighbor {r1.ifaces[0].ip4[0].ip} json",
            maxwait=6.0,
            compare=expected,
        )

    @topotatofunc
    def bgp_default_route_has_metric(self, _, r2):

        expected = {
            "paths": [
                {
                    "aspath": {"string": "65000 65000 65000 65000"},
                    "metric": 123,
                    "community": None,
                }
            ]
        }
        yield from AssertVtysh.make(
            r2, "bgpd", f"show ip bgp 0.0.0.0/0 json", maxwait=5.0, compare=expected
        )
