#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2023  David Lamparter for NetDEF, Inc.
"""
BGP + ECMP + RFC5549 IPv6 nexthops for IPv4 routes combination test.
"""

from topotato.v1 import *


@topology_fixture()
def topology(topo):
    """
              [    ]--{ u1 }--[    ]
    { lan1 }--[ r1 ]          [ r2 ]--{ lan2 }
              [    ]--{ u2 }--[    ]
    """
    topo.lans["u1"].ip4.noauto = True
    topo.lans["u2"].ip4.noauto = True


class Configs(FRRConfigs):
    zebra = """
    #% extends "boilerplate.conf"
    """

    bgpd = """
    #% extends "boilerplate.conf"
    #% block main
    debug bgp updates
    debug bgp zebra
    debug bgp nht
    debug bgp neighbor-events

    #%   if router.name == 'r1'
    router bgp 65000
    #%   else
    router bgp 65001
    #%   endif
     no bgp ebgp-requires-policy
     redistribute connected

    #%   for link in ["u1", "u2"]
     neighbor {{ router.flip("r1", "r2").iface_to(link).ll6 }} remote-as external
     neighbor {{ router.flip("r1", "r2").iface_to(link).ll6 }} interface {{ router.iface_to(link).ifname }}
     neighbor {{ router.flip("r1", "r2").iface_to(link).ll6 }} capability extended-nexthop
    #%   endfor
    #% endblock
    """


class BGP_ECMP_RFC5549(TestBase, AutoFixture, topo=topology, configs=Configs):
    """
    BGP ECMP + RFC5549 IPv4 routes w/ IPv6 nexthops combination test.

    This sets up 2 parallel BGP sessions over IPv6 link-local addresses with
    Extended Next-Hop Encoding (ENHE) capability, and announces an IPv4 prefix
    behind each router.  As there are no IPv4 addresses on the links between
    the routers, IPv6 nexthops are used.
    """

    @topotatofunc
    def test_init_session(self, topo, r1, r2):
        """
        Wait for BGP sessions.
        """

        for r_self in r1, r2:
            r_other = r_self.flip("r1", "r2")

            expected = {
                str(r_other.iface_to("u1").ll6): {
                    "bgpState": "Established",
                },
                str(r_other.iface_to("u2").ll6): {
                    "bgpState": "Established",
                },
            }
            yield from AssertVtysh.make(
                r_self,
                "bgpd",
                f"show ip bgp neighbor json",
                maxwait=10.0,
                compare=expected,
            )

    @topotatofunc
    def test_bgp_routes(self, topo, r1, r2):
        """
        Check for correct ECMP routes w/ IPv6 nexthops in BGP.
        """

        for r_self, other_lan in (r1, "lan2"), (r2, "lan1"):
            r_other = r_self.flip("r1", "r2")
            prefix = str(topo.lans[other_lan].ip4[0])

            expected = {
                "paths": [
                    {
                        "nexthops": [
                            {
                                "ip": str(r_other.iface_to("u1").ll6),
                            },
                        ],
                        "peer": {
                            "peerId": str(r_other.iface_to("u1").ll6),
                        },
                    },
                    {
                        "nexthops": [
                            {
                                "ip": str(r_other.iface_to("u2").ll6),
                            },
                        ],
                        "peer": {
                            "peerId": str(r_other.iface_to("u2").ll6),
                        },
                    },
                ],
            }
            yield from AssertVtysh.make(
                r_self,
                "bgpd",
                f"show ip bgp {prefix} json",
                maxwait=5.0,
                compare=expected,
            )

    @topotatofunc
    def test_kernel_ecmp(self, topo, r1, r2):
        """
        Verify ECMP routes have been correctly installed into the kernel.
        """
        for rtr, other_lan in (r1, "lan2"), (r2, "lan1"):
            yield from AssertKernelRoutesV4.make(
                rtr.name,
                {
                    str(topo.lans[other_lan].ip4[0]): [
                        {
                            "nexthops": [
                                JSONCompareListKeyedDict("dev"),
                                {
                                    "dev": rtr.iface_to("u1").ifname,
                                    "via": {
                                        "host": str(
                                            rtr.flip("r1", "r2").iface_to("u1").ll6
                                        ),
                                    },
                                },
                                {
                                    "dev": rtr.iface_to("u2").ifname,
                                    "via": {
                                        "host": str(
                                            rtr.flip("r1", "r2").iface_to("u2").ll6
                                        ),
                                    },
                                },
                            ],
                        },
                    ],
                },
                maxwait=2.0,
            )
