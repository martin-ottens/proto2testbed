#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2024-2025 Martin Ottens
# 
# This program is free software: you can redistribute it and/or modify 
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful, 
# but WITHOUT ANY WARRANTY; without even the implied warranty of 
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the 
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License 
# along with this program. If not, see https://www.gnu.org/licenses/.
#

MACHINE_STATE_FILE = "state.json"
GLOBAL_LOCKFILE = "p2t.filelock"
EXPERIMENT_RESERVATION_FILE = "reservationmap.json"
INTERCHANGE_DIR_PREFIX = "ptb-i-"
TAP_PREFIX = "ptb-t-"
BRIDGE_PREFIX = "ptb-b-"
INSTANCE_MANAGEMENT_SOCKET_PATH = "mgmt.sock"
INSTANCE_TTY_SOCKET_PATH = "tty.sock"
INSTANCE_INTERCHANGE_DIR_MOUNT = "mount/"
SUPPORTED_INSTANCE_NUMBER = 50
SUPPORTED_EXTRA_NETWORKS_PER_INSTANCE = 4
DEFAULT_CONFIG_PATH = "/etc/proto2testbed/proto2testbed_defaults.json"
DEFAULT_STATE_DIR = "/tmp/p2t/"
TESTBED_CONFIG_JSON_FILENAME = "testbed.json"
