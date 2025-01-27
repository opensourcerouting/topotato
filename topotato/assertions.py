#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2018-2021  David Lamparter for NetDEF, Inc.
"""
Assertions (and Modifiers) to use in topotato tests:
"""
# pylint: disable=too-many-ancestors

import os
import sys
import json
import logging
import tempfile
import re
import inspect
from collections import OrderedDict

import typing
from typing import (
    cast,
    Any,
    Callable,
    ClassVar,
    List,
    Optional,
    Type,
    Union,
)

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal  # type: ignore

from scapy.packet import Packet  # type: ignore

from .utils import json_cmp, text_rich_cmp, deindent
from .base import TopotatoItem, TopotatoFunction, skiptrace, SkipMode
from .livescapy import TimedScapy
from .frr.livelog import LogMessage
from .timeline import TimingParams
from .exceptions import (
    TopotatoCLICompareFail,
    TopotatoCLIUnsuccessfulFail,
    TopotatoLogFail,
    TopotatoPacketFail,
    TopotatoRouteCompareFail,
    TopotatoUnhandledArgs,
    TopotatoInvalidArg,
)

if typing.TYPE_CHECKING:
    from .frr.core import FRRRouterNS
    from . import toponom, topobase

__all__ = [
    "AssertKernelRoutesV4",
    "AssertKernelRoutesV6",
    "AssertVtysh",
    "AssertPacket",
    "AssertLog",
    "DaemonStop",
    "DaemonRestart",
    "Delay",
    "ModifyLinkStatus",
    "BackgroundCommand",
    "ReconfigureFRR",
]

_logger = logging.getLogger(__name__)


class TopotatoAssertion(TopotatoItem):
    """
    Common base for assertions (test items that do NOT modify state)
    """

    cascade_failures = SkipMode.SkipThis


class TopotatoModifier(TopotatoItem):
    """
    Common base for modifiers (test items that DO modify state)

    The intention here is to allow the framework to distinguish whether some
    item is a dependency for future assertions.  If an assertion fails, the
    test continues.  If a modifier fails, the remainder of the test is skipped.
    """

    cascade_failures = SkipMode.SkipThisAndLater


class TimedMixin:
    """
    Helper for (retry-)timing configuration.

    :param float delay: interval to retry test at, in seconds.
    :param Optional[float] maxwait: deadline until which to retry.  At least
       one attempt is made even if this deadline has already passed.

    For simplicity, the same mixin is used for active and passive timing.
    Active timing uses the delay parameter to repeat active attempts whie
    passive timing listens on received events and therefore does not use the
    delay parameter.

    .. caution::

       The ``maxwait`` parameter is a deadline anchored at **starting up the
       test network for this test class**, not the particular test (which is
       what topotests did.)

       This is generally what's needed for tests:  something is supposed to
       have converted by X time after the test environment was started up.

       The distinction is particularly important when a test is indeed failing:
       two consecutive tests with the same deadline will *not* make topotato
       wait twice that amount, the wait on the first test will have depleted
       the maxwait for the second and only one attempt will be made that.
    """

    _timing: TimingParams

    default_delay: ClassVar[Optional[float]] = None
    """
    Delay between active attempts.

    Only used for assertions that actively perform checks rather than
    listening for events.  If None, the delay parameter will not be accepted.
    """
    default_maxwait: ClassVar[Optional[float]] = None
    """
    Maximum time to wait on this assertions.
    """

    def __init__(self, **kwargs):
        cls = self.__class__
        if cls.default_delay is None:
            if "delay" in kwargs:
                raise TopotatoUnhandledArgs(
                    "%s does not accept a delay parameter" % cls.__name__
                )

        delay = kwargs.pop("delay", cls.default_delay)
        maxwait = kwargs.pop("maxwait", cls.default_maxwait)

        super().__init__(**kwargs)

        self._timing = TimingParams(delay, maxwait)
        self._timing.anchor(self.relative_start)

        fn = cast(TopotatoItem, self).getparent(TopotatoFunction)
        assert fn is not None
        if fn.include_startup:
            self._timing.full_history = True

    def relative_start(self):
        fn = cast(TopotatoItem, self).getparent(TopotatoFunction)
        assert fn is not None
        return fn.started_ts


