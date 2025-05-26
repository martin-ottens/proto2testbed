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

import jsonpickle
import os
import random
import string
import socket
import errno

from loguru import logger
from dataclasses import dataclass, field
from typing import List

from utils.state_lock import StateLock
from utils.settings import CommonSettings
from helper.network_helper import NetworkBridge
from constants import *


@dataclass
class ReservationMapping:
    vsock_cids: List[str] = field(default_factory=list)
    bridge_interfaces: List[str] = field(default_factory=list)
    tap_interfaces: List[str] = field(default_factory=list)


class ConcurrencyReservation:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        
        return cls._instance

    def __init__(self) -> None:
        self.current_reservation = ReservationMapping()
        self._write_reservation()

    def _write_reservation(self) -> None:
        with open(CommonSettings.statefile_base / CommonSettings.experiment / EXPERIMENT_RESERVATION_FILE, "w+") as handle:
            handle.write(jsonpickle.encode(self.current_reservation))

    def _collect_all_reservations(self) -> ReservationMapping:
        mapping = ReservationMapping()

        for experiment in os.listdir(CommonSettings.statefile_base):
            if not os.path.isdir(os.path.join(CommonSettings.statefile_base, experiment)):
                continue
            
            reservation_file = os.path.join(CommonSettings.statefile_base, experiment, EXPERIMENT_RESERVATION_FILE)

            if not os.path.exists(reservation_file):
                continue

            try:
                with open(reservation_file, "r") as handle:
                    reservations: ReservationMapping = jsonpickle.decode(handle.read())

                    mapping.bridge_interfaces.extend(reservations.bridge_interfaces)
                    mapping.tap_interfaces.extend(reservations.tap_interfaces)
                    mapping.vsock_cids.extend(reservations.vsock_cids)
            except Exception as ex:
                logger.opt(exception=ex).debug(f"Unable to read reservation file '{reservation_file}'")

        return mapping

    def generate_new_tap_names(self, count: int = 1) -> List[str]:
        tap_names: List[str] = []

        with StateLock.get_instance():
            reservations = self._collect_all_reservations()

            for _ in range(count):
                while True:
                    choice = TAP_PREFIX + "".join(random.choices(string.ascii_letters + string.digits, k=8))
                    if choice not in reservations.tap_interfaces:
                        tap_names.append(choice)
                        break

            if NetworkBridge.check_interfaces_available(tap_names):
                raise Exception(f"TAP interfaces from {tap_names} are not reserved but exist on the system!")
                
            self.current_reservation.tap_interfaces.extend(tap_names)
            self._write_reservation()
        
        return tap_names

    def generate_new_vsock_cids(self, count: int = 1) -> List[int]:
        while True:
            vsock_cids: List[int] = []

            with StateLock.get_instance():
                reservations = self._collect_all_reservations()

                for _ in range(count):
                    while True:
                        choice = random.randint(3, 0xFFFFFFFF)
                        if choice not in reservations.vsock_cids:
                            vsock_cids.append(choice)
                            break

                self.current_reservation.vsock_cids.extend(vsock_cids)
                self._write_reservation()

            one_match = False
            for vsock_cid in vsock_cids:
                s = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
                s.settimeout(0.1)
                try:
                    s.connect((vsock_cid, 1))
                    s.close()
                    logger.debug(f"Searching VSOCK CID: Connection succeeded with CID {vsock_cid}, but it was not reserved")
                    one_match = True
                    break
                except OSError as ex:
                    if ex.errno not in (errno.ENODEV, errno.EHOSTUNREACH):
                        logger.debug(f"Searching VSOCK CID: Connection error with CID {vsock_cid}, seems to be in use but it was not reserved")
                        one_match = True
                        break
                except Exception:
                    logger.debug(f"Searching VSOCK CID: Connection error with CID {vsock_cid}, seems to be in use but it was not reserved")
                    one_match = True
                    break

            if one_match:
                logger.warning("Regenerating VSOCK CID list since CIDs are in use without reservation.")
                self.current_reservation.vsock_cids = filter(lambda x: x not in vsock_cids, self.current_reservation.vsock_cids)
                with StateLock.get_instance():
                    self._write_reservation()
            else:
                return vsock_cids
                

    def generate_new_bridge_names(self, count: int = 1) -> List[str]:
        bridge_names: List[str] = []

        with StateLock.get_instance():
            reservations = self._collect_all_reservations()

            for _ in range(count):
                while True:
                    choice = BRIDGE_PREFIX + "".join(random.choices(string.ascii_letters + string.digits, k=8))
                    if choice not in reservations.bridge_interfaces:
                        bridge_names.append(choice)
                        break

            if NetworkBridge.check_interfaces_available(bridge_names):
                raise Exception(f"Bridge interfaces from {bridge_names} are not reserved but exist on the system!")
                
            self.current_reservation.bridge_interfaces.extend(bridge_names)
            self._write_reservation()
        
        return bridge_names
