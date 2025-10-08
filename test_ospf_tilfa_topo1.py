#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2018-2022  David Lamparter for NetDEF, Inc.
"""
OSPFv2 TI-LFA basic bringup test

Check that we have appropriate backup paths calculated by TI-LFA.  This test
does not simulate any actual "outage" where these paths would be used, it only
checks they are calculated correctly.
"""

from topotato.v1 import *


__topotests_replaces__ = {
    "ospf_tilfa_topo1/": "d0a0e7061c7bf41803905da1d49656fe91b8007e",
}


@topology_fixture()
def topology(topo):
    """
    [ r1 ]--{ lan12 }--[ r2 ]--{ lan23 }--[    ]
       |                                  [    ]
    { lan51 }                             [ r3 ]
       |                                  [    ]
    [ r5 ]--{ lan45 }--[ r4 ]--{ lan34 }--[    ]
    """


class FRRConfigured(RouterFRR):
    zebra = """
    #% extends "boilerplate.conf"
    """

    ospfd = """
    #% extends "boilerplate.conf"
    #% block main
    #% if router.name == "r1"
    debug ospf event
    debug ospf sr
    debug ospf ti-lfa
    #% endif
    !
    interface lo
     ip ospf passive
    !
    #% for iface in router.ifaces
    interface {{ iface.ifname }}
     ip ospf network point-to-point
     ip ospf hello-interval 1
     ip ospf dead-interval 2
     ip ospf retransmit-interval 3
    #% endfor
    !
    router ospf
     ospf router-id {{ router.lo_ip4[0].ip }}
     network {{ router.lo_ip4[0].ip }}/32 area 0.0.0.0
     network 10.0.0.0/9 area 0.0.0.0
     area 0.0.0.0 range 10.0.0.0/9
     area 0.0.0.0 range 10.255.0.0/24
     capability opaque
     mpls-te on
     mpls-te router-address {{ router.lo_ip4[0].ip }}
     router-info area ##- 0.0.0.0 - broken in original topotest
     segment-routing on
     segment-routing global-block 16000 23999
     segment-routing node-msd 8
     segment-routing prefix {{ router.lo_ip4[0].ip }}/32 index {{ router.name[1:] }}0
    #% endblock
    """


class Setup(TopotatoNetwork, topo=topology):
    r1: FRRConfigured
    r2: FRRConfigured
    r3: FRRConfigured
    r4: FRRConfigured
    r5: FRRConfigured


