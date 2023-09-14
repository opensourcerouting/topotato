# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2022 Nathan Mangar


"""
Test if RIP `allow-ecmp` command works correctly.
"""

__topotests_file__ = "rip_allow_ecmp/test_rip_allow_ecmp.py"
__topotests_gitrev__ = "4953ca977f3a5de8109ee6353ad07f816ca1774c"

# pylint: disable=invalid-name, missing-class-docstring, missing-function-docstring, line-too-long, consider-using-f-string, wildcard-import, unused-wildcard-import, f-string-without-interpolation

from topotato import *


@topology_fixture()
def topology(topo):
    """
    [ r1 ]
      |
    { s1 }--[ r3 ]
      |
    [ r2 ]
    """

    topo.router("r2").lo_ip4.append("10.10.10.1/32")
    topo.router("r3").lo_ip4.append("10.10.10.1/32")
    topo.router("r1").iface_to("s1").ip4.append("192.168.1.1/24")
    topo.router("r2").iface_to("s1").ip4.append("192.168.1.2/24")
    topo.router("r3").iface_to("s1").ip4.append("192.168.1.3/24")


class Configs(FRRConfigs):
    routers = ["r1", "r2", "r3"]

    zebra = """
    #% extends "boilerplate.conf"
    #% block main
    #%   for iface in router.ifaces
    interface {{ iface.ifname }}
     ip address {{ iface.ip4[0] }}
    !
    #%   endfor
    #% endblock
    """

    ripd_rtrs = ["r1", "r2", "r3"]
    ripd = """
    #% extends "boilerplate.conf"
    #% block main
    router rip
    ##
    #%   if router.name == 'r1'
     allow-ecmp
     network 192.168.1.0/24
     timers basic 5 15 10
    ##
    #%   elif router.name == 'r2'
     network 192.168.1.0/24
     network 10.10.10.1/32
     timers basic 5 15 10
    ##
    #%   elif router.name == 'r3'
     network 192.168.1.0/24
     network 10.10.10.1/32
     timers basic 5 15 10
    #%   endif
    #% endblock
    """


class RIPAllowECMP(TestBase, AutoFixture, topo=topology, configs=Configs):
    @topotatofunc
    def show_rip_routes(self, _, r1, r2):
        expected = {
            "route": [
                {
                    "prefix": "10.10.10.1/32",
                    "nexthops": {
                        "nexthop": [
                            {
                                "nh-type": "ip4",
                                "protocol": "rip",
                                "rip-type": "normal",
                                "gateway": "192.168.1.2",
                                "from": "192.168.1.2",
                                "tag": 0,
                            },
                            {
                                "nh-type": "ip4",
                                "protocol": "rip",
                                "rip-type": "normal",
                                "gateway": "192.168.1.3",
                                "from": "192.168.1.3",
                                "tag": 0,
                            },
                        ]
                    },
                    "metric": 2,
                },
            ]
        }
        yield from AssertVtysh.make(
            r1,
            "zebra",
            f"show ip route json",
            maxwait=5.0,
            compare=expected,
        )

    @topotatofunc
    def show_routes(self, _, r1, r2):
        expected = {
            "10.10.10.1/32": [
                {
                    "nexthops": [
                        {
                            "ip": "192.168.1.2",
                            "active": True,
                        },
                        {
                            "ip": "192.168.1.3",
                            "active": True,
                        },
                    ]
                }
            ]
        }
        yield from AssertVtysh.make(
            r1,
            "zebra",
            f"show ip route json",
            maxwait=5.0,
            compare=expected,
        )
