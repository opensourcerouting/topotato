#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2018-2021  David Lamparter for NetDEF, Inc.
"""
Linux implementation of topotato instances, based on nswrap
"""
# pylint: disable=duplicate-code

import json
import os
import sys
import shlex
import re
import time
import subprocess
import logging

try:
    import packaging.version
except ImportError:
    packaging = None  # type: ignore

from typing import Union, Dict, List, Any, Optional

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal  # type: ignore

import pytest

import scapy.arch  # type: ignore[import-untyped]

# this is here for 2 reasons (and needs to be before "import scapy.all":
# - topotato neither needs nor wants scapy to use any nameservers, the list
#   *should* be empty
# - scapy prints a confusing message if it can't read resolv.conf
#   ("Could not retrieve the OS's nameserver !")
scapy.arch.read_nameservers = lambda: []

# pylint: disable=wrong-import-position
import scapy.all  # type: ignore[import-untyped]

from .scapyext.netnssock import NetnsL2Socket
from .utils import exec_find, EnvcheckResult
from .nswrap import LinuxNamespace
from .toponom import LAN, LinkIface, Network
from . import topobase


_logger = logging.getLogger(__name__)


def ifname(host: str, iface: str) -> str:
    """
    make short interface names

    normally we use host_iface, but if iface starts with "host-" then just
    use straight iface.  we're on a 15 char limit...
    """
    if iface.startswith(host + "-"):
        return iface
    return "%s_%s" % (host, iface)


def proc_write(path: str, value: str):
    return [
        "test ! -f %s || echo %s > %s" % (path, value, path),
    ]