class AssertKernelRoutes(TimedMixin, TopotatoAssertion):
    """
    Common code for v4/v6 kernel routing table check.
    """

    af: ClassVar[Union[Literal[4], Literal[6]]]
    default_delay = 0.1

    _rtr: str
    _routes: dict
    _local: bool

    posargs = ["rtr", "routes"]

    # pylint: disable=too-many-arguments
    def __init__(self, *, name, rtr, routes, local=False, **kwargs):
        name = "%s:%s/routes-v%d" % (name, rtr, self.af)
        super().__init__(name=name, **kwargs)

        self._rtr = rtr
        self._routes = routes
        self._local = local

    def __call__(self):
        router = self.instance.routers[self._rtr]

        for _ in self.timeline.run_tick(self._timing):
            routes = router.routes(self.af, self._local)
            diff = json_cmp(routes, self._routes)
            if diff is None:
                break
        else:
            raise TopotatoRouteCompareFail(str(diff))


class AssertKernelRoutesV4(AssertKernelRoutes):
    """
    Retrieve IPv4 routing table from kernel and compare against reference.

    .. py:method:: make(rtr, routes, *, local=False, delay=0.1, maxwait=None)
       :classmethod:

       Generate a test item to verify the kernel IPv4 routing table matches
       some expectation.

       :param Union[str, .toponom.Router] rtr: Router to retrieve routes from.
          Either a string router name or a :py:class:`toponom.Router` object is
          acceptable.
       :param Dict[str, Any] routes: Expected routes.  Dictionary may include
          JSONCompare flags like :py:class:`.utils.JSONCompareIgnoreContent`.
       :param local: include ``local`` table / system routes.
    """

    # mypy issue 8796 workaround - repeat the type
    af: ClassVar[Union[Literal[4], Literal[6]]]
    af = 4


class AssertKernelRoutesV6(AssertKernelRoutes):
    """
    Same as :py:class:`AssertKernelRoutesV4`, but for IPv6.
    """

    # mypy issue 8796 workaround - repeat the type
    af: ClassVar[Union[Literal[4], Literal[6]]]
    af = 6


class AssertVtysh(TimedMixin, TopotatoAssertion):
    _nodename = "vtysh"
    _cmdprefix = ""

    commands: OrderedDict

    _rtr: "toponom.Router"
    _daemon: str
    _command: str
    _compare: Optional[str]
    _filters: List[Callable[[str], str]]

    default_delay = 0.1
    default_filters = [
        lambda t: deindent(t, trim=True),
    ]

    posargs = ["rtr", "daemon", "command", "compare"]

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        *,
        name,
        rtr,
        daemon,
        command,
        compare=None,
        filters=None,
        **kwargs,
    ):
        if not isinstance(compare, (str, dict, list, type(None))):
            raise TopotatoInvalidArg(f"invalid input to AssertVtysh: {compare!r}")

        command_cleaned = command
        command_cleaned = re.sub(r"(?m)^[\s\n]+", "", command_cleaned)
        command_cleaned = re.sub(r"\s+\n", "\n", command_cleaned)
        command_cleaned = command_cleaned.rstrip("\n")
        command_cleaned = re.sub(r"\n+", "; ", command_cleaned)

        name = "%s:%s/%s/%s[%s]" % (
            name,
            rtr.name,
            daemon,
            self._nodename,
            command_cleaned,
        )
        super().__init__(name=name, **kwargs)

        self._rtr = rtr
        self._daemon = daemon
        self._command = self._cmdprefix + command
        self._compare = compare
        self._filters = filters or self.default_filters

    def __call__(self):
        router = cast("FRRRouterNS", self.instance.routers[self._rtr.name])

        for _ in self.timeline.run_tick(self._timing):
            _, out, rc = router.vtysh_polled(self.timeline, self._daemon, self._command)
            if rc != 0:
                msg = f"vtysh return value {rc}"
                if out and out[-1].text.strip() != "":
                    line = out[-1].text.strip().rsplit("\n", 1)[-1]
                    msg = f"{msg}, output: {line}"
                result = TopotatoCLIUnsuccessfulFail(msg)
            else:
                result = None
                text = "".join(event.text for event in out)

                if isinstance(self._compare, type(None)):
                    pass
                elif isinstance(self._compare, str):
                    for filterfn in self._filters:
                        text = filterfn(text)
                    result = text_rich_cmp(
                        router._configs,
                        text,
                        self._compare,
                        "output from %s" % (self._command),
                    )
                else:
                    diff = json_cmp(json.loads(text), self._compare)
                    if diff is not None:
                        result = TopotatoCLICompareFail(str(diff))

            if result is None:
                out[-1].match_for.append(self)
                break
        else:
            assert result is not None
            raise result

    @property
    def command(self):
        return self._command

    @property
    def compare(self):
        return self._compare


