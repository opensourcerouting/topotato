#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2018-2022  David Lamparter for NetDEF, Inc.
"""
Basic OSPF (v2 + v3) test.
"""

from topotato.v1 import *


@topology_fixture()
def topology(topo):
    """
    {lan1}  {lan2}
       |      |
    [ r1 ]  [ r2 ]
       |      |
    {  lan3      }
       |
    [ r3 ]--{lan4}
       |
    [ r4 ]--{lan6}
    """


class Configs(FRRConfigs):
    zebra = """
    #% extends "boilerplate.conf"
    """

    ospfd = """
    #% extends "boilerplate.conf"
    #% block main
    debug ospf event
    !
    #%   for iface in router.ifaces
    interface {{ iface.ifname }}
     ip ospf hello-interval 1
     ip ospf dead-interval 2
     ip ospf retransmit-interval 3
    #%   endfor
    !
    router ospf
     ospf router-id {{ router.lo_ip4[0].ip }}
     timers throttle lsa all 500
     timers throttle spf 0 50 500
     redistribute connected
    #%   if router.name == 'r3'
     network {{ router.iface_to('lan3').ip4[0].network }} area 0
     network {{ router.iface_to('lan4').ip4[0].network }} area 0
     network {{ router.iface_to('r4').ip4[0].network }} area 1
    #%   elif router.name == 'r4'
     network 10.0.0.0/9 area 1
    #%   else
     network 10.0.0.0/9 area 0
    #%   endif
    #% endblock
    """

    ospf6d = """
    #% extends "boilerplate.conf"
    #% block main
    #% if router.name == 'r1'
    debug ospf6 event
    debug ospf6 neighbor
    debug ospf6 spf process
    debug ospf6 spf database
    #% endif
    !
    #%   for iface in router.ifaces
    interface {{ iface.ifname }}
     ipv6 ospf6 hello-interval 1
     ipv6 ospf6 dead-interval 2
     ipv6 ospf6 retransmit-interval 3
    #%     if 'r4' in iface.ifname
     ipv6 ospf6 area 0.0.0.1
    #%     else
     ipv6 ospf6 area 0.0.0.0
    #%     endif
    #%   endfor
    !
    router ospf6
     ospf6 router-id {{ router.lo_ip4[0].ip }}
     timers throttle spf 0 50 500
     redistribute connected
    #% endblock
    """


