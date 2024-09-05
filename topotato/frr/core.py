#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2018-2021  David Lamparter for NetDEF, Inc.
"""
FRR handling - turns a toponom router into an FRR router
"""

import importlib
import json
import logging
import os
import pwd
import re
import shlex
import signal
import socket
import struct
import sys
import time
import typing
from typing import (
    cast,
    Any,
    ClassVar,
    Collection,
    Dict,
    FrozenSet,
    Generator,
    List,
    Mapping,
    Optional,
    Tuple,
)
from typing_extensions import Protocol

import pytest

try:
    from deprecated import deprecated
except ImportError:

    def deprecated(fn):  # type: ignore
        return fn


from ..defer import subprocess
from ..utils import get_dir, EnvcheckResult
from ..timeline import Timeline, MiniPollee, TimedElement
from .livelog import LiveLog, LogMessage
from ..exceptions import (
    TopotatoDaemonCrash,
    TopotatoDaemonStartFail,
    TopotatoDaemonStopFail,
    TopotatoFail,
)
from ..pcapng import Context
from ..network import TopotatoNetwork
from ..topobase import CallableNS
from .exceptions import FRRStartupVtyshConfigFail

if typing.TYPE_CHECKING:
    from .. import toponom
    from ..types import ISession


_logger = logging.getLogger(__name__)


class FRRSetupError(EnvironmentError):
    pass


