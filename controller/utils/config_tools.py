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

import json
import stat
import os
import re

from pathlib import Path
from loguru import logger
from jsonschema import validate
from typing import Optional

import state_manager
from utils.settings import *
from utils.system_commands import get_asset_relative_to, set_owner
from utils.settings import TestbedConfig, CommonSettings


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
        total_replaced = 0
        missing_replacements = []
        for placeholder in placeholders:
            replacement = os.environ.get(placeholder, None)
            if replacement is None:
                missing_replacements.append(f"{{{{{placeholder}}}}}")
                continue
            
            pattern = rf'{{{{\s*{re.escape(placeholder)}\s*}}}}'
            config_str = re.sub(pattern, replacement, config_str)
            logger.debug(f"Replaced {{{{{placeholder}}}}} with value '{replacement}'")
            total_replaced += 1
        
        if len(missing_replacements) != 0:
            raise Exception(f"Unable to get environment variables for placeholders {', '.join(missing_replacements)}: Variables not set.")
        else:
            logger.info(f"Replaced {total_replaced} placeholder variables in config.")

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


def load_vm_initialization(config: TestbedConfig, base_path: Path, state_manager: state_manager.InstanceStateManager) -> bool:
    for instance in config.instances:
        script_file = None
        env_variables = None
        if instance.setup_script is not None:
            script_file = base_path / Path(instance.setup_script)
            if not script_file.exists() or not script_file.is_relative_to(base_path):
                logger.critical(f"Unable to get script file '{script_file}' for Instance {instance.name}!")
                return False

            if not bool(script_file.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
                logger.critical(f"Setup script '{script_file}' for Instance {instance.name} is not executable!")
                return False

            script_file = instance.setup_script # relative to package root
        
            if instance.environment is None:
                env_variables = None
            else:
                env_variables = instance.environment
                if not isinstance(env_variables, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env_variables.items()):
                    logger.critical(f"Unable to load environment dict for VM {instance.name}")
                    return False

        state_manager.add_instance(
            name=instance.name, 
            script_file=script_file, 
            setup_env=env_variables, 
            init_preserve_files=instance.preserve_files)

    return True


def check_preserve_dir(preserve_dir: Optional[str]) -> bool:
    if preserve_dir is None:
        logger.warning("File Preservation is disabled, no files from Instances will be preserved!")
        return True
    
    if os.path.exists(preserve_dir):
        if not os.path.isdir(preserve_dir):
            logger.critical(f"File Preservation: {preserve_dir} is not a directory!")
            return False
        
        if len(os.listdir(preserve_dir)) != 0:
            logger.warning(f"File Preservation directory {preserve_dir} is not empty, possible overwrite")
    else:
        logger.debug(f"File Preservation directory {preserve_dir} does not exist, creating it.")
        os.mkdir(preserve_dir)
        if CommonSettings.executor is not None:
            set_owner(preserve_dir, CommonSettings.executor)

    logger.info(f"File Preservation: Saving instance files to {preserve_dir}")
    return True
