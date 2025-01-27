#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2023  David Lamparter for NetDEF, Inc.
"""
Test network for topotato.
"""

import logging
import itertools
import os
import re
import typing
from typing import (
    cast,
    Any,
    ClassVar,
    Dict,
    List,
    Optional,
    Tuple,
    Type,
)

from .timeline import Timeline
from .osdep import NetworkInstance

if typing.TYPE_CHECKING:
    from . import toponom
    from .types import ISession
    from .frr.core import FRRSetup
    from .pretty import PrettyInstance


_logger = logging.getLogger(__name__)


class TopotatoNetwork(NetworkInstance):
    """
    Main network representation & interface.

    This class is not used directly;  each test (or multiple tests if they are
    very similar) create subclasses of it.  The topotato machinery then creates
    an instance through the subclass to run a particular test class against.

    System names referenced in the topology are looked up directly in the class
    namespace to get the "system type" (a subclass of
    :py:class:`TopotatoParams`) for each system.  For example, for
    ``[ h1 ]---[ h2 ]``, "h1" and "h2" should be class variables on the
    subclass like this::

        class TestSetup(TopotatoNetwork, topo=topology):
            h1: Host
            h2: Host

    (where :py:class:`Host` refers to the class defined below.)

    Note that the test only defines the subclass but does not create an
    instance of it, that only happens when topotato actually runs the test.
    """

    timeline: Timeline
    session: "ISession"
    nodeid: str
    pretty: "PrettyInstance"
    reports: List[Any]

    _network: ClassVar["toponom.Network"]

    _defaultparams: ClassVar[Optional[Type["TopotatoParams"]]] = None
    """
    Fallback class to use if a system in the topology has no type annotation.
    This mostly exists to support "all-FRR" test setups.
    """

    _params: Dict[str, "TopotatoParams"]
    """
    Instances of :py:class:`TopotatoParams` for each system in this topology.
    Created during ``__init__``, then used to invoke
    :py:meth:`TopotatoParams.instantiate` on when the network is brought up.

    The items of this dict are also accessible as member variables on
    instances, which matches the behavior implied by the type annotations.
    """

    tempdir: str

    def __repr__(self):
        return f"{self.__class__.__name__}(..., {self.nodeid!r})"

    def make(self, name: str) -> NetworkInstance.RouterNS:
        return self._params[name].instantiate()

    def __init__(self, session: "ISession", nodeid: str):
        self.nodeid = nodeid
        super().__init__(self.__class__._network)
        self.session = session
        self.timeline = Timeline()
        self._params = {}

        taskdir = session.interactive_session.taskdir
        # AF_UNIX has a pretty short path name limit, hence the [:32] here
        basename = re.sub("[^0-9a-zA-Z]", "_", nodeid.rsplit(":", 1)[-1])[:32]

        for suffix in itertools.chain([""], range(0, 100)):
            self.tempdir = os.path.join(taskdir, basename + str(suffix))
            try:
                os.mkdir(self.tempdir)
            except OSError:
                continue
            break

        else:
            # this will fail, the point is to raise the exception
            self.tempdir = os.path.join(taskdir, basename)
            os.mkdir(self.tempdir)

        os.chmod(self.tempdir, 0o755)
        _logger.debug("%r tempdir created: %s", self, self.tempdir)

        self.environ["GCOV_PREFIX"] = self.gcov_dir = self.tempfile("gcov")

        for name in self._network.routers.keys():
            if name in self.__class__.__annotations__:
                paramcls = cast(
                    Type[TopotatoParams], self.__class__.__annotations__[name]
                )
            elif self._defaultparams is not None:
                paramcls = self._defaultparams
            else:
                raise ValueError(f"no router type/parameters for {name!r}")

            self._params[name] = paramcls(self, name)
            setattr(self, name, self._params[name])

    @classmethod
    def __init_subclass__(cls, /, topo=None, params=None, **kwargs):
        super().__init_subclass__(**kwargs)

        if not topo:
            return

        while not hasattr(topo, "net") and (
            hasattr(topo, "__wrapped__") or hasattr(topo, "topo")
        ):
            topo = getattr(topo, "__wrapped__", topo)
            topo = getattr(topo, "topo", topo)

        cls._network = topo.net
        if params is not None:
            cls._defaultparams = params

    def tempfile(self, name):
        return os.path.join(self.tempdir, name)


class TopotatoParams:
    """
    The set of necessary information for system(s) in a test topology.

    The various subclasses of this class primarily encapsulate configs for a
    given kind of router.  The information is placed on the **subclass**, not
    instances of it;  for tests with similar configs on multiple routers,
    the same subclass is instantiated multiple times for each router.
    """

    instance: TopotatoNetwork
    name: str

    def __init__(self, instance: TopotatoNetwork, name: str):
        self.instance = instance
        self.name = name

    def instantiate(self) -> NetworkInstance.RouterNS:
        raise NotImplementedError(f"cannot instantiate router {self.name!r}")


class HostNS(TopotatoNetwork.RouterNS):
    """
    A plain host in the test network.

    Just overrides the necessary abstract bits from
    :py:class:`TopotatoNetwork.RouterNS` with empty stubs.
    """

    def interactive_state(self) -> Dict[str, Any]:
        return {}

    def report_state(self) -> Optional[Dict[str, Any]]:
        return None

    def start_post(self, timeline, failed: List[Tuple[str, str]]):
        pass


class Host(TopotatoParams):
    """
    Plain hosts in the network - no parameters needed.
    """

    def instantiate(self):
        # pylint: disable=abstract-class-instantiated
        return HostNS(instance=self.instance, name=self.name)