class FRRSetup:
    """
    Encapsulation of an FRR build.

    This grabs all the necessary information about the FRR build to use,
    generally given with ``--frr-builddir`` on the pytest command line.  In
    theory multiple instances of this can exist, but for the time being there
    is only one, and you can find it in pytest's session object as
    ``session.frr``.
    """

    daemons_all: ClassVar[List[str]] = []
    """
    List of FRR daemons topotato knows about.  The daemons available are a
    subset of this, determined by reading ``Makefile`` from the FRR build.
    """
    daemons_all.extend("zebra staticd mgmtd".split())
    daemons_all.extend("bgpd ripd ripngd ospfd ospf6d isisd fabricd babeld".split())
    daemons_all.extend("eigrpd pimd pim6d ldpd nhrpd sharpd pathd pbrd".split())
    daemons_all.extend("bfdd vrrpd".split())

    daemons_mgmtd: ClassVar[FrozenSet[str]] = frozenset(
        "staticd ripd ripngd zebra".split()
    )
    """
    Daemons that get their config through mgmtd.
    """

    frrpath: str
    """
    Path to the build directory (note this is not an install in e.g. /usr)
    """
    srcpath: str
    """
    Path to sources, same as :py:attr:`frrpath` except for out-of-tree builds.
    """

    daemons: List[str]
    """
    Which daemons are available in this build, in order of startup.
    """
    binmap: Dict[str, str]
    """
    Daemon name to executable mapping
    """
    makevars: Mapping[str, str]
    """
    All the variables defined in ``Makefile``, to look up how the build was
    configured.
    """
    frrcred: pwd.struct_passwd
    """
    UID/GID that FRR was configured at build time to run under.
    """
    xrefs: Optional[Dict[Any, Any]] = None
    """
    xrefs (Log message / CLI / ...) for this FRR build.
    """

    confpath = "/etc/frr"
    """
    Configuration path FRR was configured at build time for.

    Note while daemon config paths can be overridden at daemon start,
    ``vtysh.conf`` is always in this location (since it has PAM config, which
    is mildly security relevant.)
    """

    @staticmethod
    @pytest.hookimpl()
    def pytest_addoption(parser):
        parser.addoption(
            "--frr-builddir",
            type=str,
            default=None,
            help="FRR build directory (overrides frr_builddir pytest.ini option)",
        )

        parser.addini(
            "frr_builddir",
            "FRR build directory (normally same as source, but out-of-tree is supported)",
            default="../frr",
        )

    @classmethod
    @pytest.hookimpl()
    def pytest_topotato_envcheck(cls, session: "ISession", result: EnvcheckResult):
        frrpath = get_dir(session, "--frr-builddir", "frr_builddir")

        session.frr = cls(frrpath, result)

    def __init__(self, frrpath: str, result: EnvcheckResult):
        """
        Grab setup information about a FRR build from frrpath.

        Fills in all the fields on this instance.
        """
        self.frrpath = os.path.abspath(frrpath)

        _logger.debug("FRR build directory: %r", frrpath)

        self._source_locate()
        self._env_check(result)
        self._daemons_setup(result)
        self._xrefs_load()

    def _source_locate(self):
        try:
            with open(os.path.join(self.frrpath, "Makefile"), encoding="utf-8") as fd:
                makefile = fd.read()
        except FileNotFoundError as exc:
            raise FRRSetupError(
                "%r does not seem to be a FRR build directory, did you run ./configure && make?"
                % self.frrpath
            ) from exc

        srcdirm = re.search(r"^top_srcdir\s*=\s*(.*)$", makefile, re.M)
        if srcdirm is None:
            raise FRRSetupError("cannot identify source directory for %r")

        self.srcpath = os.path.abspath(os.path.join(self.frrpath, srcdirm.group(1)))
        _logger.debug("FRR source directory: %r", self.srcpath)

        oldpath = sys.path[:]
        sys.path.append(os.path.join(self.srcpath, "python"))
        makevarmod = importlib.import_module("makevars")
        sys.path = oldpath

        self.makevars = makevarmod.MakeReVars(makefile)  # type: ignore

    def _env_check(self, result: EnvcheckResult):
        try:
            self.frrcred = pwd.getpwnam(self.makevars["enable_user"])
        except KeyError as e:
            result.error("FRR configured to use a non-existing user (%r)" % e)

        if self.makevars["sysconfdir"] not in (
            self.confpath,
            os.path.dirname(self.confpath),
        ):
            result.error(
                "FRR configured with --sysconfdir=%r, must be %r or %r for topotato"
                % (
                    self.makevars["sysconfdir"],
                    self.confpath,
                    os.path.dirname(self.confpath),
                )
            )
        if not os.path.isdir(self.confpath):
            result.error(
                "FRR config directory %r does not exist or is not a directory"
                % self.confpath
            )

    def _daemons_setup(self, result: EnvcheckResult):
        in_topotato = set(self.daemons_all)
        self.daemons = list(sorted(self.makevars["vtysh_daemons"].split()))
        missing = set(self.daemons) - in_topotato
        for daemon in missing:
            _logger.warning(
                "daemon %s missing from FRRConfigs.daemons, please add!", daemon
            )

        # this determines startup order
        self.daemons.remove("zebra")
        self.daemons.remove("staticd")
        self.daemons.insert(0, "zebra")
        self.daemons.insert(1, "staticd")
        if "mgmtd" in self.daemons:
            self.daemons.remove("mgmtd")
        self.daemons.insert(0, "mgmtd")

        _logger.info("FRR daemons: %s", ", ".join(self.daemons))

        notbuilt = set()
        self.binmap = {}
        buildprogs = []
        buildprogs.extend(self.makevars["sbin_PROGRAMS"].split())
        buildprogs.extend(self.makevars["noinst_PROGRAMS"].split())
        for name in buildprogs:
            _, daemon = name.rsplit("/", 1)
            if daemon not in self.daemons:
                _logger.debug("ignoring target %r", name)
            else:
                _logger.debug("%s => %s", daemon, name)
                if not os.path.exists(os.path.join(self.frrpath, name)):
                    result.warning("daemon %r enabled but not built?" % daemon)
                    notbuilt.add(daemon)
                else:
                    self.binmap[daemon] = name

        disabled = set(self.daemons) - set(self.binmap.keys()) - notbuilt
        for daemon in sorted(disabled):
            result.warning("daemon %r not enabled in configure, skipping" % daemon)

    def _xrefs_load(self):
        xrefpath = os.path.join(self.frrpath, "frr.xref")
        if os.path.exists(xrefpath):
            with open(xrefpath, "r", encoding="utf-8") as fd:
                self.xrefs = json.load(fd)


class _FRRConfigProtocol(Protocol):
    frr: FRRSetup
    daemons: Collection[str]

    def want_daemon(self, daemon: str) -> bool: ...


