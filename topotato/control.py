#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2018-2021  David Lamparter for NetDEF, Inc.
"""
Test Control

This is named "control" because "config" refers to actual router/daemon
configs.  The code here has nothing to do with that, it controls topotato
behavior.
"""

import re
import fnmatch
import configparser
import logging
import typing
from typing import (
    cast,
    ClassVar,
    Dict,
    List,
    Mapping,
    Optional,
    Protocol,
    Type,
    TypeVar,
    Union,
    get_origin,
    get_args,
)

import pytest

if typing.TYPE_CHECKING:
    from pytest import Session


_logger = logging.getLogger(__name__)


class UnknownControlSection(KeyError):
    pass


class ControlSection:
    control: "Control"
    sections: ClassVar[Dict[str, Type["ControlSection"]]] = {}
    section_name: ClassVar[Optional[str]] = None
    items: ClassVar[Dict[str, Type]] = {}
    name: Optional[str]

    @classmethod
    def __init_subclass__(cls, /, name=None, **kwargs):
        super().__init_subclass__(**kwargs)

        cls.section_name = name
        if name:
            ControlSection.sections[name] = cls

        cls.items = dict(cls.items)
        for k, v in cls.__annotations__.items():
            if k.startswith("_"):
                continue
            cls.items[k.removesuffix("_")] = v

    @classmethod
    def dispatch(
        cls, control: "Control", name: str, items: Mapping[str, str]
    ) -> "ControlSection":
        _name = name.split(":", 1)[0]
        if _name not in cls.sections:
            raise UnknownControlSection(
                f"[{name}] is not a valid topotato control section"
            )
        return cls.sections[_name].make(control, name, items)

    @classmethod
    def make(
        cls, control: "Control", name: str, items: Mapping[str, str]
    ) -> "ControlSection":
        return cls(control, name, items)

    # pylint: disable=too-many-branches
    def __init__(self, control: "Control", name: str, items: Mapping[str, str]):
        self.control = control

        def try_type(typ, raw_value):
            try:
                return typ(raw_value)
            except TypeError:
                return None
            except ValueError:
                return None

        if ":" in name:
            self.name = name.split(":", 1)[1]
        else:
            self.name = None

        have = set()
        for k, v in self.items.items():
            raw_value = items.get(k)

            if origin := get_origin(v):
                assert origin is Union
                if raw_value is None:
                    if type(None) not in get_args(v):
                        raise ValueError(f"missing key {k!r} in [{self.section_name}]")
                    value = None
                else:
                    for typ in get_args(v):
                        value = try_type(typ, raw_value)
                        if value:
                            break
                    else:
                        raise ValueError(
                            f"invalid value for key {k!r} in [{self.section_name}]"
                        )

            else:
                value = try_type(v, raw_value)
                if value is None:
                    raise ValueError(
                        f"invalid value for key {k!r} in [{self.section_name}]"
                    )

            setattr(self, k, value)
            have.add(k)

        extraneous = set(items.keys()) - have
        if extraneous:
            raise ValueError(
                f"unexpected items in section [{self.section_name}]: {extraneous!r}"
            )


class _ControlSectionTypeDict(Protocol):
    """
    typechecking definition for Control.typed_sections
    """

    T = TypeVar("T", bound=ControlSection)

    def get(self, key: Type[T], default: List[T]) -> List[T]: ...

    def setdefault(self, key: Type[T], newitem: List[T]) -> List[T]: ...


class Control:
    """
    (File-based) Options for a topotato run.
    """

    session: "Session"
    """
    pytest session
    """

    config: configparser.ConfigParser
    """
    Raw configuration
    """

    configfiles: List[str] = []
    """
    Config files loaded for this instance; only for reference (not used later)
    """

    typed_sections: _ControlSectionTypeDict
    targets: Dict[Union[str, None], "TargetSection"]

    def __init__(self, session):
        self.session = session
        self.config = configparser.ConfigParser()
        self.configfiles = []
        self.typed_sections = cast(_ControlSectionTypeDict, {})
        self.targets = {}

    def load_configs(self, configs):
        self.configfiles.extend(configs)
        self.config.read(configs)

        for sectname in self.config.sections():
            item = ControlSection.dispatch(self, sectname, self.config[sectname])
            self.typed_sections.setdefault(type(item), []).append(item)

    @staticmethod
    @pytest.hookimpl()
    def pytest_addoption(parser):
        parser.addoption(
            "--control",
            type=str,
            default=[],
            nargs="*",
            help="topotato control file(s)",
        )

    @classmethod
    @pytest.hookimpl()
    def pytest_topotato_preenvcheck(cls, session):
        session.control = cls(session)
        session.control.load_configs(session.config.getoption("--control"))


class RexOrGlob:
    def __init__(self, pattern: str):
        self.original_pattern = pattern

        if pattern.startswith("/") and pattern.endswith("/"):
            _pattern = pattern[1:-1]
        else:
            _pattern = fnmatch.translate(pattern)

        self.regex = re.compile(pattern)

    def match(self, value: str):
        return self.regex.match(value)


class SystemSpecificSection(ControlSection, name="rule"):
    testpath: Optional[RexOrGlob]
    hostname: Optional[RexOrGlob]
    classname: Optional[RexOrGlob]

    target: Optional[str]

    def match(self, testpath: str, hostname: str, classname: str):
        if self.testpath and not self.testpath.match(testpath):
            return False
        if self.hostname and not self.hostname.match(hostname):
            return False
        if self.classname and not self.classname.match(classname):
            return False
        return True


class TargetSection(ControlSection, name="target"):
    type_: str

    _types: ClassVar[Dict[str, Type["TargetSection"]]] = {}

    @classmethod
    def __init_subclass__(cls, /, name=None, **kwargs):
        super().__init_subclass__(cls)

        if name is not None:
            cls._types[name] = cls

    @classmethod
    def make(
        cls, control: "Control", name: str, items: Mapping[str, str]
    ) -> "ControlSection":
        return cls._types[items["type"]](control, name, items)

    def __init__(self, control: "Control", name: str, items: Mapping[str, str]):
        super().__init__(control, name, items)
        control.targets[self.name] = self
