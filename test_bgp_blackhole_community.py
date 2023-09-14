# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2023 Nathan Mangar for NetDEF, Inc.

"""
Confirm that a BGP route tagged with BLACKHOLE community is not re-advertised
downstream outside local AS.
"""

__topotests_replaces__ = {
    "bgp_blackhole_community/": "acddc0ed3ce0833490b7ef38ed000d54388ebea4",
}
# NB: upstream test change in 4777c8376a118629e4916059a8b4f86aa519db6c is bogus
# (should be a separate test)

# pylint: disable=invalid-name, missing-class-docstring, missing-function-docstring, line-too-long, consider-using-f-string, wildcard-import, unused-wildcard-import, f-string-without-interpolation, too-few-public-methods, unused-argument, attribute-defined-outside-init
from topotato.v1 import *


not_blackhole_prefix = "172.16.255.255/32"
blackhole_prefix = "172.16.255.254/32"


@topology_fixture()
def topology(topo):
    """
    [ r1 ]--[ r2 ]--[ r3 ]
              |
            [ r4 ]
    """
    topo.router("r1").lo_ip4.append(not_blackhole_prefix)
    topo.router("r1").lo_ip4.append(blackhole_prefix)


class Configs(FRRConfigs):
    zebra = """
    #% extends "boilerplate.conf"
    ## nothing needed
    """

    bgpd = """
    #% block main
    #%   set blackhole_prefix = "172.16.255.254/32"
    #%   set asns = { "r1": 65001, "r2": 65002, "r3": 65003, "r4": 65002 }
    router bgp {{ asns[router.name] }}
      timers bgp 3 9
      no bgp ebgp-requires-policy
    #%   for iface in router.ifaces
      neighbor {{ iface.other.ip4[0].ip }} remote-as {{ asns[iface.other.endpoint.name] }}
      neighbor {{ iface.other.ip4[0].ip }} timers connect 1
    #%   endfor
    #%   if router.name == 'r1'
      address-family ipv4 unicast
        redistribute connected
        neighbor {{ router.iface_to('r2').other.ip4[0].ip }} route-map r2 out
      exit-address-family
    !
    ip prefix-list blackhole-prefix seq 10 permit {{ blackhole_prefix }}
    ip prefix-list blackhole-prefix seq 20 deny any
    !
    route-map r2 permit 10
      match ip address prefix-list blackhole-prefix
      set community blackhole no-export
    route-map r2 permit 20
    #%   endif
    #% endblock
    """


class BGPBlackholeCommunity(TestBase, AutoFixture, topo=topology, configs=Configs):
    @topotatofunc
    def bgp_converge(self, topo, r1, r2, r3, r4):
        """
        Ensure convergence:

        - check that blackhole prefix made it to r2
        - check that non-blackhole prefix is on r3 and r4
        """
        expected = {
            "advertisedRoutes": {
                blackhole_prefix: {},
                not_blackhole_prefix: {},
            },
        }
        yield from AssertVtysh.make(
            r1,
            "bgpd",
            f"show ip bgp neighbor {r2.iface_to('r1').ip4[0].ip} advertised-routes json",
            maxwait=4.0,
            compare=expected,
        )

        expected = {"paths": [{"community": {"list": ["blackhole", "noExport"]}}]}
        yield from AssertVtysh.make(
            r2,
            "bgpd",
            f"show ip bgp {blackhole_prefix} json",
            maxwait=7.0,
            compare=expected,
        )

        expected = {"prefix": not_blackhole_prefix}
        for other in r3, r4:
            yield from AssertVtysh.make(
                other,
                "bgpd",
                f"show ip bgp {not_blackhole_prefix} json",
                maxwait=7.0,
                compare=expected,
            )

    @topotatofunc
    def bgp_no_advertise_ebgp(self, r2):
        """
        The blackholed prefix should be absent from r2's eBGP session.

        NB: bgp_converge() above has ensured that non_blackhole_prefix is
        propagated correctly.  This is necessary since otherwise the blackholed
        prefix might be absent because routes haven't converged yet.
        """
        expected = {
            "advertisedRoutes": {
                blackhole_prefix: None,
            },
        }
        yield from AssertVtysh.make(
            r2,
            "bgpd",
            f"show ip bgp neighbor {r2.iface_to('r3').other.ip4[0].ip} advertised-routes json",
            compare=expected,
        )

    @topotatofunc
    def bgp_yes_advertise_ibgp(self, r2):
        """
        Blackhole communities should NOT affect iBGP advertisements, so check
        that the route is still carried on the iBGP session.
        """
        expected = {
            "advertisedRoutes": {
                blackhole_prefix: JSONCompareIgnoreContent(),
            },
        }
        yield from AssertVtysh.make(
            r2,
            "bgpd",
            f"show ip bgp neighbor {r2.iface_to('r4').other.ip4[0].ip} advertised-routes json",
            compare=expected,
        )