class TimedVtysh(TimedElement):
    """
    Record output from an FRR vtysh invocation.

    This creates the appropriate wrapping for vtysh output to go into the
    :py:class:`Timeline`.

    One instance of this class represents only one vtysh command, if executing
    multiple commands in one go they each receive their own object.
    """

    rtrname: str
    daemon: str

    cmd: str
    """vtysh command that was executed.  Whitespace is stripped."""

    retcode: int
    """
    vtysh return code.

    .. todo::

       wrap ``CMD_*`` enum values from ``command.h``.
    """

    text: str
    """command output.  Whitespace is NOT stripped."""

    last: bool
    """
    Set if this command is the last of a multi-command batch.

    This is used to know when to stop running the Timeline event poller.
    """

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        ts: float,
        rtrname: str,
        daemon: str,
        cmd: str,
        retcode: int,
        text: str,
        last: bool,
    ):
        super().__init__()
        self._ts = ts
        self.rtrname = rtrname
        self.daemon = daemon
        self.cmd = cmd
        self.retcode = retcode
        self.text = text
        self.last = last

    @property
    def ts(self):
        return (self._ts, 0)

    def serialize(self, context: Context):
        jsdata = {
            "type": "vtysh",
            "router": self.rtrname,
            "daemon": self.daemon,
            "command": self.cmd,
            "retcode": self.retcode,
            "text": self.text,
        }
        return (jsdata, None)


class VtyshPoll(MiniPollee):
    """
    vtysh read poll event handler.

    Instances of this class are dynamically added (and removed) from the
    :py:class:`Timeline` event poll list while commands are executed.

    This also handles sending the next command when the previous one is done.
    """

    rtrname: str
    daemon: str

    _cur_cmd: Optional[str]
    _cur_out: Optional[bytes]

    def __init__(self, rtrname: str, daemon: str, sock: socket.socket, cmds: List[str]):
        self.rtrname = rtrname
        self.daemon = daemon
        self._sock = sock
        self._cmds = cmds
        self._cur_cmd = None
        self._cur_out = None

    def send_cmd(self):
        assert self._cur_cmd is None

        if not self._cmds:
            return

        self._cur_cmd = cmd = self._cmds.pop(0)
        self._cur_out = b""

        self._sock.setblocking(True)
        self._sock.sendall(cmd.strip().encode("UTF-8") + b"\0")
        self._sock.setblocking(False)

    def fileno(self) -> Optional[int]:
        return self._sock.fileno()

    def readable(self) -> Generator[TimedElement, None, None]:
        # TODO: timeout? socket close?
        assert self._cur_cmd is not None
        assert self._cur_out is not None

        self._cur_out += self._sock.recv(4096)

        if len(self._cur_out) >= 4 and self._cur_out[-4:-1] == b"\0\0\0":
            rc = self._cur_out[-1]
            raw = self._cur_out[:-4]
            text = raw.decode("UTF-8").replace("\r\n", "\n")

            # accept a few more non-error return codes?
            last = rc != 0 or not self._cmds

            yield TimedVtysh(
                time.time(), self.rtrname, self.daemon, self._cur_cmd, rc, text, last
            )

            self._cur_cmd = None
            self._cur_out = None

            if not last:
                self.send_cmd()


class FRRInvalidConfigFail(TopotatoFail):
    def __init__(self, router: str, daemon: str, errmsg: str):
        self.router = router
        self.daemon = daemon
        self.errmsg = errmsg
        super().__init__()

    def __str__(self):
        return f"{self.router}/{self.daemon}: {self.errmsg}"