class NetworkInstance(topobase.NetworkInstance):
    """
    represent a test setup with all its routers & switches
    """

    # TODO: replace this hack with something better (it only works because
    # _exec actually references the same dict from LinuxNamespace)
    # pylint: disable=protected-access
    _exec = LinuxNamespace._exec
    _exec.update(
        {
            "ip": None,
        }
    )

    _bridge_settings = [
        "forward_delay",
        "0",
        "mcast_snooping",
        "0",
        "nf_call_iptables",
        "0",
        "nf_call_ip6tables",
        "0",
        "nf_call_arptables",
        "0",
    ]

    # pylint: disable=unused-argument
    @classmethod
    @pytest.hookimpl()
    def pytest_topotato_envcheck(cls, session, result: EnvcheckResult):
        for name, cur in cls._exec.items():
            if cur is None:
                cls._exec[name] = cur = exec_find(name)
            if cur is None:
                result.error("%s is required to run on Linux systems", name)

        ip_ver = subprocess.check_output([cls._exec("ip"), "-V"]).decode("UTF-8")
        ip_ver_m = re.search(r"iproute2-((?:ss)?[\d\.]+)", ip_ver)
        if ip_ver_m and ip_ver_m.group(1).startswith("ss"):
            ver = ip_ver_m.group(1)
            ssdate = int(ver[2:])
            if ssdate < 191125:
                result.error(
                    "iproute2 version %s is too old, need >= ss191125 / 5.4" % (ver,)
                )
        elif ip_ver_m and packaging:
            ver = packaging.version.parse(ip_ver_m.group(1))
            minver = packaging.version.parse("5.4")
            if ver < minver:
                result.error(
                    "iproute2 version %s is too old, need >= %s" % (ver, minver)
                )
        else:
            _logger.warning(
                "cannot parse iproute2 version %r from %r",
                ip_ver,
                cls._exec("ip"),
            )

    class BaseNS(topobase.CallableEnvMixin, LinuxNamespace, topobase.BaseNS):
        """
        a netns with some extra functions for topotato
        """

        instance: "NetworkInstance"
        tempdir: str

        # broken json output from "ip -j route list"
        iproute_json_re = re.compile(
            rb'(?<!:)"(anycast|broadcast|unicast|local|multicast|throw|unreachable|prohibit|blackhole|nat)"'
        )

        def __init__(self, *, instance: "NetworkInstance", name: str):
            super().__init__(instance=instance, name=name)
            self.tempdir = instance.tempfile(name)
            os.mkdir(self.tempdir)
            _logger.debug(
                "%r temp-subdir for %r created: %s", instance, self, self.tempdir
            )

        def __repr__(self):
            return "<%s: %r>" % (self.__class__.__name__, self.name)

        def tempfile(self, name: str) -> str:
            return os.path.join(self.tempdir, name)

        def start(self):
            super().start()
            self.check_call([self._exec("ip"), "link", "set", "lo", "up"])

        def end_prep(self):
            pass

        def routes(
            self, af: Union[Literal[4], Literal[6]] = 4, local=False
        ) -> Dict[str, Any]:
            """
            get a json representation of all IPvX kernel routes

            af is 4 or 6
            if local is True, also include routes for the router's own
            addresses (useful for consistency checks across multiple routers,
            no need to special-case each router's own address)
            """

            assert af in [4, 6]
            ret: Dict[str, List[Any]] = {}

            def add(arr):
                for route in arr:
                    dst = route["dst"]
                    if dst == "default":
                        dst = "0.0.0.0/0"
                    if "/" not in dst:
                        dst = dst + ("/32" if af == 4 else "/128")
                    ret.setdefault(dst, []).append(route)

            def ip_r_call(extra=None):
                text = self.check_output(
                    [self._exec("ip"), "-%d" % af, "-j", "route", "list"]
                    + (extra or [])
                )
                text = self.iproute_json_re.sub(rb'"type":"\1"', text)
                try:
                    return json.loads(text)
                except json.decoder.JSONDecodeError as e:
                    raise SystemError("invalid JSON from iproute2: %r" % text) from e

            add(ip_r_call())
            if local:
                add(ip_r_call(["table", "local"]))

            for net in list(ret.keys()):
                if net.startswith("fe80:") or net.startswith("ff00:"):
                    del ret[net]

            return ret

        def status(self):
            print("##### status for %s #####" % self.name)
            self.check_call(
                [
                    "/bin/sh",
                    "-x",
                    "-c",
                    "hostname; ip addr list; ip route list; ip -6 route list; ps axuf",
                ],
                stderr=sys.stdout,
            )

    class SwitchyNS(BaseNS, topobase.SwitchyNS):
        """
        namespace used for switching between the various routers

        note only ONE of these is used.  multiple bridges are created in here
        to cover multiple switches with one namespace.  no IP addresses exist
        in this at all, it's just doing switching.

        most bridges represent p2p links and have only 2 member interfaces.
        however, it is intentional that these still go through a bridge
        because that (a) makes things consistent (b) allows us to attach
        tcpdump from the switch NS and (c) allows setting links down on the
        bridge side so the router gets "carrier down"
        """

        def start(self):
            """
            switch ns init:

            - kill br-nftables because that really fucks things up.
            - disable ipv6 everywhere because we don't want linklocals on
              these interfaces
            """
            super().start()

            calls = []
            calls.append("ip link set lo up")
            calls.extend(
                proc_write("/proc/sys/net/bridge/bridge-nf-call-iptables", "0")
            )
            calls.extend(
                proc_write("/proc/sys/net/bridge/bridge-nf-call-ip6tables", "0")
            )
            calls.extend(
                proc_write("/proc/sys/net/bridge/bridge-nf-call-arptables", "0")
            )
            calls.extend(proc_write("/proc/sys/net/ipv6/conf/all/disable_ipv6", "1"))
            calls.extend(
                proc_write("/proc/sys/net/ipv6/conf/default/disable_ipv6", "1")
            )

            self.check_call(["/bin/sh", "-e", "-c", "; ".join(calls)])

    class RouterNS(BaseNS, topobase.RouterNS):
        """
        a (FRR) router namespace.  maybe change the name.

        one of these corresponds to 1 router in the topology
        """

        def start(self):
            """
            router ns init:

            - turn on IP forwarding just in case
            - kill DAD because it just slows down tests
            - create all the interfaces from the topology
            - add the addresses the topology contains
            """
            super().start()

            assert self.instance.switch_ns is not None

            calls = []
            calls.extend(proc_write("/proc/sys/net/ipv4/ip_forward", "1"))
            calls.extend(proc_write("/proc/sys/net/ipv6/conf/all/forwarding", "1"))
            calls.extend(proc_write("/proc/sys/net/ipv6/conf/default/forwarding", "1"))
            calls.extend(proc_write("/proc/sys/net/ipv6/conf/all/optimistic_dad", "1"))
            calls.extend(
                proc_write("/proc/sys/net/ipv6/conf/default/optimistic_dad", "1")
            )
            calls.extend(proc_write("/proc/sys/net/ipv6/conf/all/accept_dad", "0"))
            calls.extend(proc_write("/proc/sys/net/ipv6/conf/default/accept_dad", "0"))

            for ip4 in self.instance.network.routers[self.name].lo_ip4:
                calls.append("ip -4 addr add %s dev lo scope global" % ip4)
            for ip6 in self.instance.network.routers[self.name].lo_ip6:
                calls.append("ip -6 addr add %s dev lo" % ip6)

            self.check_call(["/bin/sh", "-e", "-c", "; ".join(calls)])

            parentcalls = []
            calls = []

            for iface in self.instance.network.routers[self.name].ifaces:
                parentcalls.append(
                    "ip link add name %s address %s netns %d up type veth peer name %s netns %d"
                    % (
                        shlex.quote(iface.ifname),
                        shlex.quote(iface.macaddr),
                        self.pid,
                        shlex.quote(ifname(self.name, iface.ifname)),
                        self.instance.switch_ns.pid,
                    )
                )

                for ip4 in iface.ip4:
                    calls.append(
                        "ip -4 addr add %s dev %s" % (ip4, shlex.quote(iface.ifname))
                    )
                for ip6 in iface.ip6:
                    calls.append(
                        "ip -6 addr add %s dev %s" % (ip6, shlex.quote(iface.ifname))
                    )

            subprocess.check_call(["/bin/sh", "-e", "-c", "; ".join(parentcalls)])
            self.check_call(["/bin/sh", "-e", "-c", "; ".join(calls)])

        def link_set(self, iface: LinkIface, state: bool):
            """
            take an interface on this router up/down for poking things

            this changes the interface state on the switch NS since that gets
            propagated to the router NS as carrier state, so we get carrier
            down inside the router.  matches an unplugged LAN cable pretty
            well.
            """
            assert iface.ifname is not None
            assert self.instance.switch_ns is not None

            ifn = ifname(self.name, iface.ifname)
            self.instance.switch_ns.check_call(
                [
                    self._exec("ip"),
                    "link",
                    "set",
                    ifn,
                    "up" if state else "down",
                ]
            )

    network: Network
    switch_ns: Optional[SwitchyNS]
    routers: Dict[str, RouterNS]
    bridges: List[str]
    scapys: Dict[str, NetnsL2Socket]

    # TODO: none of the coverage stuff belongs in here.  but it works, and
    # right now (2023-09-28) that matters more than getting it to "perfect".
    gcov_dir: str
    lcov_args: List[str]

    _covdatafile: Optional[str] = None
    """
    filename of lcov coverage data from daemons in this namespace
    """

    _lcov: Optional[subprocess.Popen] = None
    """
    lcov process running asynchronously to extract coverage data
    """

    def __init__(self, network: Network):
        super().__init__(network)
        self.bridges = []
        self.lcov_args = []

    # pylint: disable=too-many-branches
    def start(self):
        """
        kick everything up

        also add the various interfaces to the bridges in the switch-NS.
        """

        assert self.switch_ns is not None

        self.switch_ns.start()
        for rns in self.routers.values():
            rns.start()

        # def linkinfo(iface):
        #    if isinstance(iface.endpoint, LAN):
        #        pid = self.switch_ns.pid
        #    else:
        #        pid = self.routers[iface.endpoint.name].pid
        #    name = iface.ifname
        #    mac = iface.macaddr
        #    return (str(pid), name, mac)

        for links in self.network.links.values():
            for link in links:
                if isinstance(link.a.endpoint, LAN):
                    continue
                if isinstance(link.b.endpoint, LAN):
                    continue
                brname = "%s_%s" % (link.a.endpoint.name, link.b.endpoint.name)
                if link.parallel_num != 0:
                    brname += "_%d" % (link.parallel_num)
                self.bridges.append(brname)
                self.switch_ns.check_call(
                    [
                        self._exec("ip"),
                        "link",
                        "add",
                        "name",
                        brname,
                        "up",
                        "promisc",
                        "on",
                        "type",
                        "bridge",
                    ]
                    + self._bridge_settings
                )
                self.switch_ns.check_call(
                    [
                        self._exec("ip"),
                        "link",
                        "set",
                        ifname(link.a.endpoint.name, link.a.ifname),
                        "up",
                        "master",
                        brname,
                    ]
                )
                self.switch_ns.check_call(
                    [
                        self._exec("ip"),
                        "link",
                        "set",
                        ifname(link.b.endpoint.name, link.b.ifname),
                        "up",
                        "master",
                        brname,
                    ]
                )

        for lan in self.network.lans.values():
            brname = lan.name
            self.bridges.append(brname)
            self.switch_ns.check_call(
                [
                    self._exec("ip"),
                    "link",
                    "add",
                    "name",
                    brname,
                    "up",
                    "type",
                    "bridge",
                ]
                + self._bridge_settings
            )
            for iface in lan.ifaces:
                self.switch_ns.check_call(
                    [
                        self._exec("ip"),
                        "link",
                        "set",
                        ifname(iface.other.endpoint.name, iface.other.ifname),
                        "up",
                        "master",
                        brname,
                    ]
                )

        self.scapys = {}
        args = []

        with self.switch_ns:
            for br in self.bridges:
                args.extend(["-i", br])

                with self.switch_ns.ctx_until_stop(NetnsL2Socket(iface=br)) as sock:
                    self.scapys[br] = sock
                    os.set_blocking(sock.fileno(), False)

        self.switch_ns.start_run()
        for rns in self.routers.values():
            rns.start_run()

    def _gcov_collect(self):
        have_gcov = False
        for dirname, _, filenames in os.walk(self.gcov_dir):
            for filename in filenames:
                if filename.endswith(".gcda"):
                    have_gcov = True

                    gcno = filename[:-5] + ".gcno"
                    target = os.path.join(dirname[len(self.gcov_dir) :], gcno)
                    os.symlink(target, os.path.join(dirname, gcno))

        if have_gcov:
            self._covdatafile = self.tempfile("lcov-data")
            assert self._covdatafile is not None

            # pylint: disable=consider-using-with
            self._lcov = subprocess.Popen(
                [
                    "lcov",
                    *self.lcov_args,
                    "-c",
                    "-q",
                    "-d",
                    self.gcov_dir,
                    "-o",
                    self._covdatafile,
                ]
            )

    def coverage_wait(self) -> Optional[str]:
        if self._lcov is not None:
            self._lcov.wait()
            self._lcov = None
        return self._covdatafile

    def stop(self):
        assert self.switch_ns is not None

        for rns in self.routers.values():
            rns.end_prep()
        for rns in self.routers.values():
            rns._do_atexit()
            rns.end()

        self.switch_ns._do_atexit()
        self.switch_ns.end()
        self._gcov_collect()

    def status(self):
        assert self.switch_ns is not None

        self.switch_ns.status()
        for rns in self.routers.values():
            rns.status()


def test():
    # pylint: disable=import-outside-toplevel
    from . import toponom
    import tempfile

    net = toponom.test()

    class TestNetworkInstance(NetworkInstance):
        def tempfile(self, name):
            return tempfile.mktemp(name)

    instance = TestNetworkInstance(net)
    instance.prepare()
    try:
        instance.start()
    except subprocess.CalledProcessError as e:
        print(e)
        time.sleep(60)
        raise
    print("--- r1 ---")
    instance.routers["r1"].check_call(["ip", "addr", "list"])
    print("--- r2 ---")
    instance.routers["r2"].check_call(["ip", "addr", "list"])

    return instance


if __name__ == "__main__":
    _instance = test()

    time.sleep(30)
    _instance.stop()
