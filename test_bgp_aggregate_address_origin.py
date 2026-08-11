#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2022 Nathan Mangar

"""
Test if works the following commands:
router bgp 65031
  address-family ipv4 unicast
    aggregate-address 172.16.255.0/24 origin igp
"""

__topotests_file__ = "bgp_aggregate_address_origin/test_bgp_aggregate-address_origin.py"
__topotests_gitrev__ = "4953ca977f3a5de8109ee6353ad07f816ca1774c"

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
    topo.router("r1").lo_ip4.append("172.16.255.254/32")


class FRRConfR1(RouterFRR):
    zebra = ""

    bgpd = """
    #% extends "boilerplate.conf"
    #% block main
    router bgp 65000
     no bgp ebgp-requires-policy
     neighbor {{ routers.r2.ifaces[0].ip4[0].ip }} remote-as 65001
     neighbor {{ routers.r2.ifaces[0].ip4[0].ip }} timers 3 10
     address-family ipv4 unicast
      redistribute connected
      aggregate-address 172.16.255.0/24 origin igp
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
     neighbor {{ routers.r1.ifaces[0].ip4[0].ip }} timers 3 10
    !
    #% endblock
    """


class Setup(TopotatoNetwork, topo=topology):
    r1: FRRConfR1
    r2: FRRConfR2


class BGPAggregateAddressOrigin(TestBase, AutoFixture, setup=Setup):
    @topotatofunc
    def bgp_converge(self, _, r1, r2):
        expected = {
            str(r1.ifaces[0].ip4[0].ip): {
                "bgpState": "Established",
                "addressFamilyInfo": {"ipv4Unicast": {"acceptedPrefixCounter": 3}},
            }
        }
        yield from AssertVtysh.make(
            r2,
            "bgpd",
            f"show ip bgp neighbor {r1.ifaces[0].ip4[0].ip} json",
            maxwait=5.0,
            compare=expected,
        )

    @topotatofunc
    def bgp_aggregate_address_has_metric(self, _, r2):
        expected = {"paths": [{"origin": "IGP"}]}
        yield from AssertVtysh.make(
            r2,
            "bgpd",
            f"show ip bgp 172.16.255.0/24 json",
            maxwait=3.0,
            compare=expected,
        )