# pylint: disable=too-many-ancestors,too-many-instance-attributes
class FRRRouterNS(TopotatoNetwork.RouterNS, CallableNS):
    """
    Add a bunch of FRR daemons on top of an (OS-dependent) RouterNS
    """

    _configs: _FRRConfigProtocol
    instance: TopotatoNetwork
    frr: FRRSetup
    logfiles: Dict[str, str]
    pids: Dict[str, int]
    rundir: Optional[str]
    varlibdir: Optional[str]
    rtrcfg: Dict[str, str]
    livelogs: Dict[str, LiveLog]
    frrconfpath: str
    merged_cfg: str

    def __init__(
        self, instance: TopotatoNetwork, name: str, configs: _FRRConfigProtocol
    ):
        super().__init__(instance, name)
        self._configs = configs
        self.frr = configs.frr
        self.logfiles = {}
        self.livelogs = {}
        self.pids = {}
        self.rundir = None
        self.rtrcfg = {}

    @property
    @deprecated
    def configs(self):
        return self._configs

    def _getlogfd(self, daemon):
        if daemon not in self.livelogs:
            self.livelogs[daemon] = LiveLog(self, daemon)
            self.instance.timeline.install(self.livelogs[daemon])
            self.instance.timeline.observe(self.livelogs[daemon], self._logwatch)
        return self.livelogs[daemon].wrfd

    def _logwatch(self, evt: TimedElement):
        if not isinstance(evt, LogMessage):
            return

        logmsg = cast(LogMessage, evt)
        # FIXME: this will no longer trigger with integrated config
        # as the error is reported by vtysh (in _load_config) instead
        if logmsg.uid == "SHWNK-NWT5S":
            raise FRRInvalidConfigFail(logmsg.router.name, logmsg.daemon, logmsg.text)

    def interactive_state(self) -> Dict[str, Any]:
        return {
            "rundir": self.rundir,
            "frrpath": self.frr.frrpath,
        }

    def report_state(self) -> Dict[str, Any]:
        # TODO: merge interactive_state / report_state?
        return self.rtrcfg

    def xrefs(self):
        return self.frr.xrefs

    def start(self):
        super().start()

        frrcred = self.frr.frrcred

        # bit of a hack
        self.rundir = rundir = self.tempfile("run")
        os.mkdir(rundir)
        os.chown(rundir, frrcred.pw_uid, frrcred.pw_gid)
        self.check_call(["mount", "--bind", rundir, "/run"])
        self.check_call(["mount", "--bind", rundir, "/var/run"])

        self.varlibdir = varlibdir = self.tempfile("var_lib")
        os.mkdir(varlibdir)
        os.chown(varlibdir, frrcred.pw_uid, frrcred.pw_gid)
        self.varlibdir = varlibdir
        self.check_call(["mount", "--bind", varlibdir, "/var/lib"])

    def start_run(self):
        super().start_run()

        self.rtrcfg = self._configs.configs
        self.frrconfpath = self.tempfile("frr.conf")

        # TODO: convert to integrated config in tests rather than crudely merge here
        self.merged_cfg = "\n".join(
            self.rtrcfg.get(daemon, "") for daemon in self._configs.daemons
        )

        with open(self.frrconfpath, "w", encoding="utf-8") as fd:
            fd.write(self.merged_cfg)

        for daemon in self._configs.daemons:
            if daemon not in self.rtrcfg:
                continue
            self.logfiles[daemon] = self.tempfile("%s.log" % daemon)
            self.start_daemon(daemon, defer_config=True)

        if self.pids:
            # one-pass load all daemons
            self._load_config()

    def _load_config(self, daemon=None):
        daemon_arg = ["-d", daemon] if daemon else []

        vtysh = self._vtysh(
            daemon_arg + ["-f", self.frrconfpath], stderr=subprocess.PIPE
        )
        out, err = vtysh.communicate()
        out, err = out.decode("UTF-8"), err.decode("UTF-8")

        _logger.debug("stdout from config load: %r", out)
        _logger.debug("stderr from config load: %r", err)

        if 0 < vtysh.returncode < 128:
            raise FRRStartupVtyshConfigFail(
                self.name, vtysh.returncode, out, err, self.merged_cfg
            )
        if vtysh.returncode != 0:
            # terminated by signal
            raise subprocess.CalledProcessError(
                vtysh.returncode, vtysh.args, vtysh.stdout, vtysh.stderr
            )

    def start_daemon(self, daemon: str, defer_config=False):
        frrpath = self.frr.frrpath
        binmap = self.frr.binmap

        assert self.rundir is not None

        logfd = self._getlogfd(daemon)

        execpath = os.path.join(frrpath, binmap[daemon])
        cmdline = []

        cmdline.extend(
            [
                execpath,
                "-d",
            ]
        )
        cmdline.extend(
            [
                "--log",
                "file:%s" % self.logfiles[daemon],
                "--log",
                "monitor:%d" % logfd.fileno(),
                "--log-level",
                "debug",
                "--vty_socket",
                self.rundir,
                "-i",
                "%s/%s.pid" % (self.rundir, daemon),
            ]
        )
        try:
            self.check_call(cmdline, pass_fds=[logfd.fileno()])
        except subprocess.CalledProcessError as e:
            raise TopotatoDaemonStartFail(
                daemon=daemon, router=self.name, cmdline=shlex.join(cmdline)
            ) from e

        # want record-priority & timestamp precision...

        # have to retry this due to mgmtd/frr issue #16362
        for retry in range(30, -1, -1):
            try:
                pid, _, _ = self.vtysh_polled(
                    self.instance.timeline,
                    daemon,
                    "enable\nconfigure\nlog file %s\ndebug memstats-at-exit\nend\nclear log cmdline-targets"
                    % self.logfiles[daemon],
                )
                break
            except ConnectionRefusedError as e:
                if retry:
                    time.sleep(0.1)
                    continue
                raise TopotatoDaemonStartFail(
                    daemon=daemon, router=self.name, cmdline=shlex.join(cmdline)
                ) from e
            except FileNotFoundError as e:
                if retry:
                    time.sleep(0.1)
                    continue
                raise TopotatoDaemonStartFail(
                    daemon=daemon, router=self.name, cmdline=shlex.join(cmdline)
                ) from e

        self.pids[daemon] = pid

        if not defer_config:
            self._load_config(daemon)

    def start_post(self, timeline, failed: List[Tuple[str, str]]):
        for daemon in self._configs.daemons:
            if not self._configs.want_daemon(daemon):
                continue

            try:
                _, _, rc = self.vtysh_polled(timeline, daemon, "show version")
            except ConnectionRefusedError:
                failed.append((self.name, daemon))
                return
            except FileNotFoundError:
                failed.append((self.name, daemon))
                return
            if rc != 0:
                failed.append((self.name, daemon))

    def stop_daemon(self, daemon: str):
        if daemon not in self.pids:
            return

        pid = self.pids[daemon]
        del self.pids[daemon]

        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError as e:
            raise TopotatoDaemonCrash(daemon=daemon, router=self.name) from e

        for i in range(0, 5):
            self.instance.timeline.sleep(i * 0.1)
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                return

        raise TopotatoDaemonStopFail(daemon=daemon, router=self.name)

    def restart_daemon(self, daemon: str):
        self.stop_daemon(daemon)
        self.start_daemon(daemon)

    def end_prep(self):
        for livelog in self.livelogs.values():
            livelog.close_prep()

        for daemon, pid in list(reversed(self.pids.items())):
            try:
                os.kill(pid, signal.SIGTERM)
                # stagger SIGTERM signals a tiiiiny bit
                self.instance.timeline.sleep(0.01)
            except ProcessLookupError:
                del self.pids[daemon]
                # FIXME: log something

        super().end_prep()

    def end(self):
        livelogs = self.livelogs.values()

        # TODO: move this to instance level
        self.instance.timeline.sleep(1.0, final=livelogs)

        for livelog in self.livelogs.values():
            livelog.close()

        super().end()

    def _vtysh(self, args: List[str], **kwargs) -> subprocess.Popen:
        assert self.rundir is not None

        frrpath = self.frr.frrpath
        execpath = os.path.join(frrpath, "vtysh/vtysh")
        return self.popen(
            [execpath] + ["--vty_socket", self.rundir] + args,
            stdout=subprocess.PIPE,
            **kwargs,
        )

    def vtysh_exec(self, timeline: Timeline, cmds, timeout=5.0):
        cmds = [c.strip() for c in cmds.splitlines() if c.strip() != ""]

        args: List[str] = []
        for cmd in cmds:
            args.extend(("-c", cmd))

        proc = self._vtysh(args)
        output, _ = proc.communicate(timeout=timeout)
        output = output.decode("UTF-8")

        timed = TimedVtysh(
            time.time(), self.name, "vtysh", cmds, proc.returncode, output, True
        )
        timeline.append(timed)

        return (None, [timed], proc.returncode)

    def vtysh_polled(self, timeline: Timeline, daemon, cmds, timeout=5.0):
        if daemon == "vtysh":
            return self.vtysh_exec(timeline, cmds, timeout)

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM, 0)
        fn = self.tempfile("run/%s.vty" % (daemon))

        sock.connect(fn)
        peercred = sock.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3I")
        )
        pid, _, _ = struct.unpack("3I", peercred)

        cmds = [c.strip() for c in cmds.splitlines() if c.strip() != ""]

        # TODO: refactor
        vpoll = VtyshPoll(self.name, daemon, sock, cmds)

        output = []
        retcode = None

        with timeline.with_pollee(vpoll) as poller:
            vpoll.send_cmd()

            end = time.time() + timeout
            for event in poller.run_iter(end):
                if not isinstance(event, TimedVtysh):
                    continue
                output.append(event)
                retcode = event.retcode
                if event.last:
                    break

        return (pid, output, retcode)