class ReconfigureFRR(AssertVtysh):
    _nodename = "reconfigure"
    _cmdprefix = "enable\nconfigure\n"


class AssertPacket(TimedMixin, TopotatoAssertion):
    _link: str
    _pkt: Any
    _argtypes: List[Type[Packet]]
    _expect_pkt: bool

    matched: Optional[Any]

    posargs = ["link", "pkt", "expect_pkt"]

    # pylint: disable=too-many-arguments
    def __init__(self, *, name, link, pkt, expect_pkt=True, **kwargs):
        name = "%s:%s/packet" % (name, link)
        super().__init__(name=name, **kwargs)

        self._link = link
        self._pkt = pkt
        self._expect_pkt = expect_pkt
        self.matched = None

        self._argtypes = []
        argspec = inspect.getfullargspec(self._pkt)
        for arg in argspec.args[: len(argspec.args) - len(argspec.defaults or ())]:
            if arg not in argspec.annotations:
                raise TypeError(
                    "%r needs a type annotation for parameter %r" % (self._pkt, arg)
                )
            argtype = argspec.annotations[arg]
            if not issubclass(argtype, Packet):
                raise TypeError(
                    "%r argument %r (%r) is not a scapy.Packet subtype"
                    % (self._pkt, arg, argtype)
                )
            self._argtypes.append(argtype)

    def __call__(self):
        for element in self.timeline.run_timing(self._timing):
            if not isinstance(element, TimedScapy):
                continue
            pkt = element.pkt
            if pkt.sniffed_on != self._link:
                continue

            args = []
            cur_layer = pkt

            for argtype in self._argtypes:
                cur_layer = cur_layer.getlayer(argtype)
                if cur_layer is None:
                    break
                args.append(cur_layer)

            if cur_layer is None:
                continue

            if self._pkt(*args):
                self.matched = pkt
                element.match_for.append(self)
                if not self._expect_pkt:
                    raise TopotatoPacketFail(
                        "received an unexpected matching packet for:\n%s"
                        % inspect.getsource(self._pkt)
                    )
                break
        else:
            if self._expect_pkt:
                raise TopotatoPacketFail(
                    "did not receive a matching packet for:\n%s"
                    % inspect.getsource(self._pkt)
                )


class AssertLog(TimedMixin, TopotatoAssertion):
    _rtr: str
    _daemon: str
    _pkt: Any
    _msg = Union[re.Pattern, str]

    matched: Optional[Any]

    posargs = ["rtr", "daemon", "msg"]

    # pylint: disable=arguments-differ,protected-access,too-many-arguments
    def __init__(self, *, name, rtr, daemon, msg, **kwargs):
        name = "%s:%s/%s/log" % (name, rtr.name, daemon)
        super().__init__(name=name, **kwargs)

        self._rtr = rtr
        self._daemon = daemon
        self._msg = msg
        self.matched = None

    @skiptrace
    def __call__(self):
        for msg in self.timeline.run_timing(self._timing):
            if not isinstance(msg, LogMessage):
                continue

            text = msg.text
            if isinstance(self._msg, re.Pattern):
                m = self._msg.match(text)
                if not m:
                    continue
            else:
                if text.find(self._msg) == -1:
                    continue

            self.matched = msg
            msg.match_for.append(self)
            break
        else:
            if isinstance(self._msg, re.Pattern):
                detail = cast(str, self._msg.pattern)
            else:
                detail = cast(str, self._msg)
            raise TopotatoLogFail(detail)


