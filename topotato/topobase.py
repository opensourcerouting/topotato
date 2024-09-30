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
import weakref
import warnings
import typing
from typing import (
    cast,
    Any,
    Callable,
    ContextManager,
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


class _ContextAtexit:
    """
    Context Manager wrapper to hold things until a virtual system stops.

    Used primarily for sockets in a virtual system.  Refer to
    :py:meth:`BaseNS.ctx_until_stop`.
    """

    ns: "BaseNS"

    hold: Callable[[], Optional[ContextManager]]
    """
    Either a regular closure, or a weakref, to get the wrapped context manager.
    Using a weakref allows the wrapped context object's lifetime to end earlier.
    """

    exit_on_exception: bool

    _strong_ref: Optional[ContextManager]
    """
    Used only during the span between ``__init__`` and ``__exit__``.
    """

    def __init__(
        self,
        ns: "BaseNS",
        context: ContextManager,
        *,
        exit_on_exception=True,
        weak=False,
    ):
        self.ns = ns
        self._strong_ref = context
        self.exit_on_exception = exit_on_exception

        if weak:
            self.hold = weakref.ref(context)
        else:
            self.hold = lambda: context

    def __enter__(self):
        assert self._strong_ref is not None

        return self._strong_ref.__enter__()

    def __exit__(self, exc_type, exc_value, tb):
        assert self._strong_ref is not None

        if self.exit_on_exception and exc_value is not None:
            self._strong_ref.__exit__(exc_type, exc_value, tb)
        else:
            self.ns.atexit(self)

        # context manager may now drop if weak=True
        self._strong_ref = None

    def __call__(self):
        assert self._strong_ref is None

        context = self.hold()
        if context is None:
            # weakref gone away
            return
        context.__exit__(None, None, None)


class AtexitExceptionIgnoredWarning(UserWarning):
    """
    :py:mod:`warnings` category for exceptions ignored during router atexit.

    Exceptions from a router's :py:meth:`BaseNS.atexit` functions shouldn't
    prevent other atexit functions from running (or really abort things
    in general.)  They're therefore converted to warnings of this category
    (much like exceptions during normal ``atexit`` or ``__del__``.)
    """


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
    _atexit: List[Callable[[], None]]

    def __init__(self, *, instance: "NetworkInstance", **kw) -> None:
        self.instance = instance
        self_or_kwarg(self, kw, "name")

        super().__init__(**kw)
        self._atexit = []

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

        .. warning::

           This should call :py:meth:`_do_atexit`, but currently doesn't.
           Needs a cleanup pass on sequencing of things between
           :py:meth:`end_prep`, :py:meth:`end`, and MRO/super() call order.

           (The main concern is losing important logs/events on shutdown if
           closing things too early.)
        """

    def _do_atexit(self) -> None:
        for atexit in self._atexit:
            try:
                atexit()
            except Exception as e:  # pylint: disable=broad-exception-caught
                filename, lineno, module_globals = "<???>", 0, {}

                tb = e.__traceback__
                if tb:
                    while tb.tb_next:
                        tb = tb.tb_next

                    filename = tb.tb_frame.f_code.co_filename
                    lineno = tb.tb_frame.f_lineno
                    module_globals = tb.tb_frame.f_globals
                    del tb

                warnings.warn_explicit(
                    f"Exception during atexit: {e!r}",
                    AtexitExceptionIgnoredWarning,
                    filename=filename,
                    lineno=lineno,
                    module_globals=module_globals,
                )

    def atexit(self, fn: Callable[[], None]):
        """
        Call given function when this system stops.

        Exceptions from the function are converted into warnings of category
        :py:class:`AtexitExceptionIgnoredWarning`, i.e. won't crash out.
        """
        self._atexit.insert(0, fn)

    def ctx_until_stop(
        self, context: ContextManager, *, exit_on_exception=True, weak=False
    ):
        """
        Wrap a context manager and keep it alive until this system stops.

        Use like::

            with router.ctx_until_stop(socket(...)) as sock:
                sock.connect(...)

        The socket will then be closed when router is stopped, or will be
        immediately closed if an exception occurs inside the ``with`` block.

        :param ContextManager context: context manager to wrap.
        :param bool exit_on_exception: if True (default), clean up the context
            manager immediately if an exception happens in the ``with`` block.
            If False, the context manager always lives until the router shuts
            down.
        :param bool weak: use a weak reference to hold the context manager.
            May be useful to allow some object to go out of scope earlier.
        :return: a context manager wrapping the original one, with the same
            return value from ``__enter__``.
        """
        return _ContextAtexit(
            self, context, exit_on_exception=exit_on_exception, weak=weak
        )


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
