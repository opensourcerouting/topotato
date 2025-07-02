#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2018-2021  David Lamparter for NetDEF, Inc.
"""
topotato is designed as a heavily custom extension to pytest.  The core
aspects of this are defined in this module (:py:mod:`topotato.base`).
"""

import os
import inspect
from collections import OrderedDict
import time
import logging
import string
from enum import Enum

import typing
from typing import (
    Any,
    Callable,
    ClassVar,
    Dict,
    Generator,
    Iterable,
    List,
    Optional,
    Tuple,
    Type,
    Union,
    cast,
)

import pytest
import _pytest
from _pytest import nodes
from _pytest.outcomes import Failed, Skipped

# from _pytest.mark.structures import Mark

from .exceptions import (
    TopotatoFail,
    TopotatoEarlierFailSkip,
    TopotatoDaemonCrash,
    TopotatoUnhandledArgs,
)
from .livescapy import LiveScapy
from .generatorwrap import GeneratorWrapper, GeneratorChecks
from .network import TopotatoNetwork
from .leaks import FDState, FDDelta, fdinfo

if typing.TYPE_CHECKING:
    from types import TracebackType

    from _pytest._code.code import ExceptionInfo, TracebackEntry, Traceback
    from _pytest.python import Function

    from .toponom import Network
    from .timeline import Timeline
    from .pretty import PrettyItem

_logger = logging.getLogger(__name__)


class _SkipTrace(set):
    """
    Get calling code location while skipping over specific functions.

    Create an instance (cf. :py:data:`skiptrace`), then use that instance as
    decorator (without braces at the end!).
    """

    def __call__(self, origfn):
        fn = origfn
        while not hasattr(fn, "__code__") and hasattr(fn, "__func__"):
            fn = getattr(fn, "__func__")
        self.add(fn.__code__)
        return origfn

    def __repr__(self):
        # this is pretty much just for sphinx/autodoc
        return "<%s.%s>" % (self.__class__.__module__, self.__class__.__name__)

    def get_callers(self) -> List[inspect.FrameInfo]:
        """
        :return: the calling stack frames left after skipping over functions
           annotated with this decorator.
        """
        stack = inspect.stack()
        stack.pop(0)

        while stack and stack[0].frame.f_code in self:
            stack.pop(0)

        if not stack:
            raise IndexError("cannot locate caller")
        return stack


skiptrace = _SkipTrace()
"""
Decorator for use in topotato logic to make tracebacks more useful.

Functions/methods annotated with this decorator will be left out when printing
backtraces.  Most :py:mod:`topotato.assertions` code should use this since the
inner details of how a topotato assertion works are not normally what you want
to debug when a test fails.

.. todo::

   Add a testrun/pytest option that disables this, for bug hunting in topotato
   itself.
"""

endtrace = _SkipTrace()


class ItemGroup(list["TopotatoItem"]):
    """
    Return value of the :py:meth:`TopotatoItem.make` generators.

    This is handed back as a temporary second reference to the test items that
    were just yielded back from the ``yield from`` in a test, in order to allow
    optional additional tinkering with test items.

    See :py:meth:`skip_on_exception` below for how to use this.
    """

    def skip_on_exception(self, fn: Callable[["TopotatoItem"], None]):
        """
        Add conditional skip to given test items.

        For use either as a function decorator, or with helper functions.  Adds
        the given callable function to prerequisites of all test items::

            mytests = yield from AssertSomething.make(...)

            # condition A (as decorator)
            @mytests.skip_on_exception
            def conditional(item):
                raise TopotatoSkipped("don't actually run this")

            # condition B (use helper)
            mytests.skip_on_exception(check_feature_xyz)
        """
        for item in self:
            item.skipchecks.append(fn)


class SkipMode(Enum):
    """
    Behavior regarding failures in earlier/later topotato test items.
    """

    DontSkip = 0
    """
    Always execute this test item, even if earlier items had problems.
    """

    SkipThis = 1
    """
    Skip this test item if something before it cascade-failed, but don't
    cascade failures from this item.
    """

    SkipThisAndLater = 2
    """
    Skip this test item if something before it cascade-failed, and also make
    failures in this test item cascade to later items.
    """

    SkipThisAndLaterHard = 3
    """
    As previous, but Skipping this item cascades as well.
    """