class OSPF_TILFA_Topo1(TestBase, AutoFixture, setup=Setup):
    # show ip route json - shorthand: connected prefix
    @staticmethod
    def _connected_entry(iface="lo", protos=None):
        ret = [
            JSONCompareListKeyedDict("protocol"),
        ]
        for proto in protos or ["connected", "ospf"]:
            ret.append(
                {
                    "protocol": proto,
                    "nexthops": [
                        {
                            "directlyConnected": True,
                            "interfaceName": iface,
                        },
                    ],
                }
            )
        return ret

    # show ip route json - shorthand: ospf nexthop + route
    @staticmethod
    def _routed_entry(r1, nhs):
        return [
            {
                "protocol": "ospf",
                "nexthops": [JSONCompareListKeyedDict("ip")]
                + [
                    {
                        "ip": str(nh.iface_to(lan).ip4[0].ip),
                        "interfaceName": str(r1.iface_to(lan).ifname),
                    }
                    for nh, lan in nhs
                ],
            }
        ]

    # show ip route json - shorthand: ospf nexthop + route + backup
    @staticmethod
    def _routed_entry_backup(r1, nhs, backups=None):
        ret = {
            "protocol": "ospf",
            "nexthops": [JSONCompareListKeyedDict("ip")],
            "backupNexthops": [JSONCompareListKeyedDict("ip")],
        }
        for i in nhs:
            nh, lan = i[0], i[1]
            ret["nexthops"].append(
                {
                    "ip": str(nh.iface_to(lan).ip4[0].ip),
                    "interfaceName": str(r1.iface_to(lan).ifname),
                }
            )
            if len(i) > 2:
                ret["nexthops"][-1]["labels"] = i[2]

        if backups:
            for rt, lan, labels in backups:
                ret["backupNexthops"].append(
                    {
                        "ip": str(rt.iface_to(lan).ip4[0].ip),
                        "labels": labels,
                    }
                )
        else:
            ret["backupNexthops"] = None

        return [ret]

    def _baseline(self, topo, r1, r2, r3, r4, r5):
        """
        Check initial routing table without TI-LFA enabled
        """
        expected = {
            str(r1.lo_ip4[0]): self._connected_entry(),
        }

        for rt, lan, nh in [
            (r2, "lan12", r2),
            (r3, "lan12", r2),
            (r4, "lan51", r5),
            (r5, "lan51", r5),
        ]:
            expected[str(rt.lo_ip4[0])] = self._routed_entry(r1, [(nh, lan)])

        for lan in ["lan12", "lan51"]:
            expected[str(topo.lans[lan].ip4[0])] = self._connected_entry(
                iface=r1.iface_to(lan).ifname
            )

        for lan, nhs in [
            ("lan23", [(r2, "lan12")]),
            ("lan34", [(r2, "lan12"), (r5, "lan51")]),
            ("lan45", [(r5, "lan51")]),
        ]:
            expected[str(topo.lans[lan].ip4[0])] = self._routed_entry(r1, nhs)

        yield from AssertVtysh.make(
            r1,
            "zebra",
            f"show ip route json",
            maxwait=10.0,
            compare=expected,
        )

    @topotatofunc
    def test_workaround_linkreset(self, topo, r1, r2, r3, r4, r5):
        """
        **WORKAROUND** - there's an ordering bug somewhere in the segment
        routing or TI-LFA code that makes things not come up correctly if
        the interfaces are already up when the config is loaded.  Therefore
        this test function flaps a link down and back up.  This needs to be
        fixed in FRR.
        """
        yield from ModifyLinkStatus.make(r1, r1.iface_to("lan12"), False)
        yield from ModifyLinkStatus.make(r1, r1.iface_to("lan51"), False)
        yield from ModifyLinkStatus.make(r2, r2.iface_to("lan12"), False)
        yield from ModifyLinkStatus.make(r5, r5.iface_to("lan51"), False)

        yield from Delay.make(maxwait=0.5)

        yield from ModifyLinkStatus.make(r1, r1.iface_to("lan12"), True)
        yield from ModifyLinkStatus.make(r1, r1.iface_to("lan51"), True)
        yield from ModifyLinkStatus.make(r2, r2.iface_to("lan12"), True)
        yield from ModifyLinkStatus.make(r5, r5.iface_to("lan51"), True)

    @topotatofunc
    def test_initial(self, topo, r1, r2, r3, r4, r5):
        """
        Wait for adjacencies & establish the baseline (no TI-LFA) routing table
        """
        yield from self._baseline(topo, r1, r2, r3, r4, r5)

    @topotatofunc
    def test_lfa_linkprot_on(self, topo, r1, r2, r3, r4, r5):
        """
        Turn on TI-LFA link protection and check we have MPLS backup paths
        """
        yield from ReconfigureFRR.make(
            r1,
            "vtysh",
            "router ospf\nfast-reroute ti-lfa",
        )

        expected = {
            str(r1.lo_ip4[0]): self._connected_entry(),
        }

        # routers
        # directly connected
        expected[str(r2.lo_ip4[0])] = self._routed_entry_backup(
            r1, nhs=[(r2, "lan12")], backups=[(r5, "lan51", [16040])]
        )
        expected[str(r5.lo_ip4[0])] = self._routed_entry_backup(
            r1, nhs=[(r5, "lan51")], backups=[(r2, "lan12", [16030])]
        )

        # indirect
        expected[str(r3.lo_ip4[0])] = self._routed_entry_backup(
            r1, nhs=[(r2, "lan12", [16030])], backups=[(r5, "lan51", [16040, 16030])]
        )
        expected[str(r4.lo_ip4[0])] = self._routed_entry_backup(
            r1, nhs=[(r5, "lan51", [16040])], backups=[(r2, "lan12", [16030, 16040])]
        )

        # LANs
        # directly connected
        for lan in ["lan12", "lan51"]:
            expected[str(topo.lans[lan].ip4[0])] = self._connected_entry(
                iface=r1.iface_to(lan).ifname
            )

        for lan, nhs, backups in [
            ("lan23", [(r2, "lan12")], [(r5, "lan51", [16040])]),
            ("lan45", [(r5, "lan51")], [(r2, "lan12", [16030])]),
            (
                "lan34",
                [(r2, "lan12"), (r5, "lan51")],
                [(r5, "lan51", [16040]), (r2, "lan12", [16030])],
            ),
        ]:
            expected[str(topo.lans[lan].ip4[0])] = self._routed_entry_backup(
                r1, nhs, backups
            )

        yield from AssertVtysh.make(
            r1,
            "zebra",
            f"show ip route json",
            maxwait=8.0,
            compare=expected,
        )

    @topotatofunc
    def test_lfa_linkprot_off(self, topo, r1, r2, r3, r4, r5):
        """
        Check we're back in initial routing state after turning off TI-LFA
        link protection.
        """
        yield from ReconfigureFRR.make(
            r1,
            "vtysh",
            "router ospf\nno fast-reroute ti-lfa",
        )

        yield from self._baseline(topo, r1, r2, r3, r4, r5)

    @topotatofunc
    def test_lfa_nodeprot_on(self, topo, r1, r2, r3, r4, r5):
        """
        Now try TI-LFA node protection...
        """
        yield from ReconfigureFRR.make(
            r1,
            "vtysh",
            "router ospf\nfast-reroute ti-lfa node-protection",
        )

        expected = {
            str(r1.lo_ip4[0]): self._connected_entry(),
        }

        # routers
        # directly connected
        expected[str(r2.lo_ip4[0])] = self._routed_entry_backup(r1, nhs=[(r2, "lan12")])
        expected[str(r5.lo_ip4[0])] = self._routed_entry_backup(r1, nhs=[(r5, "lan51")])

        # indirect
        expected[str(r3.lo_ip4[0])] = self._routed_entry_backup(
            r1, nhs=[(r2, "lan12", [16030])], backups=[(r5, "lan51", [16040])]
        )
        expected[str(r4.lo_ip4[0])] = self._routed_entry_backup(
            r1, nhs=[(r5, "lan51", [16040])], backups=[(r2, "lan12", [16030])]
        )

        # LANs
        # directly connected
        for lan in ["lan12", "lan51"]:
            expected[str(topo.lans[lan].ip4[0])] = self._connected_entry(
                iface=r1.iface_to(lan).ifname
            )

        for lan, nhs, backups in [
            ("lan23", [(r2, "lan12")], []),
            ("lan45", [(r5, "lan51")], []),
            (
                "lan34",
                [(r2, "lan12"), (r5, "lan51")],
                [(r5, "lan51", [16040]), (r2, "lan12", [16030])],
            ),
        ]:
            expected[str(topo.lans[lan].ip4[0])] = self._routed_entry_backup(
                r1, nhs, backups
            )

        yield from AssertVtysh.make(
            r1,
            "zebra",
            f"show ip route json",
            maxwait=8.0,
            compare=expected,
        )

    @topotatofunc
    def test_lfa_nodeprot_off(self, topo, r1, r2, r3, r4, r5):
        """
        And again, check we're back cleanly after turning off TI-LFA node
        protection.
        """
        yield from ReconfigureFRR.make(
            r1,
            "vtysh",
            "router ospf\nno fast-reroute ti-lfa node-protection",
        )

        yield from self._baseline(topo, r1, r2, r3, r4, r5)
