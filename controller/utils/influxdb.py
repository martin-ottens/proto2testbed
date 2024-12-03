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
from utils.settings import CommonSetings

class InfluxDBAdapter(Dismantable):
    def _insert_thread(self):
        if self.store_disabled:
            return
        
        try:
            if self.user is not None:
                client = InfluxDBClient(host=self.host, port=self.port,
                                         user=self.user, password=self.password,
                                         retries=self.retries, timeout=self.timeout)
                client.switch_database(self.database)
            else:
                client = InfluxDBClient(host=self.host, port=self.port,
                                         retries=self.retries, timeout=self.timeout)
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
    
        if self.user is not None:
            client = InfluxDBClient(host=self.host, port=self.port, 
                                user=self.user, password=self.password, 
                                retries=self.retries, timeout=self.timeout)
        else:
            client = InfluxDBClient(host=self.host, port=self.port,
                                retries=self.retries, timeout=self.timeout)

        try:
            databases = client.get_list_database()
        except Exception as ex:
            logger.opt(exception=ex).critical("InfluxDBAdapter: Unable to connect to InfluxDB")
            client.close()
            return False

        if not len(list(filter(lambda x: x["name"] == self.database, databases))):
            logger.critical(f"InfluxDBAdapter: InfluxDB database '{self.database}' not found!")
            client.close()
            return False
    
        logger.info(f"InfluxDBAdapter: InfluxDB is up & running, database '{self.database}' was found.")
        client.close()
        return True

    def __init__(self, series_name: Optional[str] = None,
                 store_disabled: bool = False, config_path: Optional[Path] = None):
        self.store_disabled = store_disabled
        self.series_name = series_name

        if config_path is None:
            if not store_disabled and "INFLUXDB_DATABASE" not in os.environ.keys():
                default_database = CommonSetings.default_configs.get_defaults("influx_database")
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
            self.store_disabled = config.get("disabled", store_disabled)
            self.timeout = config.get("timeout", 20)
            self.retries = config.get("retries", 4)

        if not self._check_connection():
            raise Exception("InfluxDBAdapter: Unable to verify InfluxDB connection!")

        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._running = False
        self._thread = False

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
