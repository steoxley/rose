#!/bin/bash
#-------------------------------------------------------------------------------
# (C) British Crown Copyright 2012-3 Met Office.
# 
# This file is part of Rose, a framework for scientific suites.
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
#-------------------------------------------------------------------------------
# Test "rose app-upgrade" for complex macros.
#-------------------------------------------------------------------------------
. $(dirname $0)/test_header
#-------------------------------------------------------------------------------
tests 3

#-------------------------------------------------------------------------------
# Check current working directory is app directory while upgrading
init <<'__CONFIG__'
meta=test-app-upgrade/apple
__CONFIG__
setup
init_meta test-app-upgrade apple fig
init_macro test-app-upgrade <<'__MACRO__'
#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os


import rose.upgrade


class UpgradeAppletoFig(rose.upgrade.MacroUpgrade):

    """Upgrade from Apple to Fig."""

    BEFORE_TAG = "apple"
    AFTER_TAG = "fig"

    def upgrade(self, config, meta_config=None):
        self.add_setting(config, ["namelist:add_sect_only"])
        print "Current directory:", os.getcwd()
        return config, self.reports
__MACRO__

#-----------------------------------------------------------------------------
TEST_KEY=$TEST_KEY_BASE-upgrade
# Check a complex upgrade
CONFIG_DIR=$(cd ../config && pwd -P)
run_pass "$TEST_KEY" rose app-upgrade --non-interactive \
 --meta-path=../rose-meta/ -C ../config fig
file_cmp "$TEST_KEY.out" "$TEST_KEY.out" <<__OUTPUT__
Current directory: $CONFIG_DIR
[U] Upgradeapple-fig: changes: 2
    namelist:add_sect_only=None=None
        Added
    =meta=test-app-upgrade/fig
        Upgraded from apple to fig
__OUTPUT__
file_cmp "$TEST_KEY.err" "$TEST_KEY.err" </dev/null
teardown
