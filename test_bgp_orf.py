#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2023 Nathan Mangar

"""
Test if BGP ORF filtering is working correctly when modifying prefix-list.

Initially advertise "ini_permit" from R1 to R2. Then add "ini_deny", check
ORF updated, remove "ini_permit", check ORF updated.
"""

__topotests_replaces__ = {
    "bgp_orf/": "acddc0ed3ce0833490b7ef38ed000d54388ebea4",
}

# pylint: disable=wildcard-import, unused-wildcard-import, trailing-whitespace

from topotato.v1 import *


@topology_fixture()
def topology(topo):
    """
    [ r1 ]--{ ini_permit }
    [    ]
    [    ]--{ ini_deny }
      |
    [ r2 ]
    """


class Configs(FRRConfigs):
    zebra = """
    #% extends "boilerplate.conf"
    ## nothing needed
    """

    bgpd = """
    #% block main
    #%   if router.name == 'r1'
    router bgp 65001
     no bgp ebgp-requires-policy
     neighbor {{ router.iface_to('r2').other.ip4[0].ip }} remote-as external
     address-family ipv4 unicast
      redistribute connected
      neighbor {{ router.iface_to('r2').other.ip4[0].ip }} capability orf prefix-list both
    !
    #%   elif router.name == 'r2'
    router bgp 65002
     no bgp ebgp-requires-policy
     neighbor {{ router.iface_to('r1').other.ip4[0].ip }} remote-as external
     address-family ipv4 unicast
      neighbor {{ router.iface_to('r1').other.ip4[0].ip }} capability orf prefix-list both
      neighbor {{ router.iface_to('r1').other.ip4[0].ip }} prefix-list r1 in
    !
    ip prefix-list r1 seq 5 permit {{ topo.lans["ini_permit"].ip4[0] }}
    #%   endif
    #% endblock
    """


class TestBGPORF(TestBase, AutoFixture, topo=topology, configs=Configs):
    @topotatofunc
    def bgp_converge(self, topo, r1, r2):
        """
        Wait for initial BGP convergence

        - ``ini_permit`` LAN should be seen on r2
        - ``ini_deny`` LAN should NOT be seen on r2
        """
        expected = {
            "advertisedRoutes": {
                str(topo.lans["ini_permit"].ip4[0]): JSONCompareIgnoreContent(),
                str(topo.lans["ini_deny"].ip4[0]): None,
            }
        }
        yield from AssertVtysh.make(
            r1,
            "bgpd",
            f"show bgp ipv4 unicast neighbor {r2.iface_to('r1').ip4[0].ip} advertised-routes json",
            maxwait=5.0,
            compare=expected,
        )

        expected = {
            "peers": {
                str(r1.iface_to("r2").ip4[0].ip): {
                    "pfxRcd": 1,
                    "pfxSnt": 1,
                    "state": "Established",
                    "peerState": "OK",
                }
            }
        }
        yield from AssertVtysh.make(
            r2,
            "bgpd",
            f"show bgp ipv4 unicast summary json",
            maxwait=5.0,
            compare=expected,
        )

    @topotatofunc
    def bgp_orf_change_permit(self, topo, r1, r2):
        """
        Change config on r2 to permit ``ini_deny`` prefix
        """
        yield from ReconfigureFRR.make(
            r2,
            "bgpd",
            f"ip prefix-list r1 seq 10 permit {topo.lans['ini_deny'].ip4[0]}",
        )

        expected = {
            "advertisedRoutes": {
                str(topo.lans["ini_permit"].ip4[0]): JSONCompareIgnoreContent(),
                str(topo.lans["ini_deny"].ip4[0]): JSONCompareIgnoreContent(),
            }
        }
        yield from AssertVtysh.make(
            r1,
            "bgpd",
            f"show bgp ipv4 unicast neighbor {r2.iface_to('r1').ip4[0].ip} advertised-routes json",
            maxwait=5.0,
            compare=expected,
        )

        expected = {
            "routes": {
                str(topo.lans["ini_permit"].ip4[0]): [{"valid": True}],
                str(topo.lans["ini_deny"].ip4[0]): [{"valid": True}],
            }
        }
        yield from AssertVtysh.make(
            r2,
            "bgpd",
            f"show bgp ipv4 unicast json",
            maxwait=5.0,
            compare=expected,
        )

    @topotatofunc
    def bgp_orf_change_deny(self, topo, r1, r2):
        """
        Change config on r2 to deny ``ini_permit`` prefix
        """
        yield from ReconfigureFRR.make(r2, "bgpd", "no ip prefix-list r1 seq 5")

        expected = {
            "advertisedRoutes": {
                str(topo.lans["ini_permit"].ip4[0]): None,
                str(topo.lans["ini_deny"].ip4[0]): JSONCompareIgnoreContent(),
            }
        }
        yield from AssertVtysh.make(
            r1,
            "bgpd",
            f"show bgp ipv4 unicast neighbor {r2.iface_to('r1').ip4[0].ip} advertised-routes json",
            maxwait=5.0,
            compare=expected,
        )

        expected = {
            "routes": {
                str(topo.lans["ini_permit"].ip4[0]): None,
                str(topo.lans["ini_deny"].ip4[0]): [{"valid": True}],
            }
        }
        yield from AssertVtysh.make(
            r2,
            "bgpd",
            f"show bgp ipv4 unicast json",
            maxwait=5.0,
            compare=expected,
        )
