#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2018-2021  David Lamparter for NetDEF, Inc.
"""
HTML test report prettying
"""

import sys
import base64
import re
import time
import os
import math
import json
import lzma
import zlib
import tempfile
import logging
import subprocess
import pathlib
from xml.etree import ElementTree

import typing
from typing import (
    Any,
    cast,
    ClassVar,
    Dict,
    List,
    Type,
    Optional,
    BinaryIO,
)

import pytest
import docutils.core
import jinja2
import markupsafe

from . import base, assertions
from .defer import spawn
from .utils import exec_find, deindent, get_dir
from .scapy import ScapySend
from .pcapng import Sink, SectionHeader

if typing.TYPE_CHECKING:
    from .network import TopotatoNetwork


_logger = logging.getLogger(__name__)
# _pretty_session = pytest.StashKey["PrettySession"]()


def _docrender(item):
    obj = item.obj

    if obj.__doc__ is None:
        return ""
    if obj.__doc__.strip() == "":
        return ""

    docstr = deindent(obj.__doc__)
    parts = docutils.core.publish_parts(docstr, writer_name="html4")
    return parts["fragment"]


def _docrender_markup(item):
    html = _docrender(item)
    return markupsafe.Markup(f'<div class="docstring">{html}</div>')


jenv = jinja2.Environment(
    loader=jinja2.PackageLoader("topotato.pretty", "html"),
    autoescape=True,
)
jenv.filters["docrender"] = _docrender_markup


# migrate to javascript
# import urllib.parse
# from .frr import FRRConfigs
#            xref = FRRConfigs.xrefs['refs'].get(self._uid, [])
#            loc_set = {(loc['file'], loc['line']) for loc in xref}
#            if len(loc_set) == 1:
#                filename, line = loc_set.pop()
#                if self._prettysession.source_url:
#                    path = urllib.parse.urljoin(self._prettysession.source_url, filename)
#                else:
#                    path = os.path.join(FRRConfigs.srcpath, filename)
#                meta.append(html.a(self._uid, href="%s#L%d" % (path, line)))
#            else:
#                meta.append(fmt.uid(self._uid))


class PrettyExtraFile:
    filename: Optional[str]

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self, owner, name, ext, mimetype, data):
        self.owner = owner
        self.name = name
        self.ext = ext
        self.mimetype = mimetype
        self.data = data
        self.filename = None

        owner.extrafiles[name] = self

    def output(self, basepath, basename):
        self.filename = "%s_%s%s" % (basename, self.name, self.ext)

        with open(os.path.join(basepath, self.filename), "wb") as fd:
            data = self.data
            if isinstance(self.data, str):
                data = data.encode("UTF-8")
            fd.write(data)


class PrettySession:
    exec_dot: ClassVar[Optional[str]]
    prettyitems: List["PrettyItem"]

    def __init__(self, session, outdir=None, source_url=None):
        self.session = session
        self.outdir = outdir
        self.source_url = source_url
        self.prettyitems = []

        if outdir and not os.path.exists(outdir):
            os.mkdir(outdir)

    def push(self, item, call, result):
        if not isinstance(item, base.TopotatoItem):
            return

        if not hasattr(item, "pretty"):
            item.pretty = PrettyItem.make(self, item)
        item.pretty(call, result)
        self.prettyitems.append(item.pretty)

    # pylint: disable=unused-argument
    def finish(self, exitstatus):
        basedir = os.path.dirname(os.path.abspath(__file__))

        for filename in ["gcov.js", "gcov.css"]:
            with open(os.path.join(self.outdir, filename), "wb") as wrfd:
                with open(os.path.join(basedir, "html", filename), "rb") as rdfd:
                    wrfd.write(rdfd.read())

        for prettyitem in self.prettyitems:
            prettyitem.finish()

    @staticmethod
    @pytest.hookimpl()
    def pytest_addoption(parser):
        parser.addoption(
            "--reportato-dir",
            type=str,
            default=None,
            help="output directory for topotato HTML report",
        )
        parser.addoption(
            "--source-url",
            type=str,
            default=None,
            help="URL to use as base in HTML report source links",
        )

        parser.addini(
            "reportato_dir", "Default output directory for topotato HTML report"
        )

    # pylint: disable=unused-argument
    @classmethod
    @pytest.hookimpl()
    def pytest_topotato_envcheck(cls, session, result):
        cls.exec_dot = exec_find("dot")
        if cls.exec_dot is None:
            result.warning("graphviz (dot) not found; network diagrams won't be drawn.")

    @classmethod
    @pytest.hookimpl()
    def pytest_sessionstart(cls, session):
        if session.config.getoption("--collect-only"):
            return

        outdir = get_dir(session, "--reportato-dir", "reportato_dir")
        source_url = session.config.getoption("--source-url")

        # session.stash[_pretty_session] = cls(session, outdir, source_url)
        session.pretty_session = cls(session, outdir, source_url)

    @staticmethod
    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(item, call):
        outcome = yield
        report = outcome.get_result()

        # self = item.session.stash.get(_pretty_session, None)
        self = getattr(item.session, "pretty_session", None)
        if self:
            self.push(item, call, report)

    @staticmethod
    @pytest.hookimpl()
    def pytest_sessionfinish(session, exitstatus):
        # self = item.session.stash.get(_pretty_session, None)
        self = getattr(session, "pretty_session", None)
        if self:
            self.finish(exitstatus)