# false warning on get_closest_marker()
# pylint: disable=abstract-method
class TopotatoItem(nodes.Item):
    """
    pytest base class for test "items" - asserts, route checks, etc.

    This is heavily pytest-specific machinery.  Dragons may be involved.  You
    should NOT ever see this class directly in a topotato test source file.
    The various assertions are subclasses of this, and instances are handed
    to pytest to do its thing.
    """

    pretty: "PrettyItem"

    _codeloc: Optional[inspect.FrameInfo]
    """
    Test source code location that resulted in the creation of this item.
    Filtered heavily to condense down useful information.
    """

    cascade_failures: ClassVar[SkipMode] = SkipMode.SkipThis
    """
    Refer to :py:class:`SkipMode`.  Normal test items derived from
    :py:class:`.assertions.TopotatoAssertion` or
    :py:class:`.assertions.TopotatoModifier` needn't worry about this since
    those two set it correctly.
    """

    nodeid_children_sep: Optional[str] = None

    _obj: "TestBase"
    """
    The test source instance which this item has resulted from, i.e. an
    instance of WhateverTestClass defined in test_something.py
    """

    cls_node: "TopotatoClass"
    """
    The pytest node created for the :py:class:`TestBase` subclass.
    """
    instance: "TopotatoNetwork"
    """
    Running network instance this item belongs to.
    """
    timeline: "Timeline"

    skipchecks: List[Callable[["TopotatoItem"], None]]
    """
    List of additional callables to check before running this test item.  The
    called functions should either return or raise a :py:class:`TopotatoSkipped`
    exception.

    Exceptions from these checks do not automatically skip other tests, only
    this test item is skipped.
    """

    posargs: ClassVar[List[str]] = []

    def __init__(self, *, name: str, parent: nodes.Node, codeloc=None, **kw):
        nodeid = None
        child_sep = getattr(parent, "nodeid_children_sep", None)
        if child_sep:
            nodeid = parent.nodeid + child_sep + name

        super().__init__(parent=parent, name=name, nodeid=nodeid, **kw)
        self.skipchecks = []
        self._codeloc = codeloc

        self.cls_node = cast(TopotatoClass, self.getparent(TopotatoClass))
        if self.cls_node is None:
            raise RuntimeError("TopotatoItem without parent TopotatoClass?!")
        self._obj = self.cls_node.obj

    @classmethod
    def from_parent(
        cls: Type["TopotatoItem"], parent: nodes.Node, *args, **kw
    ) -> "TopotatoItem":
        if len(args) > len(cls.posargs):
            raise TopotatoUnhandledArgs(f"too many positional args for {cls.__name__}")

        for i, arg in enumerate(args):
            if cls.posargs[i] in kw:
                raise TopotatoUnhandledArgs(
                    f"duplicate argument {cls.posargs[i]!r} for {cls.__name__}"
                )
            kw[cls.posargs[i]] = arg

        return super().from_parent(parent=parent, **kw)

    @classmethod
    @GeneratorWrapper.apply
    @skiptrace
    def make(
        cls: Type["TopotatoItem"], *args, **kwargs
    ) -> Generator[Optional["TopotatoItem"], Tuple["TopotatoClass", str], None]:
        """
        Core plumbing to create an actual test item.

        All topotato tests should be the result of the main test source file
        invoking a whole bunch of::

           yield from SomeSubclass.make(...)

        Note that this is a generator and calling it without a yield from won't
        do anything useful.  args/kwargs are passed along to the actual test.
        """

        callers = skiptrace.get_callers()
        assert callers

        # ordering of test items is based on caller here, so we need to go
        # with the topmost or we end up reordering things in a weird way.
        location = ""
        caller = None
        while callers:
            module = inspect.getmodule(callers[0].frame)
            if not module or module.__name__.startswith("topotato."):
                break
            caller = callers.pop(0)
            location = "#%d%s" % (caller.lineno, location)
        del callers

        try:
            ig = yield from cls._make(location, caller, *args, **kwargs)
            return ig
        except TopotatoUnhandledArgs as e:
            # shorten backtrace by re-raising
            raise TopotatoUnhandledArgs(*e.args) from None

    @skiptrace
    @classmethod
    def _make(
        cls: Type["TopotatoItem"], namesuffix, codeloc, *args, **kwargs
    ) -> Generator[Optional["TopotatoItem"], Tuple["TopotatoClass", str], ItemGroup]:
        parent, _ = yield None
        self = cls.from_parent(
            parent, name=namesuffix, codeloc=codeloc, *args, **kwargs
        )
        yield self

        return ItemGroup([self])

    @pytest.hookimpl(tryfirst=True)
    @staticmethod
    def pytest_pycollect_makeitem(collector, name, obj):
        """
        Redirect pytest item creation on objects that have a
        ``_topotato_makeitem`` method to call that instead.  This is the "core"
        pytest hook-in that makes all the other topotato objects appear.
        """
        if hasattr(obj, "_topotato_makeitem"):
            # pylint: disable=protected-access
            if inspect.ismethod(obj._topotato_makeitem):
                _logger.debug("_topotato_makeitem(%r, %r, %r)", collector, name, obj)
                return obj._topotato_makeitem(collector, name, obj)
            _logger.debug("%r._topotato_makeitem: not a method", obj)
        return None

    def setup(self):
        """
        Called by pytest in the "setup" stage (pytest_runtest_setup)
        """
        super().setup()

        fn = self.getparent(TopotatoFunction)
        if fn and not fn.started_ts:
            # pylint: disable=attribute-defined-outside-init
            fn.started_ts = time.time()

        with _SkipMgr(self):
            self.instance = self.cls_node.netinst
            self.timeline = self.instance.timeline

    # pylint: disable=unused-argument
    @pytest.hookimpl()
    @staticmethod
    def pytest_topotato_run(item: "TopotatoItem", testfunc: Callable):
        testfunc()

    @endtrace
    @skiptrace
    def runtest(self):
        """
        Called by pytest in the "call" stage (pytest_runtest_call)
        """
        with _SkipMgr(self):
            for check in self.skipchecks:
                check(self)

            self.session.config.hook.pytest_topotato_run(item=self, testfunc=self)

    def reportinfo(self):  # -> Tuple[Union[py.path.local, str], int, str]:
        """
        Specialize pytest's location information for this test.

        Return the location the test item was yield-generated from, rather
        than some place deep in the topotato logic.
        """
        if self._codeloc is None:
            return "???", 0, self.name

        fspath = self._codeloc.filename
        lineno = self._codeloc.lineno
        return fspath, lineno, self.name

    # pytest < 7.4
    def _prunetraceback(self, excinfo: "ExceptionInfo[BaseException]") -> None:
        excinfo.traceback = self._traceback_filter(excinfo)

    # pytest >= 7.4
    def _traceback_filter(self, excinfo: "ExceptionInfo[BaseException]") -> "Traceback":
        if self.config.getoption("fulltrace", False):
            return excinfo.traceback

        tb = excinfo.traceback
        newtb: List["TracebackEntry"] = []
        for entry in reversed(tb):
            # pylint: disable=protected-access
            if entry._rawentry.tb_frame.f_code in endtrace:
                break
            if entry._rawentry.tb_frame.f_code in skiptrace:
                continue
            if newtb:
                if hasattr(entry, "with_repr_style"):
                    entry = entry.with_repr_style("short")
                elif hasattr(entry, "set_repr_style"):
                    entry.set_repr_style("short")
            newtb.insert(0, entry)

        return type(excinfo.traceback)(newtb)

    def _repr_failure(self, excinfo, style=None):
        reprcls = getattr(excinfo.value, "TopotatoRepr", None)
        if reprcls:
            return reprcls(excinfo)

        if getattr(self, "_codeloc", None) is None:
            return super().repr_failure(excinfo)

        if isinstance(excinfo.value, _pytest.fixtures.FixtureLookupError):
            return excinfo.value.formatrepr()

        class FakeTraceback:
            def __init__(self, codeloc, nexttb):
                self.tb_frame = codeloc.frame
                self.tb_lineno = codeloc.lineno
                self.tb_next = nexttb

        # pylint: disable=protected-access
        ftb = cast(
            "TracebackType",
            FakeTraceback(self._codeloc, excinfo.traceback[0]._rawentry),
        )
        excinfo.traceback.insert(0, _pytest._code.code.TracebackEntry(ftb))

        if self.config.getoption("fulltrace", False):
            style = "long"
        elif isinstance(excinfo.value, TopotatoFail):
            excinfo.traceback = _pytest._code.Traceback([excinfo.traceback[0]])
            style = "long"
        else:
            tb = _pytest._code.Traceback([excinfo.traceback[-1]])
            excinfo.traceback = excinfo.traceback.filter(_pytest._code.filter_traceback)
            if len(excinfo.traceback) == 0:
                excinfo.traceback = tb
            if style in ["auto", None]:
                style = "long"

        # see comment in pytest
        Path = _pytest.pathlib.Path
        try:
            abspath = Path(os.getcwd()) != Path(str(self.config.invocation_params.dir))
        except OSError:
            abspath = True

        return excinfo.getrepr(
            funcargs=True,
            abspath=abspath,
            showlocals=self.config.getoption("showlocals", False),
            style=style,
            tbfilter=False,
            truncate_locals=True,
        )

    def repr_failure(self, excinfo, style=None):
        """
        Customize pytest's failure representation to overwrite location.

        As with reportinfo, give the location this item was yielded from
        rather than some place deep in topotato logic.
        """
        res = self._repr_failure(excinfo, style)
        self.session.config.hook.pytest_topotato_failure(
            item=self,
            excinfo=excinfo,
            excrepr=res,
            codeloc=getattr(self, "_codeloc", None),
        )
        return res


