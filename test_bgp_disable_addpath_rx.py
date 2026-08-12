# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2022 Nathan Mangar

"""
Test if AddPath RX direction is not negotiated via AddPath capability.
"""

__topotests_file__ = "bgp_disable_addpath_rx/test_disable_addpath_rx.py"
__topotests_gitrev__ = "e82b531df94b9fd7bc456df8a1b7c58f2770eff9"

# pylint: disable=invalid-name, missing-class-docstring, missing-function-docstring, line-too-long, consider-using-f-string, wildcard-import, unused-wildcard-import, f-string-without-interpolation, too-few-public-methods

from topotato.v1 import *


@topology_fixture()
def topology(topo):
    """
    [ r1 ]
      |
    { s1 }  [ r3 ]
      |       |
    [ r2 ]--{ s2 }
              |
            [ r4 ]
    """

    topo.router("r3").lo_ip4.append("172.16.16.254/32")
    topo.router("r4").lo_ip4.append("172.16.16.254/32")
    topo.router("r1").iface_to("s1").ip4.append("192.168.1.1/24")
    topo.router("r2").iface_to("s1").ip4.append("192.168.1.2/24")
    topo.router("r2").iface_to("s2").ip4.append("192.168.2.2/24")
    topo.router("r3").iface_to("s2").ip4.append("192.168.2.3/24")
    topo.router("r4").iface_to("s2").ip4.append("192.168.2.4/24")


class FRRConfR1(RouterFRR):
    zebra = ""

    bgpd = """
    #% extends "boilerplate.conf"
    #% block main
    router bgp 65001
     timers bgp 3 10
     no bgp ebgp-requires-policy
     neighbor {{ routers.r2.iface_to('s1').ip4[0].ip }} remote-as external
     neighbor {{ routers.r2.iface_to('s1').ip4[0].ip }} timers connect 5
     address-family ipv4 unicast
      neighbor {{ routers.r2.iface_to('s1').ip4[0].ip }} disable-addpath-rx
    !
    #% endblock
    """


class FRRConfR2(RouterFRR):
    zebra = ""

    bgpd = """
    #% extends "boilerplate.conf"
    #% block main
    router bgp 65002
     timers bgp 3 10
     no bgp ebgp-requires-policy
     neighbor {{ routers.r1.iface_to('s1').ip4[0].ip }} remote-as external
     neighbor {{ routers.r1.iface_to('s1').ip4[0].ip }} timers connect 5
     neighbor {{ routers.r3.iface_to('s2').ip4[0].ip }} remote-as external
     neighbor {{ routers.r3.iface_to('s2').ip4[0].ip }} timers connect 5
     neighbor {{ routers.r4.iface_to('s2').ip4[0].ip }} remote-as external
     neighbor {{ routers.r4.iface_to('s2').ip4[0].ip }} timers connect 5
     address-family ipv4 unicast
      neighbor {{ routers.r1.iface_to('s1').ip4[0].ip }} addpath-tx-all-paths
    !
    #% endblock
    """


class FRRConfR3(RouterFRR):
    zebra = ""

    bgpd = """
    #% extends "boilerplate.conf"
    #% block main
    router bgp 65003
     timers bgp 3 10
     no bgp ebgp-requires-policy
     neighbor {{ routers.r2.iface_to('s2').ip4[0].ip }} remote-as external
     neighbor {{ routers.r2.iface_to('s2').ip4[0].ip }} timers connect 5
     address-family ipv4 unicast
      redistribute connected
    !
    #% endblock
    """


class FRRConfR4(RouterFRR):
    zebra = ""

    bgpd = """
    #% extends "boilerplate.conf"
    #% block main
    router bgp 65004
     timers bgp 3 10
     no bgp ebgp-requires-policy
     neighbor {{ routers.r2.iface_to('s2').ip4[0].ip }} remote-as external
     neighbor {{ routers.r2.iface_to('s2').ip4[0].ip }} timers connect 5
     address-family ipv4 unicast
      redistribute connected
    !
    #% endblock
    """


class Setup(TopotatoNetwork, topo=topology):
    r1: FRRConfR1
    r2: FRRConfR2
    r3: FRRConfR3
    r4: FRRConfR4


class BGPDisableAddpathRx(TestBase, AutoFixture, setup=Setup):
    @topotatofunc
    def check_bgp_advertised_routes(self, _, r1, r2):
        expected = {
            "advertisedRoutes": {
                "172.16.16.254/32": {
                    "addrPrefix": "172.16.16.254",
                    "prefixLen": 32,
                },
                "192.168.2.0/24": {
                    "addrPrefix": "192.168.2.0",
                    "prefixLen": 24,
                },
            },
            "totalPrefixCounter": 2,
        }
        yield from AssertVtysh.make(
            r2,
            "bgpd",
            f"show bgp ipv4 unicast neighbor {r1.iface_to('s1').ip4[0].ip} advertised-routes json",
            maxwait=5.0,
            compare=expected,
        )

    @topotatofunc
    def check_bgp_disabled_addpath_rx(self, _, r1, r2):
        expected = {
            str(r2.iface_to("s1").ip4[0].ip): {
                "bgpState": "Established",
                "neighborCapabilities": {
                    "addPath": {
                        "ipv4Unicast": {"txReceived": True, "rxReceived": True}
                    },
                },
                "addressFamilyInfo": {"ipv4Unicast": {"acceptedPrefixCounter": 2}},
            }
        }
        yield from AssertVtysh.make(
            r1,
            "bgpd",
            f"show bgp neighbor {r2.iface_to('s1').ip4[0].ip} json",
            maxwait=2.0,
            compare=expected,
        )
