#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2022 Nathan Mangar

"""
Test if `set as-path replace` is working correctly for route-maps.
"""

__topotests_file__ = "bgp_set_aspath_replace/test_bgp_set_aspath_replace.py"
__topotests_gitrev__ = "77e3d82167b97a1ff4abe59d6e4f12086a61d9f9"

# pylint: disable=invalid-name, missing-class-docstring, missing-function-docstring, line-too-long, consider-using-f-string, wildcard-import, unused-wildcard-import, f-string-without-interpolation, too-few-public-methods

from topotato.v1 import *


@topology_fixture()
def topology(topo):
    """
    [ r1 ]
      |
    { s1 }--[ r3 ]
      |       |
    [ r2 ]--{ s2 }

    """

    topo.router("r3").lo_ip4.append("172.16.255.31/32")
    topo.router("r3").lo_ip4.append("172.16.255.32/32")


class FRRConfR1(RouterFRR):
    zebra = ""

    bgpd = """
    #% extends "boilerplate.conf"
    #% block main
    router bgp 65001
     no bgp ebgp-requires-policy
     neighbor {{ routers.r2.iface_to('s1').ip4[0].ip }} remote-as external
     neighbor {{ routers.r2.iface_to('s1').ip4[0].ip }} timers 3 10
     address-family ipv4 unicast
      neighbor {{ routers.r2.iface_to('s1').ip4[0].ip }} route-map r2 in
    !
    ip prefix-list p1 seq 5 permit {{ routers.r3.lo_ip4[0] }}
    !
    route-map r2 permit 10
     match ip address prefix-list p1
     set as-path replace 65003
    route-map r2 permit 20
     set as-path replace any
    !
    #% endblock
    """


class FRRConfR2(RouterFRR):
    zebra = ""

    bgpd = """
    #% extends "boilerplate.conf"
    #% block main
    router bgp 65002
     no bgp ebgp-requires-policy
     neighbor {{ routers.r1.iface_to('s1').ip4[0].ip }} remote-as external
     neighbor {{ routers.r1.iface_to('s1').ip4[0].ip }} timers 3 10
     neighbor {{ routers.r3.iface_to('s2').ip4[0].ip }} remote-as external
     neighbor {{ routers.r3.iface_to('s2').ip4[0].ip }} timers 3 10
    !
    #% endblock
    """


class FRRConfR3(RouterFRR):
    zebra = ""

    bgpd = """
    #% extends "boilerplate.conf"
    #% block main
    router bgp 65003
     no bgp ebgp-requires-policy
     neighbor {{ routers.r2.iface_to('s2').ip4[0].ip }} remote-as external
     neighbor {{ routers.r2.iface_to('s2').ip4[0].ip }} timers 3 10
     address-family ipv4 unicast
      redistribute connected
    !
    #% endblock
    """


class Setup(TopotatoNetwork, topo=topology):
    r1: FRRConfR1
    r2: FRRConfR2
    r3: FRRConfR3


class BGPSetAspathReplace(TestBase, AutoFixture, setup=Setup):
    @topotatofunc
    def bgp_converge(self, _, r1, r3):
        expected = {
            "routes": {
                str(r3.lo_ip4[0]): [{"path": "65002 65001"}],
                str(r3.lo_ip4[1]): [{"path": "65001 65001"}],
            }
        }
        yield from AssertVtysh.make(
            r1,
            "bgpd",
            f"show bgp ipv4 unicast json",
            maxwait=5.0,
            compare=expected,
        )