class _SkipMgr:
    """
    Simple context manager used by :py:class:`TopotatoItem` to make errors
    skip later test items on the same network.
    """

    _item: TopotatoItem

    def __init__(self, item: TopotatoItem):
        self._item = item

    def __enter__(self) -> None:
        if self._item.cascade_failures == SkipMode.DontSkip:
            return
        if self._item.cls_node.skipall:
            raise TopotatoEarlierFailSkip(
                self._item.cls_node.skipall_node
            ) from self._item.cls_node.skipall

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        tb: Optional["TracebackType"],
    ) -> None:
        if exc_value is None:
            return

        if not isinstance(exc_value, (Exception, Failed, Skipped)):
            return
        if self._item.cascade_failures in [SkipMode.DontSkip, SkipMode.SkipThis]:
            return
        if self._item.cascade_failures in [SkipMode.SkipThisAndLater] and isinstance(
            exc_value, Skipped
        ):
            return

        self._item.cls_node.skipall_node = self._item
        self._item.cls_node.skipall = exc_value


# false warning on get_closest_marker()
# pylint: disable=abstract-method
class InstanceStartup(TopotatoItem):
    """
    Test pseudo-item to start up topology.

    Includes starting tshark and checking all daemons are running.
    """

    cascade_failures = SkipMode.SkipThisAndLaterHard

    commands: OrderedDict

    def __init__(self, **kwargs):
        super().__init__(name="startup", **kwargs)

    def reportinfo(self):
        fspath, _, _ = self.cls_node.reportinfo()
        return fspath, float("-inf"), "startup"

    def setup(self):
        self.cls_node.fdstate_start = FDState()

        # this needs to happen before TopotatoItem.setup, since that accesses
        # cls_node.netinst
        with _SkipMgr(self):
            # pylint: disable=protected-access
            self.cls_node.netinst = self.cls_node.obj._setup(
                self.session, self.cls_node.nodeid
            ).prepare()
        super().setup()

    @endtrace
    @skiptrace
    def runtest(self):
        with _SkipMgr(self):
            self.cls_node.do_start()