class Delay(TimedMixin, TopotatoAssertion):
    @skiptrace
    def __call__(self):
        for _ in self.timeline.run_timing(self._timing):
            pass


class _DaemonControl(TopotatoModifier):
    _rtr: "toponom.Router"
    _daemon: str

    op_name: ClassVar[str]
    posargs = ["rtr", "daemon"]

    def __init__(self, *, name, rtr, daemon, **kwargs):
        name = "%s:%s/%s/%s" % (name, rtr.name, daemon, self.op_name)
        super().__init__(name=name, **kwargs)
        self._rtr = rtr
        self._daemon = daemon

    def do(self, router):
        pass

    def runtest(self):
        router = self.instance.routers[self._rtr.name]
        self.do(router)


class DaemonRestart(_DaemonControl):
    op_name = "restart"

    def do(self, router):
        router.restart_daemon(self._daemon)


class DaemonStop(_DaemonControl):
    op_name = "stop"

    def do(self, router):
        router.stop_daemon(self._daemon)


class ModifyLinkStatus(TopotatoModifier):
    _rtr: Any
    _iface: "toponom.LinkIface"
    _state: bool

    posargs = ["rtr", "iface", "state"]

    # pylint: disable=too-many-arguments
    def __init__(self, *, name, rtr, iface, state, **kwargs):
        name = "%s:%s/link[%s (%s) -> %s]" % (
            name,
            rtr.name,
            iface.ifname,
            iface.other.endpoint.name,
            "UP" if state else "DOWN",
        )
        super().__init__(name=name, **kwargs)

        self._rtr = rtr
        self._iface = iface
        self._state = state

    def __call__(self):
        router = self.instance.routers[self._rtr.name]
        router.link_set(self._iface, self._state)


class BackgroundCommand:
    """
    run sth in bg
    """

    _rtr: "toponom.Router"

    tmpfile: Any
    proc: Any

    def __init__(self, rtr, cmd):
        self._rtr = rtr
        self._cmd = cmd

    class Action(TopotatoModifier):
        _rtr: "toponom.Router"
        _cmdobj: "BackgroundCommand"

        def __init__(self, *, name, cmdobj, **kwargs):
            name = '%s:%s/exec["%s" (%s)]' % (
                name,
                cmdobj._rtr.name,
                cmdobj._cmd,
                self.__class__.__name__,
            )
            super().__init__(name=name, **kwargs)

            self._rtr = cmdobj._rtr
            self._cmdobj = cmdobj

    class Start(Action):
        # pylint: disable=consider-using-with
        def __call__(self):
            router = cast("topobase.CallableNS", self.instance.routers[self._rtr.name])

            ifd = open("/dev/null", "rb")
            self._cmdobj.tmpfile = tmpfile = tempfile.TemporaryFile()

            self._cmdobj.proc = router.popen(
                ["/bin/sh", "-c", self._cmdobj._cmd],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                stdin=ifd,
                stdout=tmpfile,
                stderr=tmpfile,
            )

    class Wait(Action):
        def __call__(self):
            ret = self._cmdobj.proc.wait()
            self._cmdobj.tmpfile.seek(0)
            output = self._cmdobj.tmpfile.read().decode("UTF-8")
            del self._cmdobj.tmpfile
            sys.stdout.write(output)

            if ret != 0:
                raise ValueError("nonzero exit: %s!" % ret)

    @skiptrace
    def start(self):
        yield from self.Start.make(cmdobj=self)

    @skiptrace
    def wait(self):
        yield from self.Wait.make(cmdobj=self)
