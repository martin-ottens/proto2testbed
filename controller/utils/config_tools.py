import json

from pathlib import Path
from loguru import logger
from jsonschema import validate

import state_manager

def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        raise Exception("Unable to find 'testbed.json' in given setup.")

    try:
        with open(config_path, "r") as handle:
            config = json.load(handle)
    except Exception as ex:
        logger.opt(exception=ex).critical("Unable to parse config json")
        raise Exception(f"Unable to parse config {config_path}")

    with open("assets/config.schema.json", "r") as handle:
        schema = json.load(handle)

    try:
        validate(instance=config, schema=schema)
    except Exception as ex:
        logger.opt(exception=ex).critical("Unable to validate config scheme")
        raise Exception(f"Unable to parse config {config_path}")
    
    return config


def load_vm_initialization(config, base_path: Path, state_manager: state_manager.MachineStateManager, fileserver_base: str) -> bool:
    for machine in config["machines"]:
        script_file = None
        env_variables = None
        if machine["setup_script"] is not None:
            script_file = base_path / Path(machine["setup_script"])
            if not script_file.exists() or not script_file.is_relative_to(base_path):
                logger.critical(f"Unable to get script file '{script_file}' for VM {machine['name']}!")
                return False
            script_file = machine["setup_script"] # relative to package root
        
            if machine["environment"] is None:
                env_variables = None
            else:
                env_variables = machine["environment"]
                if not isinstance(env_variables, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env_variables.items()):
                    logger.critical(f"Unable to load environment dict for VM {machine['name']}")
                    return False
        
        state_manager.add_machine(machine["name"], script_file, env_variables, fileserver_base)

    return True
    