# false warning on get_closest_marker()
# pylint: disable=abstract-method
class InstanceShutdown(TopotatoItem):
    """
    Test pseudo-item to shut down topology.

    As part of shut down, tshark is stopped / the pcap file is closed in an
    orderly fashion (otherwise you get truncated pcap files.)
    """

    # kinda irrelevant here
    cascade_failures = SkipMode.DontSkip

    def __init__(self, **kwargs):
        super().__init__(name="shutdown", **kwargs)

    def reportinfo(self):
        fspath, _, _ = self.cls_node.reportinfo()
        return fspath, float("inf"), "shutdown"

    def setup(self):
        # specifically skip shutdown only if startup failed
        if isinstance(self.cls_node.skipall_node, InstanceStartup):
            raise TopotatoEarlierFailSkip(
                self.cls_node.skipall_node
            ) from self.cls_node.skipall

        super().setup()

    def __call__(self):
        self.cls_node.do_stop(self)

        fdstate_end = FDState()
        delta = FDDelta(self.cls_node.fdstate_start, fdstate_end)

        if delta:
            _logger.error("FD leaks detected:")
            for fd in sorted(delta.closed):
                _logger.error("FD %4d closed", fd)
            for fd in sorted(delta.changed):
                _logger.error("FD %4d differs, now: %s", fd, fdinfo(fd))
            for fd in sorted(delta.opened):
                _logger.error("FD %4d opened: %s", fd, fdinfo(fd))