class PrettyInstance(list):
    template = jenv.get_template("instance.html.j2")
    extrafiles: Dict[str, "PrettyExtraFile"]

    def __init__(self, prettysession, instance):
        super().__init__()
        self.prettysession = prettysession
        self.instance = instance
        self.timed = []
        self.extrafiles = {}

    _filename_sub = re.compile(r"[^a-zA-Z0-9]")

    # pylint: disable=too-many-locals,protected-access,possibly-unused-variable,too-many-statements,too-many-branches
    def report(self):
        topotatocls = self[0].item.getparent(base.TopotatoClass)
        nodeid = topotatocls.nodeid
        basename = self._filename_sub.sub("_", nodeid)
        basepath = os.path.join(self.prettysession.outdir, basename)

        data = {
            "ts_start": getattr(topotatocls, "started_ts", None),
            "funcs": [],
            "items": [],
            "macmap": self.instance.network.macmap(),
            "configs": {},
        }

        for rtrname, rtr in self.instance.routers.items():
            config = rtr.report_state()
            if config:
                data["configs"][rtrname] = config

        items = []
        prevfunc = None

        for i, prettyitem in enumerate(self.instance.pretty):
            prettyitem.idx = i

            itembasename = "%s_%s" % (
                basename,
                self._filename_sub.sub("_", prettyitem.nodeid_rel),
            )
            for extrafile in prettyitem.files():
                extrafile.output(self.prettysession.outdir, itembasename)

            funcparent = prettyitem.item.getparent(base.TopotatoFunction)
            if funcparent is not prevfunc and funcparent is not None:
                items.append(PrettyItem.make(self.prettysession, funcparent))

                funcinfo = prettyitem.json_fill(data)
                funcinfo["start_item"] = i
                data["funcs"].append(funcinfo)

            prevfunc = funcparent

            items.append(prettyitem)
            data["items"].append(prettyitem.json_fill(data))

        del prevfunc
        del funcparent

        # remove doctype / xml / ... decls
        ElementTree.register_namespace("", "http://www.w3.org/2000/svg")
        try:
            toposvgp = ElementTree.fromstring(self[0].toposvg)
            toposvg = ElementTree.tostring(toposvgp).decode("UTF-8")
        except ElementTree.ParseError as e:
            _logger.error(
                "failed to process graphviz network diagram SVG as XML: %r", e
            )
            _logger.error("SVG data: %r", self[0].toposvg)
            toposvg = ""

        data["timed"] = items[-1]._jsdata
        if items[-1]._pdml:
            data["pdml"] = items[-1]._pdml
        # ugh...
        for k, v in items[-1]._jstoplevel.items():
            data.setdefault(k, {}).update(v)
        data_json = json.dumps(data, ensure_ascii=True).encode("ASCII")
        data_bz = base64.b64encode(zlib.compress(data_json, level=6)).decode("ASCII")

        extrafiles = self.extrafiles
        for item in self:
            extrafiles.update(item.extrafiles)

        covdata = None
        try:
            covdatafile = topotatocls.netinst.coverage_wait()
        except AttributeError:
            covdatafile = None
        if covdatafile:
            try:
                with open(covdatafile, "rb") as fd:
                    covdata = fd.read()
            except FileNotFoundError:
                # TODO: do something useful...
                pass

        if covdata:
            covdata = lzma.compress(covdata, preset=9)

            lcov = PrettyExtraFile(
                self, "lcov", ".lcov.xz", "application/octet-stream", covdata
            )
            lcov.output(self.prettysession.outdir, basename)

            basedir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

            assert lcov.filename is not None

            genhtml_cmd = [
                os.path.join(basedir, "vendor/genhtml"),
                "-q",
                "--html-prolog",
                os.path.join(basedir, "topotato/html/lcov-prolog.html"),
                "-t",
                topotatocls.nodeid,
                "--header-title",
                "topotato coverage report",
                #    "-s",
                #    "-k",
                #    "-d", "desc",
                "-o",
                basepath + ".lcovhtml",
                os.path.join(self.prettysession.outdir, lcov.filename),
            ]

            subprocess.check_call(genhtml_cmd)

            coverage_loc = repr(basename + ".lcovhtml")
        else:
            coverage_loc = "null"

        output = self.template.render(locals())

        with open("%s.html" % basepath, "wb") as fd:
            fd.write(output.encode("UTF-8"))

    @staticmethod
    def extract(html: str) -> Dict[str, Any]:
        b64_re = re.compile(r'const data = "')
        m = b64_re.search(html)

        if m is None:
            raise ValueError("input text does not contain topotato JSON block")

        b64_data = html[m.end() : html.find('"', m.end())]
        gzip_data = base64.b64decode(b64_data)
        json_data = zlib.decompress(gzip_data)
        return json.loads(json_data)