class OSPFTopo1Test(TestBase, AutoFixture, topo=topology, configs=Configs):
    @topotatofunc
    def test_initial(self, topo, r1, r2, r3, r4):
        yield from AssertVtysh.make(r1, 'ospfd', 'show ip ospf route', r'''
            ============ OSPF network routing table ============
            N IA 10.7.0.0/16           [20] area: 0.0.0.0
                                       via 10.103.0.3, r1-lan3
            N    10.101.0.0/16         [10] area: 0.0.0.0
                                       directly attached to r1-lan1
            N    10.102.0.0/16         [20] area: 0.0.0.0
                                       via 10.103.0.2, r1-lan3
            N    10.103.0.0/16         [10] area: 0.0.0.0
                                       directly attached to r1-lan3
            N    10.104.0.0/16         [20] area: 0.0.0.0
                                       via 10.103.0.3, r1-lan3
            N IA 10.105.0.0/16         [30] area: 0.0.0.0
                                       via 10.103.0.3, r1-lan3

            ============ OSPF router routing table =============
            R    10.255.0.2            [10] area: 0.0.0.0, ASBR
                                       via 10.103.0.2, r1-lan3
            R    10.255.0.3            [10] area: 0.0.0.0, ABR, ASBR
                                       via 10.103.0.3, r1-lan3
            R    10.255.0.4         IA [20] area: 0.0.0.0, ASBR
                                       via 10.103.0.3, r1-lan3

            ============ OSPF external routing table ===========
            N E2 10.255.0.2/32         [10/20] tag: 0
                                       via 10.103.0.2, r1-lan3
            N E2 10.255.0.3/32         [10/20] tag: 0
                                       via 10.103.0.3, r1-lan3
            N E2 10.255.0.4/32         [20/20] tag: 0
                                       via 10.103.0.3, r1-lan3


            ''', maxwait = 30.0)

        yield from AssertVtysh.make(r2, 'ospfd', 'show ip ospf route', r'''
            ============ OSPF network routing table ============
            N IA 10.7.0.0/16           [20] area: 0.0.0.0
                                       via 10.103.0.3, r2-lan3
            N    10.101.0.0/16         [20] area: 0.0.0.0
                                       via 10.103.0.1, r2-lan3
            N    10.102.0.0/16         [10] area: 0.0.0.0
                                       directly attached to r2-lan2
            N    10.103.0.0/16         [10] area: 0.0.0.0
                                       directly attached to r2-lan3
            N    10.104.0.0/16         [20] area: 0.0.0.0
                                       via 10.103.0.3, r2-lan3
            N IA 10.105.0.0/16         [30] area: 0.0.0.0
                                       via 10.103.0.3, r2-lan3

            ============ OSPF router routing table =============
            R    10.255.0.1            [10] area: 0.0.0.0, ASBR
                                       via 10.103.0.1, r2-lan3
            R    10.255.0.3            [10] area: 0.0.0.0, ABR, ASBR
                                       via 10.103.0.3, r2-lan3
            R    10.255.0.4         IA [20] area: 0.0.0.0, ASBR
                                       via 10.103.0.3, r2-lan3

            ============ OSPF external routing table ===========
            N E2 10.255.0.1/32         [10/20] tag: 0
                                       via 10.103.0.1, r2-lan3
            N E2 10.255.0.3/32         [10/20] tag: 0
                                       via 10.103.0.3, r2-lan3
            N E2 10.255.0.4/32         [20/20] tag: 0
                                       via 10.103.0.3, r2-lan3


            ''', maxwait = 30.0)

        yield from AssertVtysh.make(r3, 'ospfd', 'show ip ospf route', r'''
            ============ OSPF network routing table ============
            N    10.7.0.0/16           [10] area: 0.0.0.1
                                       directly attached to r3-r4
            N    10.101.0.0/16         [20] area: 0.0.0.0
                                       via 10.103.0.1, r3-lan3
            N    10.102.0.0/16         [20] area: 0.0.0.0
                                       via 10.103.0.2, r3-lan3
            N    10.103.0.0/16         [10] area: 0.0.0.0
                                       directly attached to r3-lan3
            N    10.104.0.0/16         [10] area: 0.0.0.0
                                       directly attached to r3-lan4
            N    10.105.0.0/16         [20] area: 0.0.0.1
                                       via 10.7.4.3, r3-r4

            ============ OSPF router routing table =============
            R    10.255.0.1            [10] area: 0.0.0.0, ASBR
                                       via 10.103.0.1, r3-lan3
            R    10.255.0.2            [10] area: 0.0.0.0, ASBR
                                       via 10.103.0.2, r3-lan3
            R    10.255.0.4            [10] area: 0.0.0.1, ASBR
                                       via 10.7.4.3, r3-r4

            ============ OSPF external routing table ===========
            N E2 10.255.0.1/32         [10/20] tag: 0
                                       via 10.103.0.1, r3-lan3
            N E2 10.255.0.2/32         [10/20] tag: 0
                                       via 10.103.0.2, r3-lan3
            N E2 10.255.0.4/32         [10/20] tag: 0
                                       via 10.7.4.3, r3-r4


            ''', maxwait = 30.0)

        yield from AssertVtysh.make(r4, 'ospfd', 'show ip ospf route', r'''
            ============ OSPF network routing table ============
            N    10.7.0.0/16           [10] area: 0.0.0.1
                                       directly attached to r4-r3
            N IA 10.101.0.0/16         [30] area: 0.0.0.1
                                       via 10.7.3.4, r4-r3
            N IA 10.102.0.0/16         [30] area: 0.0.0.1
                                       via 10.7.3.4, r4-r3
            N IA 10.103.0.0/16         [20] area: 0.0.0.1
                                       via 10.7.3.4, r4-r3
            N IA 10.104.0.0/16         [20] area: 0.0.0.1
                                       via 10.7.3.4, r4-r3
            N    10.105.0.0/16         [10] area: 0.0.0.1
                                       directly attached to r4-lan6

            ============ OSPF router routing table =============
            R    10.255.0.1         IA [20] area: 0.0.0.1, ASBR
                                       via 10.7.3.4, r4-r3
            R    10.255.0.2         IA [20] area: 0.0.0.1, ASBR
                                       via 10.7.3.4, r4-r3
            R    10.255.0.3            [10] area: 0.0.0.1, ABR, ASBR
                                       via 10.7.3.4, r4-r3

            ============ OSPF external routing table ===========
            N E2 10.255.0.1/32         [20/20] tag: 0
                                       via 10.7.3.4, r4-r3
            N E2 10.255.0.2/32         [20/20] tag: 0
                                       via 10.7.3.4, r4-r3
            N E2 10.255.0.3/32         [10/20] tag: 0
                                       via 10.7.3.4, r4-r3


            ''', maxwait = 30.0)

        yield from AssertVtysh.make(r1, 'ospf6d', 'show ipv6 ospf6 route', r'''
            *N E2 fd00::2/128                    fe80::fc02:ff:febc:300    r1-lan3 00:$$\d+:\d+$$
            *N E2 fd00::3/128                    fe80::fc03:ff:febc:300    r1-lan3 00:$$\d+:\d+$$
            *N E2 fd00::4/128                    fe80::fc03:ff:febc:300    r1-lan3 00:$$\d+:\d+$$
            *N IA fdbc:1::/64                    ::                        r1-lan1 00:$$\d+:\d+$$
            *N IA fdbc:2::/64                    fe80::fc02:ff:febc:300    r1-lan3 00:$$\d+:\d+$$
             N E2 fdbc:2::/64                    fe80::fc02:ff:febc:300    r1-lan3 00:$$\d+:\d+$$
            *N IA fdbc:3::/64                    ::                        r1-lan3 00:$$\d+:\d+$$
             N E2 fdbc:3::/64                    fe80::fc02:ff:febc:300    r1-lan3 00:$$\d+:\d+$$
                                                 fe80::fc03:ff:febc:300    r1-lan3 
            *N IA fdbc:4::/64                    fe80::fc03:ff:febc:300    r1-lan3 00:$$\d+:\d+$$
             N E2 fdbc:4::/64                    fe80::fc03:ff:febc:300    r1-lan3 00:$$\d+:\d+$$
            *N IE fdbc:5::/64                    fe80::fc03:ff:febc:300    r1-lan3 00:$$\d+:\d+$$
             N E2 fdbc:5::/64                    fe80::fc03:ff:febc:300    r1-lan3 00:$$\d+:\d+$$
            ''', maxwait = 30.0)

        yield from AssertVtysh.make(r2, 'ospf6d', 'show ipv6 ospf6 route', r'''
            *N E2 fd00::1/128                    fe80::fc01:ff:febc:300    r2-lan3 00:$$\d+:\d+$$
            *N E2 fd00::3/128                    fe80::fc03:ff:febc:300    r2-lan3 00:$$\d+:\d+$$
            *N E2 fd00::4/128                    fe80::fc03:ff:febc:300    r2-lan3 00:$$\d+:\d+$$
            *N IA fdbc:1::/64                    fe80::fc01:ff:febc:300    r2-lan3 00:$$\d+:\d+$$
             N E2 fdbc:1::/64                    fe80::fc01:ff:febc:300    r2-lan3 00:$$\d+:\d+$$
            *N IA fdbc:2::/64                    ::                        r2-lan2 00:$$\d+:\d+$$
            *N IA fdbc:3::/64                    ::                        r2-lan3 00:$$\d+:\d+$$
             N E2 fdbc:3::/64                    fe80::fc01:ff:febc:300    r2-lan3 00:$$\d+:\d+$$
                                                 fe80::fc03:ff:febc:300    r2-lan3 
            *N IA fdbc:4::/64                    fe80::fc03:ff:febc:300    r2-lan3 00:$$\d+:\d+$$
             N E2 fdbc:4::/64                    fe80::fc03:ff:febc:300    r2-lan3 00:$$\d+:\d+$$
            *N IE fdbc:5::/64                    fe80::fc03:ff:febc:300    r2-lan3 00:$$\d+:\d+$$
             N E2 fdbc:5::/64                    fe80::fc03:ff:febc:300    r2-lan3 00:$$\d+:\d+$$
            ''', maxwait = 30.0)

        yield from AssertVtysh.make(r3, 'ospf6d', 'show ipv6 ospf6 route', r'''
            *N E2 fd00::1/128                    fe80::fc01:ff:febc:300    r3-lan3 00:$$\d+:\d+$$
            *N E2 fd00::2/128                    fe80::fc02:ff:febc:300    r3-lan3 00:$$\d+:\d+$$
            *N E2 fd00::4/128                    fe80::fc04:ff:fefe:300     r3-r4 00:$$\d+:\d+$$
            *N IA fdbc:1::/64                    fe80::fc01:ff:febc:300    r3-lan3 00:$$\d+:\d+$$
             N E2 fdbc:1::/64                    fe80::fc01:ff:febc:300    r3-lan3 00:$$\d+:\d+$$
            *N IA fdbc:2::/64                    fe80::fc02:ff:febc:300    r3-lan3 00:$$\d+:\d+$$
             N E2 fdbc:2::/64                    fe80::fc02:ff:febc:300    r3-lan3 00:$$\d+:\d+$$
            *N IA fdbc:3::/64                    ::                        r3-lan3 00:$$\d+:\d+$$
             N E2 fdbc:3::/64                    fe80::fc01:ff:febc:300    r3-lan3 00:$$\d+:\d+$$
                                                 fe80::fc02:ff:febc:300    r3-lan3 
            *N IA fdbc:4::/64                    ::                        r3-lan4 00:$$\d+:\d+$$
            *N IA fdbc:5::/64                    fe80::fc04:ff:fefe:300     r3-r4 00:$$\d+:\d+$$
             N E2 fdbc:5::/64                    fe80::fc04:ff:fefe:300     r3-r4 00:$$\d+:\d+$$
            ''', maxwait = 30.0)

        yield from AssertVtysh.make(r4, 'ospf6d', 'show ipv6 ospf6 route', r'''
            *N E2 fd00::1/128                    fe80::fc03:ff:fefe:400     r4-r3 00:$$\d+:\d+$$
            *N E2 fd00::2/128                    fe80::fc03:ff:fefe:400     r4-r3 00:$$\d+:\d+$$
            *N E2 fd00::3/128                    fe80::fc03:ff:fefe:400     r4-r3 00:$$\d+:\d+$$
            *N IE fdbc:1::/64                    fe80::fc03:ff:fefe:400     r4-r3 00:$$\d+:\d+$$
             N E2 fdbc:1::/64                    fe80::fc03:ff:fefe:400     r4-r3 00:$$\d+:\d+$$
            *N IE fdbc:2::/64                    fe80::fc03:ff:fefe:400     r4-r3 00:$$\d+:\d+$$
             N E2 fdbc:2::/64                    fe80::fc03:ff:fefe:400     r4-r3 00:$$\d+:\d+$$
            *N IE fdbc:3::/64                    fe80::fc03:ff:fefe:400     r4-r3 00:$$\d+:\d+$$
             N E2 fdbc:3::/64                    fe80::fc03:ff:fefe:400     r4-r3 00:$$\d+:\d+$$
             N E2 fdbc:3::/64                    fe80::fc03:ff:fefe:400     r4-r3 00:$$\d+:\d+$$
            *N IE fdbc:4::/64                    fe80::fc03:ff:fefe:400     r4-r3 00:$$\d+:\d+$$
             N E2 fdbc:4::/64                    fe80::fc03:ff:fefe:400     r4-r3 00:$$\d+:\d+$$
            *N IA fdbc:5::/64                    ::                        r4-lan6 00:$$\d+:\d+$$
            ''', maxwait = 30.0)

    @topotatofunc
    def test_initial_kernel(self, topo, r1, r2, r3, r4):
        """
        Check that OSPF state matches kernel state

        Short 2s timer for zebra to install things since OSPF state was
        already confirmed above.  Route nexthops are not checked, only
        existence.
        """
        for rtr in topo.routers.keys():
            yield from AssertKernelRoutesV4.make(rtr, {
                '10.7.0.0/16':   JSONCompareIgnoreContent(),
                '10.101.0.0/16': JSONCompareIgnoreContent(),
                '10.102.0.0/16': JSONCompareIgnoreContent(),
                '10.103.0.0/16': JSONCompareIgnoreContent(),
                '10.104.0.0/16': JSONCompareIgnoreContent(),
                '10.105.0.0/16': JSONCompareIgnoreContent(),
                '10.255.0.1/32': JSONCompareIgnoreContent(),
                '10.255.0.2/32': JSONCompareIgnoreContent(),
                '10.255.0.3/32': JSONCompareIgnoreContent(),
                '10.255.0.4/32': JSONCompareIgnoreContent(),
            }, local = True, maxwait=2.0)

        for rtr in topo.routers.keys():
            yield from AssertKernelRoutesV6.make(rtr, {
                'fd00::1/128': JSONCompareIgnoreContent(),
                'fd00::2/128': JSONCompareIgnoreContent(),
                'fd00::3/128': JSONCompareIgnoreContent(),
                'fd00::4/128': JSONCompareIgnoreContent(),
                'fdbc:1::/64': JSONCompareIgnoreContent(),
                'fdbc:2::/64': JSONCompareIgnoreContent(),
                'fdbc:3::/64': JSONCompareIgnoreContent(),
                'fdbc:4::/64': JSONCompareIgnoreContent(),
                'fdbc:5::/64': JSONCompareIgnoreContent(),
            }, local = True, maxwait=2.0)


    @topotatofunc
    def test_linkdown(self, topo, r1, r2, r3, r4):
        yield from ModifyLinkStatus.make(r3, r3.iface_to('lan3'), False)

        yield from AssertVtysh.make(r1, 'ospfd', 'show ip ospf route', r'''
            ============ OSPF network routing table ============
            N    10.101.0.0/16         [10] area: 0.0.0.0
                                       directly attached to r1-lan1
            N    10.102.0.0/16         [20] area: 0.0.0.0
                                       via 10.103.0.2, r1-lan3
            N    10.103.0.0/16         [10] area: 0.0.0.0
                                       directly attached to r1-lan3

            ============ OSPF router routing table =============
            R    10.255.0.2            [10] area: 0.0.0.0, ASBR
                                       via 10.103.0.2, r1-lan3

            ============ OSPF external routing table ===========
            N E2 10.255.0.2/32         [10/20] tag: 0
                                       via 10.103.0.2, r1-lan3


            ''', maxwait = 45.0)

        yield from AssertVtysh.make(r2, 'ospfd', 'show ip ospf route', r'''
            ============ OSPF network routing table ============
            N    10.101.0.0/16         [20] area: 0.0.0.0
                                       via 10.103.0.1, r2-lan3
            N    10.102.0.0/16         [10] area: 0.0.0.0
                                       directly attached to r2-lan2
            N    10.103.0.0/16         [10] area: 0.0.0.0
                                       directly attached to r2-lan3

            ============ OSPF router routing table =============
            R    10.255.0.1            [10] area: 0.0.0.0, ASBR
                                       via 10.103.0.1, r2-lan3

            ============ OSPF external routing table ===========
            N E2 10.255.0.1/32         [10/20] tag: 0
                                       via 10.103.0.1, r2-lan3


            ''', maxwait = 45.0)

        yield from AssertVtysh.make(r3, 'ospfd', 'show ip ospf route', r'''
            ============ OSPF network routing table ============
            N    10.7.0.0/16           [10] area: 0.0.0.1
                                       directly attached to r3-r4
            N    10.104.0.0/16         [10] area: 0.0.0.0
                                       directly attached to r3-lan4
            N    10.105.0.0/16         [20] area: 0.0.0.1
                                       via 10.7.4.3, r3-r4

            ============ OSPF router routing table =============
            R    10.255.0.4            [10] area: 0.0.0.1, ASBR
                                       via 10.7.4.3, r3-r4

            ============ OSPF external routing table ===========
            N E2 10.255.0.4/32         [10/20] tag: 0
                                       via 10.7.4.3, r3-r4


            ''', maxwait = 45.0)

        yield from AssertVtysh.make(r4, 'ospfd', 'show ip ospf route', r'''
            ============ OSPF network routing table ============
            N    10.7.0.0/16           [10] area: 0.0.0.1
                                       directly attached to r4-r3
            N IA 10.104.0.0/16         [20] area: 0.0.0.1
                                       via 10.7.3.4, r4-r3
            N    10.105.0.0/16         [10] area: 0.0.0.1
                                       directly attached to r4-lan6

            ============ OSPF router routing table =============
            R    10.255.0.3            [10] area: 0.0.0.1, ABR, ASBR
                                       via 10.7.3.4, r4-r3

            ============ OSPF external routing table ===========
            N E2 10.255.0.3/32         [10/20] tag: 0
                                       via 10.7.3.4, r4-r3


            ''', maxwait = 45.0)


        yield from AssertVtysh.make(r1, 'ospf6d', 'show ipv6 ospf6 route', r'''
            *N E2 fd00::2/128                    fe80::fc02:ff:febc:300    r1-lan3 00:$$\d+:\d+$$
            *N IA fdbc:1::/64                    ::                        r1-lan1 00:$$\d+:\d+$$
            *N IA fdbc:2::/64                    fe80::fc02:ff:febc:300    r1-lan3 00:$$\d+:\d+$$
             N E2 fdbc:2::/64                    fe80::fc02:ff:febc:300    r1-lan3 00:$$\d+:\d+$$
            *N IA fdbc:3::/64                    ::                        r1-lan3 00:$$\d+:\d+$$
             N E2 fdbc:3::/64                    fe80::fc02:ff:febc:300    r1-lan3 00:$$\d+:\d+$$
            ''', maxwait = 45.0)

        yield from AssertVtysh.make(r1, 'ospf6d', 'show ipv6 ospf6 database detail')

        yield from AssertVtysh.make(r2, 'ospf6d', 'show ipv6 ospf6 route', r'''
            *N E2 fd00::1/128                    fe80::fc01:ff:febc:300    r2-lan3 00:$$\d+:\d+$$
            *N IA fdbc:1::/64                    fe80::fc01:ff:febc:300    r2-lan3 00:$$\d+:\d+$$
             N E2 fdbc:1::/64                    fe80::fc01:ff:febc:300    r2-lan3 00:$$\d+:\d+$$
            *N IA fdbc:2::/64                    ::                        r2-lan2 00:$$\d+:\d+$$
            *N IA fdbc:3::/64                    ::                        r2-lan3 00:$$\d+:\d+$$
             N E2 fdbc:3::/64                    fe80::fc01:ff:febc:300    r2-lan3 00:$$\d+:\d+$$
            ''', maxwait = 45.0)

        yield from AssertVtysh.make(r2, 'ospf6d', 'show ipv6 ospf6 database detail')

        yield from AssertVtysh.make(r3, 'ospf6d', 'show ipv6 ospf6 route', r'''
            *N E2 fd00::4/128                    fe80::fc04:ff:fefe:300     r3-r4 00:$$\d+:\d+$$
            *N IA fdbc:4::/64                    ::                        r3-lan4 00:$$\d+:\d+$$
            *N IA fdbc:5::/64                    fe80::fc04:ff:fefe:300     r3-r4 00:$$\d+:\d+$$
             N E2 fdbc:5::/64                    fe80::fc04:ff:fefe:300     r3-r4 00:$$\d+:\d+$$
            ''', maxwait = 45.0)

        yield from AssertVtysh.make(r4, 'ospf6d', 'show ipv6 ospf6 route', r'''
            *N E2 fd00::3/128                    fe80::fc03:ff:fefe:400     r4-r3 00:$$\d+:\d+$$
            *N IE fdbc:4::/64                    fe80::fc03:ff:fefe:400     r4-r3 00:$$\d+:\d+$$
             N E2 fdbc:4::/64                    fe80::fc03:ff:fefe:400     r4-r3 00:$$\d+:\d+$$
            *N IA fdbc:5::/64                    ::                        r4-lan6 00:$$\d+:\d+$$
            ''', maxwait = 45.0)

    @topotatofunc
    def test_linkdown_kernel(self, topo, r1, r2, r3, r4):
        """
        Check that OSPF state matches kernel state again

        Short 2s timer for zebra to install things since OSPF state was
        already confirmed above.  Route nexthops are not checked, only
        (non-)existence.
        """
        for rtr in [r1, r2]:
            yield from AssertKernelRoutesV4.make(rtr.name, {
                '10.101.0.0/16': JSONCompareIgnoreContent(),
                '10.102.0.0/16': JSONCompareIgnoreContent(),
                '10.103.0.0/16': JSONCompareIgnoreContent(),
                '10.255.0.1/32': JSONCompareIgnoreContent(),
                '10.255.0.2/32': JSONCompareIgnoreContent(),
                '10.7.0.0/16':   None,
                '10.104.0.0/16': None,
                '10.105.0.0/16': None,
                '10.255.0.3/32': None,
                '10.255.0.4/32': None,
            }, local = True, maxwait=2.0)

        for rtr in [r3, r4]:
            yield from AssertKernelRoutesV4.make(rtr.name, {
                '10.7.0.0/16':   JSONCompareIgnoreContent(),
            #    '10.103.0.0/16': JSONCompareIgnoreContent(), - split LAN
                '10.104.0.0/16': JSONCompareIgnoreContent(),
                '10.105.0.0/16': JSONCompareIgnoreContent(),
                '10.255.0.3/32': JSONCompareIgnoreContent(),
                '10.255.0.4/32': JSONCompareIgnoreContent(),
                '10.101.0.0/16': None,
                '10.102.0.0/16': None,
                '10.255.0.1/32': None,
                '10.255.0.2/32': None,
            }, local = True, maxwait=2.0)

        for rtr in [r1, r2]:
            yield from AssertKernelRoutesV6.make(rtr.name, {
                'fd00::1/128': JSONCompareIgnoreContent(),
                'fd00::2/128': JSONCompareIgnoreContent(),
                'fdbc:1::/64': JSONCompareIgnoreContent(),
                'fdbc:2::/64': JSONCompareIgnoreContent(),
                'fdbc:3::/64': JSONCompareIgnoreContent(),
                'fd00::3/128': None,
                'fd00::4/128': None,
                'fdbc:4::/64': None,
                'fdbc:5::/64': None,
            }, local = True, maxwait=2.0)

        for rtr in [r3, r4]:
            yield from AssertKernelRoutesV6.make(rtr.name, {
                'fd00::3/128': JSONCompareIgnoreContent(),
                'fd00::4/128': JSONCompareIgnoreContent(),
            #    'fdbc:3::/64': JSONCompareIgnoreContent(), - split LAN
                'fdbc:4::/64': JSONCompareIgnoreContent(),
                'fdbc:5::/64': JSONCompareIgnoreContent(),
                'fd00::1/128': None,
                'fd00::2/128': None,
                'fdbc:1::/64': None,
                'fdbc:2::/64': None,
            }, local = True, maxwait=2.0)
