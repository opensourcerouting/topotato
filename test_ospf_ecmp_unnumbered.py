#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2023  David Lamparter for NetDEF, Inc.
"""
OSPF(v2) ECMP + unnumbered combination test.
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
    #% block main
    #%   for iface in router.ifaces
    #%     if not iface.other.endpoint.name.startswith("lan")
    interface {{ iface.ifname }}
     ! unnumbered configured as IPv4 PtP addressing ("LO_ADDR peer PEER_LO_ADDR/32")
     ip address {{ router.lo_ip4[0].ip }} peer {{ router.flip("r1", "r2").lo_ip4[0] }}
    #%     endif
    #%   endfor
    #% endblock
    """

    ospfd = """
    #% extends "boilerplate.conf"
    #% block main
    debug ospf lsa install
    !
    #%   for iface in router.ifaces
    interface {{ iface.ifname }}
     ip ospf network point-to-point
     ip ospf hello-interval 1
     ip ospf dead-interval 2
     ip ospf retransmit-interval 3
     ip ospf area 0.0.0.0
    #%   endfor
    !
    router ospf
     ospf router-id {{ router.lo_ip4[0].ip }}
     timers throttle lsa all 500
     timers throttle spf 0 50 500
     redistribute connected
    #% endblock
    """


class OSPF_Unnumbered_ECMP(TestBase, AutoFixture, topo=topology, configs=Configs):
    """
    OSPF(v2) ECMP + unnumbered combination test.

    Test that ECMP doesn't break in weird ways if nexthops don't have unique IPs.
    https://blog.ipspace.net/2023/08/unnumbered-ospf-arp.html#1903
    """

    @topotatofunc
    def test_init_neigh(self, topo, r1, r2):
        """
        Wait for OSPF adjacency to reach Full on both links.
        """
        for r_self in r1, r2:
            r_other = r_self.flip("r1", "r2")
            expect = {
                "neighbors": {
                    str(r_other.lo_ip4[0].ip): [
                        JSONCompareListKeyedDict("ifaceName"),
                        {
                            "nbrState": "Full/-",
                            "ifaceName": f"{ r_self.iface_to('u1').ifname }:{ r_self.lo_ip4[0].ip }",
                        },
                        {
                            "nbrState": "Full/-",
                            "ifaceName": f"{ r_self.iface_to('u2').ifname }:{ r_self.lo_ip4[0].ip }",
                        },
                    ],
                },
            }
            yield from AssertVtysh.make(
                r_self, "ospfd", "show ip ospf neighbor json", expect, maxwait=10.0
            )

    @topotatofunc
    def test_ecmp(self, topo, r1, r2):
        """
        Check OSPF actually produced an ECMP route using both links.
        """
        for rtr, other_lan in (r1, "lan2"), (r2, "lan1"):
            expect = {
                str(topo.lans[other_lan].ip4[0]): {
                    "nexthops": [
                        {
                            "via": rtr.iface_to("u1").ifname,
                        },
                        {
                            "via": rtr.iface_to("u2").ifname,
                        },
                    ],
                },
            }
            yield from AssertVtysh.make(
                rtr, "ospfd", "show ip ospf route json", expect, maxwait=10.0
            )

    @topotatofunc
    def test_kernel_ecmp(self, topo, r1, r2):
        """
        Check that OSPF passed off the route as ECMP to zebra and it was installed in the kernel.
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
                                },
                                {
                                    "dev": rtr.iface_to("u2").ifname,
                                },
                            ],
                        },
                    ],
                },
                maxwait=1.0,
            )
