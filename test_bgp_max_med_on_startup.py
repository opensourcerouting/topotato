# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2023 Nathan Mangar

"""
Test whether `bgp max-med on-startup (5-86400) [(0-4294967295)]` is working
correctly.
"""

__topotests_file__ = "bgp_max_med_on_startup/test_bgp_max_med_on_startup.py"
__topotests_gitrev__ = "acddc0ed3ce0833490b7ef38ed000d54388ebea4"

# pylint: disable=invalid-name, missing-class-docstring, missing-function-docstring, line-too-long, consider-using-f-string, wildcard-import, unused-wildcard-import, f-string-without-interpolation, too-few-public-methods, unused-argument

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
    router bgp 65001
     bgp max-med on-startup 5 777
     no bgp ebgp-requires-policy
     neighbor {{ routers.r2.iface_to('s1').ip4[0].ip }} remote-as 65002
     neighbor {{ routers.r2.iface_to('s1').ip4[0].ip }} timers 3 10
     address-family ipv4 unicast
      redistribute connected
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
     neighbor {{ routers.r1.iface_to('s1').ip4[0].ip }} remote-as 65001
     neighbor {{ routers.r1.iface_to('s1').ip4[0].ip }} timers 3 10
    !
    #% endblock
    """


class Setup(TopotatoNetwork, topo=topology):
    r1: FRRConfR1
    r2: FRRConfR2


class BGPMaxMedOnStartup(TestBase, AutoFixture, setup=Setup):
    @topotatofunc
    def bgp_converge(self, _, r1, r2):
        expected = {str(r1.iface_to("s1").ip4[0].ip): {"bgpState": "Established"}}
        yield from AssertVtysh.make(
            r2,
            "bgpd",
            f"show ip bgp neighbor {r1.iface_to('s1').ip4[0].ip} json",
            maxwait=5.0,
            compare=expected,
        )

    @topotatofunc
    def bgp_has_routes(self, _, r1, r2):
        expected = {"routes": {str(r1.lo_ip4[0]): [{"metric": 777}]}}
        yield from AssertVtysh.make(
            r2,
            "bgpd",
            f"show ip bgp neighbor {r1.iface_to('s1').ip4[0].ip} routes json",
            maxwait=2.0,
            compare=expected,
        )
