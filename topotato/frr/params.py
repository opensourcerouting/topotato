#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2018-2021  David Lamparter for NetDEF, Inc.
"""
Parameters (i.e. configs) for an FRR router.
"""

import logging
import typing
import re
from typing import (
    Any,
    ClassVar,
    Collection,
    Dict,
    List,
    Optional,
    Union,
)

from ..network import (
    TopotatoNetwork,
    TopotatoParams,
)
from .core import (
    FRRSetup,
    FRRRouterNS,
    TargetFRRSection,
)
from ..exceptions import (
    TopotatoSkipped,
)
from ..control import (
    SystemSpecificSection,
)
from .templating import TemplateUtils, jenv

if typing.TYPE_CHECKING:
    from .. import toponom
    from ..types import ISession


_logger = logging.getLogger(__name__)


class FRRRequirementNotMet(TopotatoSkipped):
    """
    FRR is missing some feature necessary for this test.
    """


# pylint: disable=too-many-ancestors
class FRRParams(TopotatoParams):
    """
    Subclasses of this class collect FRR configs for one or more routers.

    .. attention::
       The same subclass can be used for more than one router.  More than one
       instance will exist in that case, with the router name passed in to
       :py:meth:`__init__`, which allows the class to pick out the correct
       configs.

    Configurations are given as class members named by the daemon::

       class MyFRRParams(FRRParams):
           zebra = "zebra config"
           ospfd = "ospfd config"

    Each of these members is compiled as a jinja2 template.
    """

    templates: ClassVar[Dict[str, Any]]
    """
    The jinja2 config templates are compiled immediately when the class is
    defined, in :py:meth:`__init_subclass__`.  This has the benefit of
    reporting fundamental template errors right then and there.  The compiled
    templates are stored here and later rendered on instance creation.
    """

    daemon_rtrs: ClassVar[Dict[str, Optional[List[str]]]]

    modules: ClassVar[Dict[str, List[str]]]

    topology: "toponom.Network"
    topo_router: "toponom.Router"
    daemons: Collection[str]
    configs: Dict[str, str]

    def __init__(self, instance: TopotatoNetwork, name: str):
        super().__init__(instance, name)
        self.frr = instance.session.frr
        self.topology = instance.network
        self.topo_router = self.topology.router(name)
        self.configs = {}

        if self.modules:
            allmods: set[str] = set()
            for dm in self.modules.values():
                allmods.update(m.split(":", 1)[0] for m in dm)
            missing = allmods - set(self.frr.modmap.keys())
            if missing:
                raise FRRRequirementNotMet(f"missing modules: {missing!r}")

        self.requirements()

        topo = self.topology
        router = self.topo_router
        routers = list(topo.routers.keys())
        rtrmap = {rname: topo.router(rname) for rname in routers}

        for daemon, template in self.templates.items():
            if name in (self.daemon_rtrs[daemon] or [name]):
                self.configs[daemon] = template.render(
                    daemon=daemon,
                    router=router,
                    routers=rtrmap,
                    topo=topo,
                    frr=TemplateUtils(router, daemon, self),
                )

        # TODO: rework mgmtd integration, particularly for supporting older
        # FRR versions
        if self.configs and "mgmtd" not in self.configs:
            self.configs["mgmtd"] = ""

        self.daemons = list(d for d in FRRSetup.daemons_all if d in self.configs)

    def instantiate(self) -> TopotatoNetwork.RouterNS:
        target: Optional[TargetFRRSection] = None
        session: ISession = self.instance.session

        for rule in session.control.typed_sections.get(SystemSpecificSection, []):
            applies = rule.match(
                self.instance.nodeid, self.name, self.__class__.__name__
            )
            if not applies:
                continue
            if rule.target:
                t = session.control.targets[rule.target]
                if not isinstance(t, TargetFRRSection):
                    _logger.error(
                        "router %r: rule %r references non-FRR target %r",
                        self.name,
                        rule.name,
                        t,
                    )
                    continue
                target = t
                _logger.info(
                    "router %r: rule %r applies using target %r",
                    self.name,
                    rule.name,
                    t,
                )
            else:
                _logger.info(
                    "router %r: rule %r applies but has no effect", self.name, rule.name
                )

        if target:
            return target.instantiate(self.instance, self.name, self)

        # pylint: disable=abstract-class-instantiated
        return FRRRouterNS(self.instance, self.name, self.frr, self)  # type: ignore[abstract]

    def require_defun(
        self, cmd: str, contains: Optional[Union[str, re.Pattern]] = None
    ) -> None:
        """
        Check that a particular CLI command exists in this FRR version, for
        use in :py:meth:`requirements`.  Commands are looked up in FRR's
        ``frr.xref`` build output.

        :param cmd: Name of the command as defined in the C source, i.e.
            second argument to `DEFUN` macro.  Generally ends in ``_cmd``.
        :param contains: String that must appear in the command's syntax
            definition (use if some new option is added to an existing
            command.)
        :raises FRRRequirementNotMet: if the command is not found or does not
            contain the string.  This causes the test to be skipped, but can
            be caught (e.g. if there are multiple alternatives to check.)
        """
        defun = (self.frr.xrefs or {}).get("cli", {}).get(cmd)
        if defun is None:
            raise FRRRequirementNotMet(f"missing DEFUN {cmd!r}")
        if contains is not None:
            if not isinstance(contains, re.Pattern):
                contains = re.compile(re.escape(contains))
            for on_daemon in defun.values():
                if not contains.search(on_daemon["string"]):
                    raise FRRRequirementNotMet(
                        f"DEFUN {cmd!r} does not contain {contains!r}"
                    )

    def has_defun(self, cmd: str, contains: Optional[str] = None) -> bool:
        """
        Wrap :py:meth:`require_defun`, but return a bool rather than throwing
        an exception.

        This wrapper is "the other way around" because the exception thrown
        above contains additional information beyond what can be conveyed in a
        ``bool``.
        """
        try:
            self.require_defun(cmd, contains)
            return True
        except FRRRequirementNotMet:
            return False

    def has_logmsg(self, msgid: str) -> bool:
        """
        Check that a log message exists in this FRR version by looking up its
        unique ID in ``frr.xref``.

        :param msgid: ID (``XXXXX-XXXXX``) of the log message to look for.
        """
        return msgid in (self.frr.xrefs or {}).get("refs", {})

    def require_logmsg(self, msgid: str) -> None:
        """
        Wrap :py:meth:`has_logmsg` and raise exception if given log message
        does not exist in this FRR version.

        :param msgid: ID (``XXXXX-XXXXX``) of the log message to look for.
        :raises FRRRequirementNotMet: if the log message is not found.  This
            causes the test to be skipped, but can be caught (e.g. if there
            are multiple alternatives to check.)
        """
        if not self.has_logmsg(msgid):
            raise FRRRequirementNotMet(f"missing log message {msgid!r}")

    def requirements(self) -> None:
        """
        Override this method to perform FRR requirements checks.  Should
        primarily call :py:meth:`require_logmsg` and :py:meth:`require_defun`.
        """

    def want_daemon(self, daemon: str) -> bool:
        return daemon in self.configs

    def eval(self, text: str):
        """
        Helper used for the "compare" text for vtysh to fill in bits

        TBD: Replace with straight-up jinja2?
        """
        expr = jenv.compile_expression(text)
        return expr(router=self.topo_router)

    # pylint: disable=arguments-differ
    @classmethod
    def __init_subclass__(cls, /, **kwargs):
        """
        Prepare / parse the templates

        (Modifies the class itself, not much point in doing anything else)
        """
        super().__init_subclass__(**kwargs)

        cls.templates = {}
        cls.daemon_rtrs = {}
        cls.modules = getattr(cls, "modules", {})

        all_routers = getattr(cls, "routers", None)

        for daemon in FRRSetup.daemons_all:
            if not hasattr(cls, daemon):
                continue

            cls.templates[daemon] = jenv.compile_class_attr(cls, daemon)
            cls.daemon_rtrs[daemon] = getattr(cls, "%s_routers" % daemon, all_routers)

            mods = getattr(cls, daemon + "_modules", None)
            if mods:
                l = cls.modules.setdefault(daemon, [])
                l.extend(mods)

        return cls
