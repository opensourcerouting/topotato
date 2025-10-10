#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2018-2022  David Lamparter for NetDEF, Inc.
"""
IPv6 Multicast Listener Discovery tests.
"""

from topotato.v1 import *
from topotato.multicast import *
from topotato.scapy import ScapySend
from scapy.layers.inet6 import (
    IPv6,
    ICMPv6MLReport2,
    ICMPv6MLDMultAddrRec,
    IPv6ExtHdrHopByHop,
    RouterAlert,
)
from scapy.layers.inet import (
    UDP,
)


@topology_fixture()
def topology(topo):
    """
    [     ]-----[ h1 ]
    [     ]
    [ dut ]-----[ h2 ]
    [     ]
    [     ]-----{ lan }-----[ src ]
    """


class FRRConfigured(RouterFRR):
    zebra = """
    #% extends "boilerplate.conf"
    #% block main
    debug zebra events
    debug zebra packet
    debug zebra rib detailed
    debug zebra nht detailed
    #% endblock
    """

    pim6d = """
    #% extends "boilerplate.conf"
    #% block main
    #%   if frr.has_defun("debug_mld_cmd")
    debug mld
    #%   endif
    #%   if router.name in ['dut']
    interface lo
     ipv6 pim
    !
    #%     for iface in router.ifaces
    interface {{ iface.ifname }}
     ipv6 pim
     ipv6 mld query-max-response-time 10
     ipv6 mld
    !
    #%     endfor
    ipv6 pim rp {{ router.lo_ip6[0].ip }}
    #%   endif
    #% endblock
    """

    def requirements(self):
        self.require_defun("interface_ipv6_mld_cmd")


class Setup(TopotatoNetwork, topo=topology):
    dut: FRRConfigured
    h1: Host
    h2: Host
    src: Host


def iter_mld_records(report):
    for record in report.records:
        while isinstance(record, ICMPv6MLDMultAddrRec):
            yield record
            record = record.payload

class MLDBasic(TestBase, AutoFixture, setup=Setup):
    @topotatofunc(include_startup=True)
    def prepare(self, topo, dut, h1, h2, src):
        self.receiver = MulticastReceiver(h1, h1.iface_to('dut'))

        # wait for query before continuing
        logchecks = yield from AssertLog.make(dut, 'pim6d', '[MLD default:dut-h1] MLD query', maxwait=3.0)
        @logchecks.skip_on_exception
        def need_debug_mld(testitem):
            testitem.instance.dut.require_defun("debug_mld_cmd")

        # get out of initial reporting (prevents timing issues later)
        def expect_pkt(ipv6: IPv6, report: ICMPv6MLReport2):
            for record in iter_mld_records(report):
                if record.rtype == 2: # IS_EX
                    return True
        yield from AssertPacket.make("h1_dut", maxwait=4.0, pkt=expect_pkt)

        yield from Delay.make(maxwait=5.0)

    @topotatofunc
    def test_asm(self, topo, dut, h1, h2, src):
        srcaddr = src.iface_to('lan').ip6[0].ip

        yield from self.receiver.join('ff05::1234')

        logchecks = yield from AssertLog.make(dut, 'pim6d', '[MLD default:dut-h1 (*,ff05::1234)] NOINFO => JOIN', maxwait=2.0)
        @logchecks.skip_on_exception
        def need_debug_mld(testitem):
            testitem.instance.dut.require_defun("debug_mld_cmd")

        yield from AssertVtysh.make(dut, "pim6d", "debug show mld interface %s" % (dut.iface_to('h1').ifname))

        ip = IPv6(hlim=255, src=srcaddr, dst="ff05::1234")
        udp = UDP(sport=9999, dport=9999)
        yield from ScapySend.make(
            src,
            "src-lan",
            pkt = ip/udp,
	    repeat = 2,
	    interval = 0.33,
        )

        def expect_pkt(ipv6: IPv6, udp: UDP):
            return ipv6.src == str(srcaddr) and ipv6.dst == 'ff05::1234' \
                and udp.dport == 9999

        yield from AssertPacket.make("h1_dut", maxwait=2.0, pkt=expect_pkt)

    @topotatofunc
    def test_ssm(self, topo, dut, h1, h2, src):
        """
        Join a (S,G) on MLD and try forwarding a packet on it.
        """
        srcaddr = src.iface_to('lan').ip6[0].ip

        yield from self.receiver.join('ff05::2345', srcaddr)

        logchecks = yield from AssertLog.make(dut, 'pim6d', '[MLD default:dut-h1 (%s,ff05::2345)] NOINFO => JOIN' % srcaddr, maxwait=3.0)
        @logchecks.skip_on_exception
        def need_debug_mld(testitem):
            testitem.instance.dut.require_defun("debug_mld_cmd")

        yield from AssertVtysh.make(dut, "pim6d", "debug show mld interface %s" % (dut.iface_to('h1').ifname))

        ip = IPv6(hlim=255, src=srcaddr, dst="ff05::2345")
        udp = UDP(sport=9999, dport=9999)
        yield from ScapySend.make(
            src,
            "src-lan",
            pkt = ip/udp,
        )

        def expect_pkt(ipv6: IPv6, udp: UDP):
            return ipv6.src == str(srcaddr) and ipv6.dst == 'ff05::2345' \
                and udp.dport == 9999

        yield from AssertPacket.make("h1_dut", maxwait=2.0, pkt=expect_pkt)

    @topotatofunc
    def test_invalid_group(self, topo, dut, h1, h2, src):
        """
        An unicast address is not a valid group address.
        """
        ip = IPv6(hlim=1, src=h1.iface_to("dut").ll6, dst="ff02::16")
        hbh = IPv6ExtHdrHopByHop(options = RouterAlert())
        mfrec0 = ICMPv6MLDMultAddrRec(dst="fe80::1234")

        yield from ScapySend.make(
            h1,
            "h1-dut",
            pkt = ip/hbh/ICMPv6MLReport2(records = [mfrec0]),
        )
        yield from AssertLog.make(dut, 'pim6d', f"[MLD default:dut-h1 {h1.iface_to('dut').ll6}] malformed MLDv2 report (invalid group fe80::1234)", maxwait=2.0)
