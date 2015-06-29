# -*- coding: utf-8 -*-
# ----------------------------------------------------------------------------
# (C) British Crown Copyright 2012-5 Met Office.
#
# This file is part of Rose, a framework for meteorological suites.
#
# Rose is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Rose is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Rose. If not, see <http://www.gnu.org/licenses/>.
# ----------------------------------------------------------------------------
"""Implement the "rose suite-clean" command."""

from glob import glob
import os
from pipes import quote
from rose.config import ConfigLoader, ConfigNode, ConfigSyntaxError
from rose.env import env_var_process
from rose.fs_util import FileSystemEvent
from rose.host_select import HostSelector
from rose.opt_parse import RoseOptionParser
from rose.popen import RosePopenError
from rose.reporter import Reporter
from rose.suite_engine_proc import SuiteEngineProcessor, SuiteStillRunningError
import sys
import traceback
from uuid import uuid4


class SuiteRunCleaner(object):

    """Logic to remove items created by the previous runs of suites."""

    CLEANABLE_PATHS = ["share", "share/cycle", "work"]

    def __init__(self, event_handler=None, host_selector=None,
                 suite_engine_proc=None):
        if event_handler is None:
            event_handler = Reporter()
        self.event_handler = event_handler
        if host_selector is None:
            host_selector = HostSelector(event_handler=event_handler)
        self.host_selector = host_selector
        if suite_engine_proc is None:
            suite_engine_proc = SuiteEngineProcessor.get_processor(
                event_handler=event_handler)
        self.suite_engine_proc = suite_engine_proc

    def clean(self, suite_name, only_items=None):
        """Remove items created by the previous run of a suite.

        Change to user's $HOME for safety.

        """
        os.chdir(os.path.expanduser('~'))
        self.suite_engine_proc.check_suite_not_running(suite_name)
        self._clean(suite_name, only_items)
        self.suite_engine_proc.clean_hook(suite_name)

    def _clean(self, suite_name, only_items=None):
        """Perform the cleaning operations."""
        engine = self.suite_engine_proc
        suite_dir_rel = engine.get_suite_dir_rel(suite_name)
        locs_file_path = engine.get_suite_dir(
            suite_name, "log", "rose-suite-run.locs")
        locs_conf = ConfigNode().set(["localhost"], {})
        try:
            ConfigLoader().load(locs_file_path, locs_conf)
        except IOError:
            pass
        items = self.CLEANABLE_PATHS + [""]
        if only_items:
            items = only_items
        items.sort()
        uuid_str = str(uuid4())
        for auth, node in sorted(locs_conf.value.items(), self._auth_node_cmp):
            locs = []
            roots = set([""])
            for item in items:
                if item:
                    locs.append(os.path.join(suite_dir_rel, item))
                else:
                    locs.append(suite_dir_rel)
                if item and os.path.normpath(item) in self.CLEANABLE_PATHS:
                    item_root = node.get_value(["root-dir{" + item + "}"])
                    if item_root is None:  # backward compat
                        item_root = node.get_value(["root-dir-" + item])
                elif item == "":
                    item_root = node.get_value(["root-dir"])
                else:
                    continue
                if item_root:
                    loc_rel = suite_dir_rel
                    if item:
                        loc_rel = os.path.join(suite_dir_rel, item)
                    locs.append(os.path.join(item_root, loc_rel))
                    roots.add(item_root)
            if self.host_selector.is_local_host(auth):
                # Clean relevant items
                for loc in locs:
                    loc = os.path.abspath(env_var_process(loc))
                    for name in sorted(glob(loc)):
                        engine.fs_util.delete(name)
                # Clean empty directories
                # Change directory to root level to avoid cleaning them as well
                # For cylc suites, e.g. it can clean up to an empty "cylc-run/"
                # directory.
                for root in sorted(roots):
                    cwd = os.getcwd()
                    if root:
                        try:
                            os.chdir(env_var_process(root))
                        except OSError:
                            continue
                    # Reverse sort to ensure that e.g. "share/cycle/" is
                    # cleaned before "share/"
                    for name in sorted(self.CLEANABLE_PATHS, reverse=True):
                        try:
                            os.removedirs(os.path.join(suite_dir_rel, name))
                        except OSError:
                            pass
                    try:
                        os.removedirs(suite_dir_rel)
                    except OSError:
                        pass
                    if root:
                        os.chdir(cwd)
            else:
                # Invoke bash as a login shell. The root location of a path may
                # be in $DIR syntax, which can only be expanded correctly in a
                # login shell. However, profile scripts invoked on login to the
                # remote host may print lots of junks. Hence we use a UUID here
                # as a delimiter. Only output after the UUID lines are
                # desirable lines.
                command = engine.popen.get_cmd("ssh", auth, "bash", "-l", "-c")
                sh_command = (
                    "echo %(uuid)s; ls -d %(locs)s|sort; rm -fr %(locs)s"
                ) % {
                    "locs": engine.popen.list_to_shell_str(locs),
                    "uuid": uuid_str,
                }
                # Clean empty directories
                # Change directory to root level to avoid cleaning them as well
                # For cylc suites, e.g. it can clean up to an empty "cylc-run/"
                # directory.
                for root in roots:
                    names = []
                    # Reverse sort to ensure that e.g. "share/cycle/" is
                    # cleaned before "share/"
                    for name in sorted(self.CLEANABLE_PATHS, reverse=True):
                        names.append(os.path.join(suite_dir_rel, name))
                    sh_command += (
                        "; " +
                        "(cd %(root)s; rmdir -p %(names)s 2>/dev/null || true)"
                    ) % {
                        "root": root,
                        "names": engine.popen.list_to_shell_str(names),
                    }
                command.append(quote(sh_command))
                is_after_uuid_str = False
                for line in engine.popen(*command)[0].splitlines():
                    if is_after_uuid_str:
                        engine.handle_event(FileSystemEvent(
                            FileSystemEvent.DELETE, auth + ":" + line.strip()))
                    elif line == uuid_str:
                        is_after_uuid_str = True

    __call__ = clean

    @staticmethod
    def _auth_node_cmp(item1, item2):
        """Compare (auth1, node1) and (auth2, node2)."""
        ret = cmp(item1, item2)
        if ret:
            if item1[0] == "localhost":
                return -1
            elif item2[0] == "localhost":
                return 1
        return ret


def main():
    """Implement the "rose suite-clean" command."""
    opt_parser = RoseOptionParser()
    opt_parser.add_my_options("name", "non_interactive", "only_items")
    opts, args = opt_parser.parse_args()
    report = Reporter(opts.verbosity - opts.quietness)
    cleaner = SuiteRunCleaner(event_handler=report)
    if opts.name:
        args.append(opts.name)
    if not args:
        args = [os.path.basename(os.getcwd())]
    os.chdir(os.path.expanduser('~'))
    n_done = 0
    for arg in args:
        if not opts.non_interactive:
            try:
                answer = raw_input("Clean %s? y/n (default n) " % arg)
            except EOFError:
                sys.exit(1)
            if answer not in ["Y", "y"]:
                continue
        try:
            cleaner.clean(arg, opts.only_items)
        except (
            OSError,
            IOError,
            ConfigSyntaxError,
            RosePopenError,
            SuiteStillRunningError,
        ) as exc:
            report(exc)
            if opts.debug_mode:
                traceback.print_exc(exc)
        else:
            n_done += 1
    sys.exit(len(args) - n_done)  # Return 0 if everything done


if __name__ == "__main__":
    main()
