# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2022-2023  David Lamparter, Nathan Mangar
"""
Test RIP ECMP support, including multipath limit.
"""

__topotests_replaces__ = {
    "rip_allow_ecmp/": "66e0f6c456cb2380f932c8f0dfef8897218359d7",
}

# pylint: disable=invalid-name, missing-class-docstring, missing-function-docstring, line-too-long, consider-using-f-string, wildcard-import, unused-wildcard-import, f-string-without-interpolation

from topotato.v1 import *


@topology_fixture()
def topology(topo):
    """
    [ r1 ]
      |
    { s1 }--[ r2 ]--{ s2 }
    {    }          {    }
    {    }--[ r3 ]--{    }
    {    }          {    }
    {    }--[ r4 ]--{    }
    {    }          {    }
    {    }--[ r5 ]--{    }
    """


class Configs(FRRConfigs):
    zebra = """
    #% extends "boilerplate.conf"
    ## nothing needed
    """

    ripd_rtrs = ["r1", "r2", "r3", "r4", "r5"]
    ripd = """
    #% extends "boilerplate.conf"
    #% block main
    router rip
     timers basic 5 15 10
    #%   if router.name == 'r1'
     allow-ecmp
    #%   endif
    #%   for iface in router.ifaces
     network {{ iface.ip4[0].network }}
    #%   endfor
    #% endblock
    """


class RIPAllowECMP(TestBase, AutoFixture, topo=topology, configs=Configs):
    def ecmp_nexthops(self, *routers):
        """
        Helper function that returns the list of nexthops for yang + zebra
        """

        yang = [
            JSONCompareListKeyedDict("from"),
        ]
        ip = [
            JSONCompareListKeyedDict("ip"),
        ]
        for rtr in routers:
            yang.append(
                {
                    "nh-type": "ip4",
                    "protocol": "rip",
                    "rip-type": "normal",
                    "gateway": str(rtr.iface_to("s1").ip4[0].ip),
                    "from": str(rtr.iface_to("s1").ip4[0].ip),
                    "tag": 0,
                }
            )
            ip.append(
                {
                    "ip": str(rtr.iface_to("s1").ip4[0].ip),
                    "active": True,
                }
            )
        return yang, ip

    def check_ecmp(self, topo, r1, *routers):
        """
        Put together test items, expected active routers is parametrized in
        *routers input.
        """

        test_net = str(topo.lans["s2"].ip4[0])
        nhs_yang, nhs_ip = self.ecmp_nexthops(*routers)

        expected = {
            "frr-ripd:ripd": {
                "instance": [
                    JSONCompareListKeyedDict("vrf"),
                    {
                        "vrf": "default",
                        "state": {
                            "routes": {
                                "route": [
                                    {
                                        "prefix": test_net,
                                        "nexthops": {
                                            "nexthop": nhs_yang,
                                        },
                                        "metric": 2,
                                    },
                                ],
                            },
                        },
                    },
                ],
            },
        }
        xpath = (
            "/frr-ripd:ripd/instance[vrf='default']"
            f"/state/routes/route[prefix='{test_net}']"
        )
        yield from AssertVtysh.make(
            r1,
            "vtysh",
            f"show yang operational-data {xpath} ripd",
            maxwait=7.5,
            compare=expected,
        )

        expected = {
            test_net: [
                {
                    "nexthops": nhs_ip,
                }
            ]
        }
        yield from AssertVtysh.make(
            r1,
            "zebra",
            f"show ip route json",
            maxwait=7.5,
            compare=expected,
        )

    @topotatofunc
    def test_full_ecmp(self, topo, r1, r2, r3, r4, r5):
        """
        Check that all 4 ECMP paths are active
        """

        yield from self.check_ecmp(topo, r1, r2, r3, r4, r5)

    @topotatofunc
    def test_limited_ecmp(self, topo, r1, r2, r3, r4, r5):
        """
        Restrict ECMP to 2 paths and check that lowest IPs win
        """

        yield from ReconfigureFRR.make(
            r1,
            "vtysh",
            "\n".join(
                [
                    "router rip",
                    "allow-ecmp 2",
                ]
            ),
        )

        routers = [r2, r3, r4, r5]
        routers.sort(key=lambda rtr: rtr.iface_to("s1").ip4[0])
        routers = routers[:2]

        yield from self.check_ecmp(topo, r1, *routers)
