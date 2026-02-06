#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2024-2026 Martin Ottens
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

from helper.network_helper import NetworkBridge
from constants import *


@dataclass
class ReservationMapping:
    vsock_cids: List[str] = field(default_factory=list)
    bridge_interfaces: List[str] = field(default_factory=list)
    tap_interfaces: List[str] = field(default_factory=list)
    cpu_cores: int = 0
    memory_mb: int = 0


class ConcurrencyReservation:
    def __init__(self, provider) -> None:
        self.provider = provider
        self.current_reservation = ReservationMapping()
        self.all_cpu_cores = 0
        self.all_memory_mb = 0
        self._get_system_capacity()

    def _write_reservation(self) -> None:
        os.makedirs(self.provider.statefile_base / self.provider.unique_run_name, mode=0o777, exist_ok=True)
        with open(self.provider.statefile_base / self.provider.unique_run_name / CONCURRENCY_RESERVATION_FILE, "w+") as handle:
            handle.write(jsonpickle.encode(self.current_reservation))

    def _collect_all_reservations(self) -> ReservationMapping:
        mapping = ReservationMapping()

        for unique_run_name in os.listdir(self.provider.statefile_base):
            if not os.path.isdir(os.path.join(self.provider.statefile_base, unique_run_name)):
                continue
            
            reservation_file = os.path.join(self.provider.statefile_base, unique_run_name, CONCURRENCY_RESERVATION_FILE)

            if not os.path.exists(reservation_file):
                continue

            try:
                with open(reservation_file, "r") as handle:
                    reservations: ReservationMapping = jsonpickle.decode(handle.read())

                    mapping.bridge_interfaces.extend(reservations.bridge_interfaces)
                    mapping.tap_interfaces.extend(reservations.tap_interfaces)
                    mapping.vsock_cids.extend(reservations.vsock_cids)

                    if unique_run_name != self.provider.unique_run_name:
                        mapping.cpu_cores += reservations.cpu_cores
                        mapping.memory_mb += reservations.memory_mb

            except Exception as ex:
                logger.opt(exception=ex).debug(f"Unable to read reservation file '{reservation_file}'")

        return mapping
    
    def _get_system_capacity(self) -> None:
        self.all_memory_mb = (os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")) // (1024 * 1024)
        self.all_cpu_cores = os.cpu_count()
        if self.all_cpu_cores is None:
            raise Exception("Unable to get host CPU core count")
    
    def clear_reservations(self) -> None:
        try:
            os.remove(self.provider.statefile_base / self.provider.unique_run_name / CONCURRENCY_RESERVATION_FILE)
            os.rmdir(self.provider.statefile_base / self.provider.unique_run_name)
        except Exception:
            pass

    def apply_resource_demand(self, cpu_cores: int, memory_mb: int) -> bool:
        with self.provider.state_lock:
            reservations = self._collect_all_reservations()

            if reservations.cpu_cores + cpu_cores > self.all_cpu_cores:
                logger.warning(f"Not enough CPU cores available: {self.all_cpu_cores} < {reservations.cpu_cores + cpu_cores}")
                return False
            
            if reservations.memory_mb + memory_mb > self.all_memory_mb:
                logger.warning(f"Not enough memory available: {self.all_memory_mb} MB < {reservations.memory_mb + memory_mb} MB")
                
                return False

            self.current_reservation.cpu_cores = cpu_cores
            self.current_reservation.memory_mb = memory_mb
            self._write_reservation()
        
        logger.debug(f"Host system usage after start: {reservations.cpu_cores + cpu_cores}/{self.all_cpu_cores} cores, {reservations.memory_mb + memory_mb}/{self.all_memory_mb} MB memory")
        return True

    def generate_new_tap_names(self, count: int = 1) -> List[str]:
        tap_names: List[str] = []

        if count <= 0:
            return tap_names

        with self.provider.state_lock:
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
        if count <= 0:
            return []

        while True:
            vsock_cids: List[int] = []

            with self.provider.state_lock:
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
                with self.provider.state_lock:
                    self._write_reservation()
            else:
                return vsock_cids
                

    def generate_new_bridge_names(self, count: int = 1) -> List[str]:
        bridge_names: List[str] = []

        if count <= 0:
            return bridge_names

        with self.provider.state_lock:
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
