#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2024 Martin Ottens
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

import os
import json
import threading
import queue
import base64
import hashlib

from typing import Optional, Any
from loguru import logger
from pathlib import Path
from jsonschema import validate
from influxdb import InfluxDBClient

from utils.interfaces import Dismantable
from utils.system_commands import get_asset_relative_to
from utils.settings import CommonSettings

class InfluxDBAdapter(Dismantable):
    def _get_client(self) -> InfluxDBClient:
        if self.user is not None:
            return InfluxDBClient(host=self.host, port=self.port, 
                                user=self.user, password=self.password, 
                                retries=self.retries, timeout=self.timeout)
        else:
            return InfluxDBClient(host=self.host, port=self.port,
                                retries=self.retries, timeout=self.timeout)

    def _insert_thread(self):
        if self.store_disabled:
            return
        
        try:
            client = self._get_client()
            client.switch_database(self.database)
        except Exception as ex:
            logger.opt(exception=ex).error("InfluxDBAdapter: Unable to connect to databse")
            return
        
        logger.debug("InfluxDBAdapter: InfluxDB Insert Thread started.")
        
        while True:
            point = self._queue.get()
            if point is None:
                logger.debug("InfluxDBAdapter: Stopping Insert Thread.")
                break
                
            try:
                client.write_points(point)
                logger.trace(f"InfluxDBAdapter: Wrote data point {point}")
            except Exception as ex:
                logger.opt(exception=ex).warning("InfluxDBAdapter: Unable to write datapoint")
        
        client.close()

    def _check_connection(self) -> bool:
        if self.store_disabled:
            return True
        
        client = None

        try:
            client = self._get_client()
            databases = client.get_list_database()

            if not len(list(filter(lambda x: x["name"] == self.database, databases))):
                logger.critical(f"InfluxDBAdapter: InfluxDB database '{self.database}' not found!")
                return False
        except Exception as ex:
            logger.opt(exception=ex).critical("InfluxDBAdapter: Unable to connect to InfluxDB")
            return False
        finally:
            if client is not None:
                client.close()
    
        logger.info(f"InfluxDBAdapter: InfluxDB is up & running, database '{self.database}' was found.")
        return True

    def __init__(self, series_name: Optional[str] = None,
                 warn_on_no_database: bool = False, config_path: Optional[Path] = None):
        self.store_disabled = warn_on_no_database
        self.series_name = series_name

        if config_path is None:
            if "INFLUXDB_DATABASE" not in os.environ.keys():
                default_database = CommonSettings.default_configs.get_defaults("influx_database")
                if default_database is None:
                    logger.critical("InfluxDBAdapter: INFLUXDB_DATABASE not set in environment. Set varaible or specify config.")
                    raise Exception("INFLUXDB_DATABASE not set in environment")
                else:
                    self.database = default_database
            else:
                self.database = os.environ.get("INFLUXDB_DATABASE")

            self.host = os.environ.get("INFLUXDB_HOST", "127.0.0.1")
            self.port = os.environ.get("INFLUXDB_PORT", 8086)
            self.user  = os.environ.get("INFLUXDB_USER", None)
            self.password = os.environ.get("INFLUXDB_PASSWORD", None)
            self.timeout = 20
            self.retries = 4

        else:
            if not config_path.exists():
                raise Exception(f"InfluxDBAdapter: Unable to load specified InfluxDB config '{config_path}'")
        
            try:
                with open(config_path, "r") as handle:
                    config = json.load(handle)
            except Exception as ex:
                logger.opt(exception=ex).critical("InfluxDBAdapter: Unable to parse InfluxDB config json")
                raise Exception(f"Unable to parse config {config_path}")

            with open(get_asset_relative_to(__file__, "../assets/influxdb.schema.json"), "r") as handle:
                schema = json.load(handle)

            try:
                validate(instance=config, schema=schema)
            except Exception as ex:
                logger.opt(exception=ex).critical("InfluxDBAdapter: Unable to validate InfluxDB config scheme")
                raise Exception(f"Unable to parse config {config_path}")

            self.database = config.get("database")
            self.series_name = config.get("series_name", series_name)
            self.password = config.get("password", None)
            self.host = config.get("host", "127.0.0.1")
            self.user = config.get("user", None)
            self.port = config.get("port", 8086)
            self.store_disabled = config.get("disabled", warn_on_no_database)
            self.timeout = config.get("timeout", 20)
            self.retries = config.get("retries", 4)

        if not self._check_connection():
            raise Exception("InfluxDBAdapter: Unable to verify InfluxDB connection!")

        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._running = False
        self._thread = False
        self._reader = None

    def get_selected_database(self) -> str:
        return self.database

    def get_access_client(self) -> Optional[InfluxDBClient]:
        if self._reader is None:
            try:
                self._reader = self._get_client()
                self._reader.switch_database(self.database)
            except Exception as ex:
                logger.opt(exception=ex).critical("Unable to create InfluxDB reader client")
                self._reader = None
                return None
        
        return self._reader
    
    def close_access_client(self):
        if self._reader is not None:
            self._reader.close()
            self._reader = None

    def insert(self, point: Any) -> bool:
        if self.store_disabled:
            logger.trace(f"InfluxDBAdapter: Store disabled for data point '{point}'")
            return True
        
        try:
            point[0]["tags"]["experiment"] = self.series_name

            hashstr = ""
            for tag_value in point[0]["tags"].values():
                hashstr += str(tag_value)
            hash = hashlib.sha256(hashstr.encode("utf-8"))
            point[0]["tags"]["hash"] = base64.urlsafe_b64encode(hash.digest())[0:16]
        except Exception:
            logger.warning("InfluxDBAdapter: Unable to add experiment tag to data point, skipping insert.")
            return False

        with self._lock:
            if not self._running:
                return False

            if point is None:
                raise Exception("Invalid point: Got 'None'")
            
            self._queue.put(point)
    
        return True

    def start(self):
        if self.store_disabled:
            return

        self._thread = threading.Thread(target=self._insert_thread, daemon=True)
        self._thread.start()
        self._running = True

    def stop(self):
        self.close_access_client()

        if self.store_disabled:
            return

        with self._lock:
            self._running = True
            self._queue.put(None) # Poison Pill
        self._thread.join()

    def get_name(self) -> str:
        return "InfluxDBAdapter"

    def dismantle(self, force: bool = False) -> None:
        self.stop()
