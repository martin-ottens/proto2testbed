import json

from enum import Enum
from typing import Dict, List

from common.collector_configs import ExperimentConfig
from common.interfaces import JSONSerializer

class InstanceStatus(Enum):
    STARTED = "started"
    INITIALIZED = "initialized"
    MESSAGE = "message"
    FAILED = "failed"
    UNKNOWN = "unknown"

    def __str__(self):
        return str(self.value)
    
    @staticmethod
    def from_str(status: str):
        try: return InstanceStatus(status)
        except Exception:
            return InstanceStatus.UNKNOWN
        
        
class JSONSerializable():
    def as_json_bytes(self) -> bytes:
        return json.dumps(vars(self)).encode("utf-8")

class JSONSerializable():
    def as_json_bytes(self) -> bytes:
        return json.dumps(vars(self)).encode("utf-8")

class InstanceManagerDownstream(JSONSerializer):
    def __init__(self, name: str, status: str, message: str = None):
        self.name = name
        self.status = status
        self.message = message
    
    def get_status(self) -> InstanceStatus:
        return InstanceStatus.from_str(self.status)

class InitializeMessageUpstream(JSONSerializer):
    def __init__(self, status: str, script: str, environment: Dict[str, str]):
        self.status = status
        self.script = script
        self.environment = environment

# TODO: InfluxDB will become object as well
class ExperimentMessageUpstream(JSONSerializer):
    def __init__(self, status: str, influx: str, 
                 experiments: List[ExperimentConfig] = None) -> None:
        self.status = status
        self.influx = influx
        self.experiments = experiments

    @staticmethod
    def from_json(json):
        obj = ExperimentMessageUpstream(**json)

        if obj.experiments is None:
            return obj
        
        obj.experiments = []
        for experiment in json["experiments"]:
            obj.experiments.append(ExperimentConfig(**experiment))

        return obj