class TestBase:
    """
    Base class for all topotato tests.

    Everything implementing a topotato test must derive from this base.  It
    doesn't need to be direct, i.e. further subclassing is possible.
    """

    _setup: ClassVar[Type["TopotatoNetwork"]]

    @classmethod
    def _topotato_makeitem(cls, collector, name, obj):
        """
        Primary topotato pytest integration.

        topotato's pytest collection hook
        (:py:func:`topotato.pytestintegration.pytest_pycollect_makeitem`)
        checks for the existence of this method;  its existence is the initial
        entry point to the topotato pytest integration machinery.  Everything
        else happens as a result of this, because we return
        :py:class:`TopotatoClass` here, rather than the
        :py:class:`_pytest.python.Class` you would normally get from pytest.
        """
        if cls is TestBase:
            return []
        return [TopotatoClass.from_hook(obj, collector, name=name)]

    @classmethod
    def __init_subclass__(
        cls, /, topo: Optional["Network"] = None, configs=None, setup=None, **kwargs
    ):
        super().__init_subclass__(**kwargs)

        if any([topo, configs]):
            if not all([topo, configs]):
                raise RuntimeError(
                    f"{cls.__name__}: topo= and configs= must be used together"
                )
            if setup:
                raise RuntimeError(
                    f"{cls.__name__}: topo= and configs= are exclusive against setup="
                )

            class AutoSetup(TopotatoNetwork, topo=topo, params=configs):
                pass

            cls._setup = AutoSetup  # type: ignore[type-abstract]
        elif not setup:
            raise RuntimeError(
                f"{cls.__name__}: either setup=, or topo= + configs= must be used"
            )
        else:
            cls._setup = setup


