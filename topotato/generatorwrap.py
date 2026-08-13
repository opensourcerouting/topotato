#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2023  David Lamparter for NetDEF, Inc.
"""
Wrap generator functions & raise exceptions if a generator is never used.
"""

import functools
import traceback
import inspect
import warnings
from types import TracebackType
from typing import (
    cast,
    Callable,
    Generator,
    List,
    Optional,
    TypeVar,
    Type,
)

try:
    from typing import ParamSpec  # novermin
except ImportError:
    # python < 3.10
    # pylint: disable=unused-argument
    def ParamSpec(name, *, bound=None, covariant=False, contravariant=False):  # type: ignore
        return ...


class GeneratorChecksWarning(UserWarning):
    pass


class GeneratorsUnused(Exception):
    """
    Accumulation of :py:class:`GeneratorDeletedUnused` when caught inside of
    :py:class:`GeneratorChecks` ``with`` context.
    """

    generators: List["GeneratorWrapper"]

    def __init__(self, generators: List["GeneratorWrapper"]):
        super().__init__()
        self.generators = generators

    def __str__(self):
        items = "\n===\n".join(g._loc[-1] for g in self.generators).replace(
            "\n", "\n  "
        )
        return f'{len(self.generators)} generators were invoked but never executed (forgotten "yield from"?):\n  {items}'


class GeneratorChecks:
    """
    Context manager to track called but not iterated GeneratorWrapper.
    """

    _active: List
    """
    Calling a GeneratorWrapper-wrapped iterator adds it here, iterating over it
    removes it.  At the end of the context, this list needs to be empty or we
    raise an exception.
    """

    _ctxstack: List["GeneratorChecks"] = []

    def __init__(self):
        self._active = []

    def __enter__(self):
        GeneratorChecks._ctxstack.insert(0, self)
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        tb: Optional[TracebackType],
    ):
        if exc_type is not None:
            return

        assert GeneratorChecks._ctxstack.pop(0) == self

        if self._active:
            raise GeneratorsUnused(self._active)


P = ParamSpec("P")
TY = TypeVar("TY")
TS = TypeVar("TS")
TR = TypeVar("TR")


# pylint: disable=protected-access
class GeneratorWrapper(Generator[TY, TS, TR]):
    """
    Decorator / wrapper for generators to raise exception if it never ran.

    Use like::
        @GeneratorWrapper.apply
        def my_generator(foo):
            yield foo + 1
            yield foo - 1

    When the generator is later _called_ but not actually iterated over, it
    will register itself on the innermost :py:class:`GeneratorChecks` context.
    These should be collected like this::

        with GeneratorChecks():
            # this will result in an exception at the end of the with block
            my_generator(234)

            # this will execute normally
            for i in my_generator(123):
                print (i)
    """

    _wraps: Generator[TY, TS, TR]
    """
    Original generator object to forward __iter__ to.
    """
    _loc: List[str]
    """
    Location of call to pass to :py:class:`GeneratorDeletedUnused`, see there.
    """
    _gchk: Optional[GeneratorChecks]

    def __init__(self, wraps: Generator[TY, TS, TR], loc: List[str]):
        self._wraps = wraps
        self._loc = loc

        if GeneratorChecks._ctxstack:
            self._gchk = GeneratorChecks._ctxstack[0]
            self._gchk._active.append(self)
        else:
            self._gchk = None
            warnings.warn(
                "GeneratorWrapper-wrapped generator invoked without active GeneratorChecks",
                GeneratorChecksWarning,
            )

    def __iter__(self):
        if self._gchk:
            self._gchk._active.remove(self)
            self._gchk = None
        return self._wraps.__iter__()

    def send(self, value: TS) -> TY:
        if self._gchk:
            self._gchk._active.remove(self)
            self._gchk = None
        return self._wraps.send(value)

    def throw(self, typ, val=None, tb=None) -> TY:
        if self._gchk:
            self._gchk._active.remove(self)
            self._gchk = None
        return self._wraps.throw(typ, val, tb)

    @classmethod
    def apply(
        cls, function: Callable[P, Generator[TY, TS, TR]]
    ) -> Callable[P, Generator[TY, TS, TR]]:
        """
        Decorator to be used on generator functions.
        """
        if isinstance(function, (classmethod, staticmethod)):
            raise RuntimeError(
                "@GeneratorWrapper.apply must come after @classmethod/@staticmethod"
            )
        if not inspect.isgeneratorfunction(function):
            raise RuntimeError("@GeneratorWrapper.apply must be used on a generator")

        @functools.wraps(function)
        def wrapper(*args, **kwargs) -> Generator[TY, TS, TR]:
            f = inspect.currentframe()
            if f is None:
                loc = ["???"]
            else:
                loc = traceback.format_stack(f.f_back)
            del f
            return cast(Generator[TY, TS, TR], cls(function(*args, **kwargs), loc))

        return wrapper
