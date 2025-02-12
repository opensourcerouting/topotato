# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2023 Nathan Mangar

"""
Test if routes are retained during BGP restarts.
"""

__topotests_replaces__ = {
	"bgp_gr_restart_retain_routes/": "6a62adabb3938b1f478d04500e2d918b43f6107d",
}

# pylint: disable=invalid-name, missing-class-docstring, missing-function-docstring, line-too-long, consider-using-f-string, wildcard-import, unused-wildcard-import, f-string-without-interpolation, too-few-public-methods, unused-argument

from topotato.v1 import *


@topology_fixture()
def topology(topo):
    """
    [ r1 ]
      |
    [ r2 ]
    """


class Configs(FRRConfigs):
    routers = ["r1", "r2"]

    zebra = """
    #% extends "boilerplate.conf"
    ## nothing needed
    """

    bgpd = """
    #% block main
    #%   if router.name == 'r1'
    router bgp 65001
     no bgp ebgp-requires-policy
     bgp graceful-restart
     bgp graceful-restart preserve-fw-state
     neighbor {{ routers.r2.iface_to('r1').ip4[0].ip }} remote-as external
     neighbor {{ routers.r2.iface_to('r1').ip4[0].ip }} timers 1 3
     neighbor {{ routers.r2.iface_to('r1').ip4[0].ip }} timers connect 1
     address-family ipv4
      redistribute connected
    !
    #%   elif router.name == 'r2'
    router bgp 65002
     no bgp ebgp-requires-policy
     bgp graceful-restart
     bgp graceful-restart preserve-fw-state
     neighbor {{ routers.r1.iface_to('r2').ip4[0].ip }} remote-as external
     neighbor {{ routers.r1.iface_to('r2').ip4[0].ip }} timers 1 3
     neighbor {{ routers.r1.iface_to('r2').ip4[0].ip }} timers connect 1
    !
    #%   endif
    #% endblock
    """


class BGPGrRestartRetainRoutes(TestBase, AutoFixture, topo=topology, configs=Configs):
    @topotatofunc
    def bgp_converge(self, r1, r2):
        expected = {
            str(r1.iface_to("r2").ip4[0].ip): {
                "bgpState": "Established",
                "addressFamilyInfo": {"ipv4Unicast": {"acceptedPrefixCounter": 2}},
            }
        }
        yield from AssertVtysh.make(
            r2,
            "bgpd",
            f"show bgp ipv4 neighbors {r1.iface_to('r2').ip4[0].ip} json",
            maxwait=5.0,
            compare=expected,
        )

        expected = {
            str(r1.lo_ip4[0]): [
                {
                    "gateway": str(r1.iface_to("r2").ip4[0].ip),
                },
            ],
        }
        yield from AssertKernelRoutesV4.make("r2", expected, maxwait=5.5)

    @topotatofunc
    def bgp_check_bgp_retained_routes(self, r1, r2):
        yield from DaemonStop.make(r1, "bgpd")

        expected = {"paths": [{"stale": True}]}
        yield from AssertVtysh.make(
            r2,
            "bgpd",
            f"show bgp ipv4 unicast {r1.lo_ip4[0]} json",
            maxwait=5.0,
            compare=expected,
        )

        expected = {
            str(r1.lo_ip4[0]): [
                {
                    "gateway": str(r1.iface_to("r2").ip4[0].ip),
                },
            ],
        }
        yield from AssertKernelRoutesV4.make("r2", expected, maxwait=5.5)

        # just for reference
        yield from AssertVtysh.make(r2, "zebra", "show ip route")