class PrettyItem:
    itemclasses: Dict[Type[base.TopotatoItem], Type["PrettyItem"]] = {}
    template = jenv.get_template("item.html.j2")

    @classmethod
    def make(cls, session, item):
        for itemcls in type(item).mro():
            if itemcls in PrettyItem.itemclasses:
                prettycls = PrettyItem.itemclasses[itemcls]
                break
        else:
            prettycls = PrettyItem

        return prettycls(session, item)

    @classmethod
    def __init_subclass__(cls, /, matches=None, **kwargs):
        super().__init_subclass__(**kwargs)
        if matches:
            PrettyItem.itemclasses[matches] = cls

    def __init__(self, prettysession, item):
        self.prettysession = prettysession
        self.item = item
        self.timed = []
        self.result = None
        self.extrafiles = {}

    def __call__(self, call, result):
        handler = getattr(self, "when_%s" % result.when, None)
        if handler:
            handler(call, result)

    def finish(self):
        pass

    # pylint: disable=no-self-use
    def files(self):
        yield from []

    def when_setup(self, call, result):
        pass

    # pylint: disable=unused-argument
    def when_call(self, call, result):
        self.result = result

    def json_fill(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not self.result:
            return {"nodeid": self.nodeid_rel}

        loc = list(self.result.location)
        if not math.isfinite(loc[1]):
            loc[1] = None

        ret = {
            "nodeid": self.nodeid_rel,
            "outcome": self.result.outcome,
            "wasxfail": getattr(self.result, "wasxfail", None),
            "location": loc,
            "duration": self.result.duration,
        }

        if self.result.longrepr:
            longrepr = self.result.longrepr
            if tohtml := getattr(longrepr, "tohtml", None):
                ret["longrepr"] = tohtml()
            if chain := getattr(longrepr, "chain", None):
                ret["chain"] = [str(erepr) for erepr, _, _ in chain]

        return ret

    # properties for HTML rendering

    @property
    def nodeid_rel(self):
        parentid = self.item.getparent(base.TopotatoClass).nodeid
        selfid = self.item.nodeid
        return selfid[len(parentid) :]


class PrettyTopotatoFunc(PrettyItem, matches=base.TopotatoFunction):
    template = jenv.get_template("item_func.html.j2")

    @property
    def obj(self):
        return self.item.obj

    def json_fill(self, data: Dict[str, Any]) -> Dict[str, Any]:
        ret = super().json_fill(data)

        ret["func_doc"] = _docrender(self.item)
        return ret


class PrettyTopotato(PrettyItem, matches=base.TopotatoItem):
    idx: Optional[int]
    instance: Optional["TopotatoNetwork"]

    def __init__(self, prettysession, item):
        super().__init__(prettysession, item)
        self.timed = []
        self.ts_end = None
        self.instance = None
        self.idx = None

    def when_call(self, call, result):
        super().when_call(call, result)

        self.ts_end = time.time()

        assert hasattr(self.item, "instance")
        self.instance = self.item.instance

        assert self.instance is not None

        if not hasattr(self.instance, "pretty"):
            self.instance.pretty = PrettyInstance(self.prettysession, self.instance)
        self.instance.pretty.append(self)

    def json_fill(self, data: Dict[str, Any]) -> Dict[str, Any]:
        ret = super().json_fill(data)
        ret["idx"] = self.idx
        ret["ts_end"] = self.ts_end
        return ret


class PrettyStartup(PrettyTopotato, matches=base.InstanceStartup):
    toposvg: bytes

    def files(self):
        assert self.instance is not None

        dot = self.instance.network.dot()
        yield PrettyExtraFile(self, "dotfile", ".dot", "text/plain; charset=utf-8", dot)

        if self.prettysession.exec_dot:
            # pylint: disable=consider-using-with
            graphviz = subprocess.Popen(
                [self.prettysession.exec_dot, "-Tsvg", "-o/dev/stdout"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
            self.toposvg, _ = graphviz.communicate(dot.encode("UTF-8"))
            # sigh.
            self.toposvg = self.toposvg.replace(
                b'"Inconsolata Semi-Condensed"', b'"Inconsolata Semi Condensed"'
            )

            yield PrettyExtraFile(
                self, "dotfilesvg", ".svg", "image/svg+xml", self.toposvg
            )
        else:
            self.toposvg = b""


class PrettyShutdown(PrettyTopotato, matches=base.InstanceShutdown):
    _pcap: bytes
    _pdml: str
    _jsdata: List
    _jstoplevel: Dict
    _report_task = None

    def when_call(self, call, result):
        super().when_call(call, result)
        self._report_task = spawn(self._report)

    def finish(self):
        if self._report_task is not None:
            self._report_task.join()
            self._report_task = None

    def _report(self):
        assert self.instance is not None

        # FIXME: flush scapy sockets / timeline(final=True)!

        # TODO: move this to TopotatoClass?
        with tempfile.NamedTemporaryFile(prefix="topotato", suffix=".pcapng") as fd:
            pcapng = Sink(cast(BinaryIO, fd), "=")

            shdr = SectionHeader()
            pcapng.write(shdr)

            jsdata, jstoplevel = self.instance.timeline.serialize(pcapng)
            pcapng.flush()

            jstoplevel["ifnames2dot"] = {
                k: v.dotname for k, v in self.instance.ifnames.items()
            }

            fd.seek(0)
            self._pcap = fd.read()

            with subprocess.Popen(
                ["tshark", "-q", "-r", fd.name, "-T", "pdml"], stdout=subprocess.PIPE
            ) as tshark:
                pdml, _ = tshark.communicate()

            ElementTree.register_namespace("", "")
            pdmltree = ElementTree.fromstring(pdml)
            # PDML decode for log messages bloats the HTML report, but they
            # need to be included so the frame numbers are consistent.  remove
            # them here.
            i = 0
            while i < len(pdmltree):
                elem = pdmltree[i]
                if (
                    elem.find(
                        "proto[@name='frame']/field[@name='frame.protocols'][@show='systemd_journal']"
                    )
                    is not None
                ):
                    pdmltree.remove(elem)
                else:
                    i += 1
            pdml = ElementTree.tostring(pdmltree)

            self._pdml = pdml.decode("UTF-8")
            self._jsdata = jsdata
            self._jstoplevel = jstoplevel

        self.instance.pretty.report()

    def files(self):
        if self._pcap:
            yield PrettyExtraFile(
                self, "packets", ".pcapng", "application/octet-stream", self._pcap
            )


class PrettyVtysh(PrettyTopotato, matches=assertions.AssertVtysh):
    template = jenv.get_template("item_vtysh.html.j2")

    def json_fill(self, data: Dict[str, Any]) -> Dict[str, Any]:
        ret = super().json_fill(data)

        ret["vtysh_command"] = self.item.command
        if self.item.compare:
            ret["vtysh_compare"] = self.item.compare
        return ret


class PrettyScapy(PrettyTopotato, matches=ScapySend):
    template = jenv.get_template("item_scapy.html.j2")

    def json_fill(self, data: Dict[str, Any]) -> Dict[str, Any]:
        ret = super().json_fill(data)

        # pylint: disable=protected-access
        ret["scapy_summary"] = self.item._pkt.summary()
        ret["scapy_dump"] = self.item._pkt.show(dump=True)
        return ret


def _makeindex(args):
    def load(inpath, outpath):
        with open(inpath, "r", encoding="UTF-8") as fd:
            html = fd.read()
        try:
            data = PrettyInstance.extract(html)
        except ValueError:
            return None

        summary: Dict[str, int] = {}
        for item in data["items"]:
            summary[item["outcome"]] = summary.get(item["outcome"], 0) + 1

        return {
            "inpath": inpath,
            "relpath": inpath.relative_to(outpath.parent),
            "data": data,
            "summary": summary,
        }

    if len(args) < 2:
        sys.stderr.write(
            "usage: python3 -m topotato.pretty makeindex OUTNAME INPUTS...\n"
        )
        sys.exit(2)

    template = jenv.get_template("index.html.j2")

    out = pathlib.Path(args.pop(0))

    fileitems = []
    for source in args:
        source = pathlib.Path(source)
        if source.is_dir():
            for basepath, _, files in os.walk(source):
                basepathobj = pathlib.Path(basepath)
                for file in sorted(files):
                    if file.endswith(".html"):
                        fileitems.append(load(basepathobj / file, out))
        else:
            fileitems.append(load(source, out))

    fileitems = [i for i in fileitems if i is not None]
    with open(out, "w", encoding="UTF-8") as fd:
        fd.write(template.render({"fileitems": fileitems}))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("please specify an operation as commandline arg\n")
        sys.exit(2)

    if sys.argv[1] == "makeindex":
        _makeindex(sys.argv[2:])
    else:
        sys.stderr.write(f"unknown operation {sys.argv[1]!r}\n")
        sys.exit(2)
