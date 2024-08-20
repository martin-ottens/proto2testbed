import json
import random
import os
import re

from pathlib import Path
from typing import Optional
from loguru import logger
from jsonschema import validate
from influxdb import InfluxDBClient

import state_manager
from utils.settings import *
from utils.system_commands import get_asset_relative_to

from common.configs import InfluxDBConfig

def load_config(config_path: Path, skip_substitution: bool = False) -> TestbedConfig:
    if not config_path.exists():
        raise Exception("Unable to find 'testbed.json' in given setup.")

    try:
        with open(config_path, "r") as handle:
            config_str: str = handle.read()
    except Exception as ex:
        raise Exception(f"Unable to load config '{config_path}'") from ex
    
    placeholders = list(map(lambda x: x.strip(), re.findall(r'{{\s*(.*?)\s*}}', config_str)))
    if skip_substitution:
        if placeholders is not None and len(placeholders) != 0:
            logger.warning(f"Config '{config_path}' contains placeholders, but substitution is disabled")
            logger.warning(f"Found placeholders: {', '.join(list(map(lambda x: f'{{{{{x}}}}}', placeholders)))}")
    else:
        missing_replacements = []
        for placeholder in placeholders:
            replacement = os.environ.get(placeholder, None)
            if replacement is None:
                missing_replacements.append(f"{{{{{placeholder}}}}}")
                continue

            config_str = config_str.replace(f"{{{{{placeholder}}}}}", replacement)
            logger.debug(f"Replaced {{{{{placeholder}}}}} with value '{replacement}'")
        
        if len(missing_replacements) != 0:
            raise Exception(f"Unable to get environment variables for placeholders {', '.join(missing_replacements)}: Variables not set.")

    try:
        config =  json.loads(config_str)
    except Exception as ex:
        raise Exception(f"Unable to parse contents from config '{config_path}'") from ex

    with open(get_asset_relative_to(__file__, "../assets/config.schema.json"), "r") as handle:
        schema = json.load(handle)

    try:
        validate(instance=config, schema=schema)
    except Exception as ex:
        logger.opt(exception=ex).critical("Unable to validate config scheme")
        raise Exception(f"Unable to parse config '{config_path}'")
    
    return TestbedConfig(config)


def load_vm_initialization(config: TestbedConfig, base_path: Path, state_manager: state_manager.MachineStateManager, fileserver_base: str) -> bool:
    for machine in config.instances:
        script_file = None
        env_variables = None
        if machine.setup_script is not None:
            script_file = base_path / Path(machine.setup_script)
            if not script_file.exists() or not script_file.is_relative_to(base_path):
                logger.critical(f"Unable to get script file '{script_file}' for VM {machine.name}!")
                return False
            script_file = machine.setup_script # relative to package root
        
            if machine.environment is None:
                env_variables = None
            else:
                env_variables = machine.environment
                if not isinstance(env_variables, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env_variables.items()):
                    logger.critical(f"Unable to load environment dict for VM {machine.name}")
                    return False
        
        state_manager.add_machine(machine.name, script_file, env_variables, fileserver_base)

    return True


def check_influx_connection(config: InfluxDBConfig) -> bool:
    if config.disabled:
        return True
    
    if config.user is not None:
        client = InfluxDBClient(host=config.host, port=config.port, 
                                user=config.user, password=config.password, 
                                retries=config.retries, timeout=config.timeout)
    else:
        client = InfluxDBClient(host=config.host, port=config.port,
                                retries=config.retries, timeout=config.timeout)

    try:
        databases = client.get_list_database()
    except Exception as ex:
        logger.opt(exception=ex).critical("Unable to connect to InfluxDB")
        client.close()
        return False

    if not len(list(filter(lambda x: x["name"] == config.database, databases))):
        logger.critical(f"InfluxDB database '{config.database}' not found!")
        client.close()
        return False
    
    logger.info(f"InfluxDB is up & running, database '{config.database}' was found.")
    client.close()
    return True


def load_influxdb(gateway_host: str, series_name: Optional[str] = None, 
                  store_disabled: bool = False, config_path: Optional[Path] = None) -> InfluxDBConfig:
    if series_name is None:
        series_name = "".join(random.choices('0123456789abcdef', k=7))
        if not store_disabled:
            logger.warning(f"InfluxDB experiment tag randomly generated -> {series_name}")

    if config_path is None:
        if not store_disabled and "INFLUXDB_DATABASE" not in os.environ.keys():
            logger.critical("INFLUXDB_DATABASE not set in environment. Set varaible or specify config.")
            raise Exception("INFLUXDB_DATABASE not set in environment")

        host = os.environ.get("INFLUXDB_HOST", gateway_host)
        port = os.environ.get("INFLUXDB_PORT", 8086)
        user  = os.environ.get("INFLUXDB_USER", None)
        password = os.environ.get("INFLUXDB_PASSWORD", None)
        database = os.environ.get("INFLUXDB_DATABASE")

        influx_config =  InfluxDBConfig(database=database, series_name=series_name, host=host,
                                        port=port, user=user, password=password, disabled=store_disabled)
        
    else:
        if not config_path.exists():
            raise Exception(f"Unable to load specified InfluxDB config '{config_path}'")
        
        try:
            with open(config_path, "r") as handle:
                config = json.load(handle)
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to parse InfluxDB config json")
            raise Exception(f"Unable to parse config {config_path}")

        with open(get_asset_relative_to(__file__, "../assets/influxdb.schema.json"), "r") as handle:
            schema = json.load(handle)

        try:
            validate(instance=config, schema=schema)
        except Exception as ex:
            logger.opt(exception=ex).critical("Unable to validate InfluxDB config scheme")
            raise Exception(f"Unable to parse config {config_path}")
        
        if "series_name" not in config.keys():
            config["series_name"] = series_name
        
        if "host" not in config.keys():
            config["host"] = gateway_host

        config["disabled"] = store_disabled

        influx_config = InfluxDBConfig(**config)

    if not check_influx_connection(influx_config):
        raise Exception("Unable to verify InfluxDB connection!")

    return influx_config