class TopotatoWrapped:
    """
    Marker-type method wrapper to signal a method as topotato test.

    .. note::

       Understanding what this does is not particularly important/helpful for
       comprehending topotato as a whole, this is just necessary low-level
       Python plumbing without huge consequences.

    This is a bit more complicated than would be immediately apparent because
    we're wrapping a *method*, not a *function*.  Thing is, methods are
    initially defined as unbound functions, and then become bound methods when
    dereferenced by accessing them through an instance.

    The way Python handles this is that the method actually gets a descriptor
    object in the class, with a __get__ on it that does the method binding
    mentioned above.  So when you do ``obj.foobar``, there's an intermediate
    step through ``obj.foobar.__get__(obj, objtype)``.

    This class basically replicates that, but keeps returning instances of
    itself until you actually call the method.  The starting point is a
    decorated class definition along the lines of::

       class A:
           @TopotatoWrapped
           def something(self, args):
               pass

    After this, ``A.someting`` is an instance of TopotatoWrapped with
    :py:attr:`_wrap` set to the original (unbound) definition of ``something``
    and :py:attr:`_call` the same.

    When you start working with instances, e.g.::

       a = A()
       a.something(args)

    First, nothing happens on creating the instance.  But ``a.something`` (note
    the missing ``()``, so the function call isn't happening yet) results in
    :py:meth:`__get__` being called.  That returns a new instance of
    TopotatoWrapped with the same :py:attr:`_wrap`, but :py:attr:`_call` is
    updated to now point to the *bound* method (which we get transitively from
    the original ``__get__``.)  Finally, the function call is routed through
    :py:meth:`__call__` and passed onto the bound method.

    Ultimately, this gives us a properly working *method* wrapper that we
    can stick other things on - like :py:meth:`_topotato_makeitem`, which sets
    up topotato test items for functions annotated this way.
    """

    def __init__(self, wrap, call=None, *, kwds: Optional[Dict[str, Any]] = None):
        assert inspect.isgeneratorfunction(wrap)

        self._wrap = wrap
        self._call = call or wrap
        self.__wrapped__ = call or wrap
        self._kwds = kwds or {}

    def __get__(self, obj, objtype=None):
        return self.__class__(
            self._wrap, self._call.__get__(obj, objtype), kwds=self._kwds
        )

    def __call__(self, *args, **kwargs):
        return self._call(*args, **kwargs)

    # pylint: disable=protected-access,no-self-use
    def _topotato_makeitem(self, collector, name, obj):
        """
        topotato pytest integration.

        Refer to :py:meth:`TestBase._topotato_makeitem`, this is the method
        level equivalent of that.
        """
        return [TopotatoFunction.from_hook(obj, collector, name, **self._kwds)]


def topotatofunc(fn: Optional[Callable] = None, *, include_startup=False):
    """
    Decorator to mark methods as item-yielding test generators.

    :param bool include_startup: for event based assertions (logs, packets),
       include events that happened before the tests in this functions start
       (i.e. during startup, but possibly also during previous test functions.)

    .. todo::

       Just decorate with :py:class:`TopotatoWrapped` directly?  A class as
       decorator does look a bit weird though...
    """

    # @topotatofunc
    if fn is not None:
        return TopotatoWrapped(fn)

    # @topotatofunc(...)
    def wrap(fn: Callable):
        return TopotatoWrapped(
            fn,
            kwds={
                "include_startup": include_startup,
            },
        )

    return wrap


class TopotatoFunction(nodes.Collector, _pytest.python.PyobjMixin):
    started_ts: Optional[float] = None
    include_startup: bool

    # JUnit XML output splits node IDs by "::", which is the implicit default
    # for this.  But that make the JUnit report structure weird.  Use ":" for
    # better cosmetics.
    nodeid_children_sep = ":"

    # pylint: disable=protected-access
    @classmethod
    def from_hook(cls, obj, collector, name, include_startup=False):
        self = super().from_parent(collector, name=name)
        self._obj = obj._call
        self.include_startup = include_startup

        return self

    @skiptrace
    def collect(
        self,
    ) -> Union[
        None, nodes.Item, nodes.Collector, List[Union[nodes.Item, nodes.Collector]]
    ]:
        tcls = self.getparent(TopotatoClass)
        assert tcls is not None

        # obj contains unbound methods; get bound instead
        method = getattr(tcls.newinstance(), self.name)
        assert callable(method)

        topo = tcls.obj._setup._network

        # pylint: disable=protected-access
        argspec = inspect.getfullargspec(method._call).args[1:]
        argnames = set(argspec)

        # all possible kwargs
        all_args = {}
        all_args.update(topo.routers)
        all_args["topo"] = topo
        all_args["_"] = None

        args = {k: v for k, v in all_args.items() if k in argnames}
        with GeneratorChecks():
            return self.collect_iter(method(**args))

    @skiptrace
    def collect_iter(
        self,
        iterator: Generator[
            Union[nodes.Item, nodes.Collector],
            Optional[Tuple[nodes.Collector, str]],
            None,
        ],
    ) -> Union[
        None, nodes.Item, nodes.Collector, List[Union[nodes.Item, nodes.Collector]]
    ]:
        tests = []
        sendval = None
        try:
            while True:
                value = iterator.send(sendval)
                if value is not None:
                    _logger.debug("collect on: %r test: %r", self, value)
                    tests.append(value)
                sendval = (self, self.name)
        except StopIteration:
            pass

        return tests


