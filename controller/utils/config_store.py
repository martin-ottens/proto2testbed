from pathlib import Path
from loguru import logger

class ConfigStore():
    def __init__(self):
        self.setup_env = None
    
    def load_vm_initialization(self, config, base_path: Path) -> bool:
        self.setup_env = {}
        for machine in config["machines"]:
            if machine["setup_script"] is None:
                self.setup_env[machine["name"]] = None
            
            script_file = base_path / Path(machine["setup_script"])
            if not script_file.exists() or not script_file.is_relative_to(base_path):
                logger.critical(f"Unable to get script file '{script_file}' for VM {machine['name']}!")
                self.setup_env = None
                return False
            
            if machine["environment"] is None:
                env_variables = None
            else:
                env_variables = machine["environment"]
                if not isinstance(env_variables, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env_variables.items()):
                    logger.critical(f"Unable to load environment dict for VM {machine['name']}")
                    self.setup_env = None
                    return False
            
            self.setup_env[machine["name"]] = (str(script_file), env_variables, )

        return True
    
    def get_vm_initialization(self, name):
        if name not in self.setup_env.keys():
            raise Exception(f"Unkown VM name: '{name}'")
        
        return self.setup_env[name]