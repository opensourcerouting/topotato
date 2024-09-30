#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2023  David Lamparter for NetDEF, Inc.
"""
Abstract base classes for NetworkInstance/SwitchyNS/RouterNS

This module defines the interface exposed by the OS-specific network instance
and virtual router wrappers.  The :py:mod:`topotato.osdep` module selects the
appropriate implementation at runtime.  For type checking, only the methods
and attributes defined here should be used outside OS-specific code.
"""
# pylint: disable=unused-argument

from abc import ABC, abstractmethod
import os
import typing
from typing import (
    cast,
    Any,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Tuple,
    Union,
)
from typing_extensions import Protocol

from .utils import self_or_kwarg

if typing.TYPE_CHECKING:
    from typing import (
        Self,
        TypeAlias,
    )
    import subprocess
    from . import toponom
    from .timeline import Timeline


class BaseNS:
    """
    Common interface to a virtual host/router.

    Note that this is intentionally generic in not assuming code can be
    executed on that virtual system.  At some point in the future, topotato
    might add support for "external" DUTs with limited interfaces.

    .. todo::

       Tighter integration with :py:class:`Timeline`?
    """

    instance: "NetworkInstance"

    def __init__(self, *, instance: "NetworkInstance", **kw) -> None:
        self.instance = instance
        self_or_kwarg(self, kw, "name")

        super().__init__(**kw)

    def tempfile(self, name: str) -> str:
        """
        Get a path for a temporary file.
        """
        return ""

    def start(self) -> None:
        """
        Start this virtual system.
        """

    def start_run(self) -> None:
        """
        Second-stage start, e.g. things inside the virtual system.
        """

    def start_post(self, timeline: "Timeline", failed: List[Tuple[str, str]]) -> None:
        """
        Perform post-start checks.  Empty by default.

        .. todo::

           rework/remove "failed" parameter.
        """

    def end_prep(self) -> None:
        """
        Prepare for shutdown.
        """

    def end(self) -> None:
        """
        Stop this virtual system.
        """


class SwitchyNS(BaseNS):
    """
    Virtual switch at the center of an emulated network.

    This doesn't have any specific extra methods to it.
    """


class RouterNS(BaseNS):
    """
    Virtual router or host of some type in this network instance.
    """

    name: str
    """
    All virtual routers/hosts have at least a name.
    """

    @abstractmethod
    def interactive_state(self) -> Dict[str, Any]:
        """
        Retrieve state for interactive / potatool access.
        """

    @abstractmethod
    def report_state(self) -> Optional[Dict[str, Any]]:
        """
        Retrieve state for HTML test report.
        """
        return None

    def routes(
        self, af: Union[Literal[4], Literal[6]] = 4, local=False
    ) -> Dict[str, Any]:
        """
        Retrieve kernel routing table from this system.

        .. todo::

           Implement a type/protocol for the return value.
        """
        return {}

    def link_set(self, iface: "toponom.LinkIface", state: bool) -> None:
        """
        Set one of this systems interfaces up or down.
        """


class CallableNS(Protocol):
    """
    Typing protocol for virtual routers that can execute programs.

    Implementing this protocol is a requirement for all uses currently.
    """

    def check_call(self, cmdline: List[str], *args, **kwargs) -> None: ...

    def check_output(
        self, cmdline: List[str], *args, **kwargs
    ) -> Tuple[bytes, bytes]: ...

    def popen(self, cmdline: List[str], *args, **kwargs) -> "subprocess.Popen": ...


class CallableEnvMixin(ABC):
    """
    Mixin to apply env= from router/instance on subprocess creation.
    """

    environ: Dict[str, str]
    """
    OS environment variables for processes created on this virtual router
    """
    instance: "NetworkInstance"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.environ = {}

    def _modify_env(self, kwargs):
        # don't modify caller's env dict (or os.environ)
        kwargs["env"] = dict(kwargs.get("env", os.environ))
        kwargs["env"].update(self.instance.environ)
        kwargs["env"].update(self.environ)

    def popen(self, cmdline: List[str], *args, **kwargs):
        self._modify_env(kwargs)
        _super: CallableNS = cast(CallableNS, super())
        return _super.popen(cmdline, *args, **kwargs)

    def check_call(self, cmdline: List[str], *args, **kwargs):
        self._modify_env(kwargs)
        _super: CallableNS = cast(CallableNS, super())
        return _super.check_call(cmdline, *args, **kwargs)

    def check_output(self, cmdline: List[str], *args, **kwargs):
        self._modify_env(kwargs)
        _super: CallableNS = cast(CallableNS, super())
        return _super.check_output(cmdline, *args, **kwargs)


class NetworkInstance(ABC):
    """
    A possibly-running virtual network for a test.
    """

    network: "toponom.Network"
    switch_ns: Optional[SwitchyNS]
    routers: Mapping[str, RouterNS]

    RouterNS: "TypeAlias" = RouterNS
    """
    To be overridden by concrete implementations, the virtual router type
    generally assumed by this instance.
    """
    SwitchyNS: "TypeAlias" = SwitchyNS
    """
    To be overridden by concrete implementations.
    """
    environ: Dict[str, str]
    """
    OS environment variables for processes created on this instance
    """

    def __init__(self, network: "toponom.Network") -> None:
        super().__init__()
        self.network = network
        self.switch_ns = None
        self.routers = {}
        self.environ = {}

    def make(self, name: str) -> RouterNS:
        """
        Overrideable method to instantiate a virtual router in this instance.

        Subclasses further down the chain may want to use custom subclasses
        for specific virtual routers.  This enables that.
        """
        # pylint: disable=abstract-class-instantiated
        return self.RouterNS(instance=self, name=name)  # type: ignore

    @abstractmethod
    def tempfile(self, name: str) -> str:
        """
        Get a path for a temporary file.
        """

    def prepare(self) -> "Self":
        """
        Execute setup (create switch & router objects) for this network instance.
        """
        # pylint: disable=abstract-class-instantiated
        self.switch_ns = self.SwitchyNS(instance=self, name="switch-ns")

        # self.routers is immutable, assign as a whole
        routers = {}
        for r in self.network.routers.values():
            routers[r.name] = self.make(r.name)
        self.routers = routers
        return self

    @abstractmethod
    def start(self) -> None:
        """
        Start this network instance.
        """

    @abstractmethod
    def stop(self) -> None:
        """
        Stop this network instance.
        """