# false warning on get_closest_marker()
# pylint: disable=abstract-method
class TopotatoClass(_pytest.python.Class):
    """
    Representation of a test class definition.

    :py:meth:`TestBase._topotato_makeitem` results in topotato tests getting
    one of this here rather than the regular :py:class:`_pytest.python.Class`.
    This allows us to customize behavior.
    """

    _obj: Type[TestBase]
    """
    Test class (the type).
    """

    _instance: TestBase
    """
    The actual instance of our test class.
    """

    skipall: Optional[Union[Exception, Failed, Skipped]]
    skipall_node: Optional[TopotatoItem]

    starting_ts: float
    started_ts: float
    netinst: "TopotatoNetwork"

    fdstate_start: FDState

    # pylint: disable=protected-access
    @classmethod
    def from_hook(cls, obj, collector, name):
        self = super().from_parent(collector, name=name)
        self._obj = obj
        self.skipall_node = None
        self.skipall = None

        # TODO: automatically add a bunch of markers for test requirements.
        for fixture in getattr(self._obj, "use", []):
            self.add_marker(pytest.mark.usefixtures(fixture))

        return self

    def newinstance(self):
        return self._instance

    def collect(self) -> Iterable[Union[nodes.Item, nodes.Collector]]:
        """
        Tell pytest our test items, adding startup/shutdown.

        Note that the various methods in the class are still collected using
        standard pytest logic.  However, the :py:func:`topotatofunc` decorator
        will cause methods to have a ``_topotato_makeitem`` attribute, which
        then replaces the :py:class:`_pytest.python.Function` with the
        topotato assertions defined for the test.
        """

        first = True
        # only use one instance for topotato test classes
        self._instance = self.obj()

        # WARNING: pytest 6.x <> 7.x difference - pytest 6.x inserts an
        # Instance() class here; pytest 7.x does not have that!

        for item in super().collect():
            if first:
                # super().collect() calls pytest magic functions like
                #   ._inject_setup_class_fixture() and
                #   ._inject_setup_method_fixture() and
                # let those run first and then inject ourselves after that
                yield InstanceStartup.from_parent(self)
                first = False

            yield item

        if not first:
            yield InstanceShutdown.from_parent(self)

    def do_start(self) -> None:
        self.starting_ts = time.time()

        netinst = self.netinst

        tcname = self.nodeid
        tcname = "".join(
            ch if ch in string.ascii_letters + string.digits else "_" for ch in tcname
        )
        netinst.lcov_args.extend(  # type: ignore[attr-defined]
            [
                "-t",
                tcname,
                "--exclude",
                "/usr/include/*",
                "--exclude",
                "*_clippy.c",
                "--exclude",
                "*.yang.c",
            ]
        )

        netinst.start()
        netinst.timeline.sleep(0.2)
        # netinst.status()

        failed: List[Tuple[str, str]] = []
        for rtr in netinst.network.routers.keys():
            router = netinst.routers[rtr]
            router.start_post(netinst.timeline, failed)

        if len(failed) > 0:
            netinst.timeline.sleep(0)
            if len(failed) == 1:
                rname, daemon = failed[0]
                raise TopotatoDaemonCrash(daemon=daemon, router=rname)

            routers = ",".join(set(i[0] for i in failed))
            daemons = ",".join(set(i[1] for i in failed))
            raise TopotatoDaemonCrash(daemon=daemons, router=routers)

        self.started_ts = time.time()

        for ifname, sock in netinst.scapys.items():  # type: ignore[attr-defined]
            netinst.timeline.install(LiveScapy(ifname, sock))

    @staticmethod
    def do_stop(stopitem):
        netinst = stopitem.instance

        netinst.stop()

        netinst.timeline.sleep(1, final=True)
