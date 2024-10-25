import json

from enum import Enum
from typing import Dict, List, Any

from common.application_configs import ApplicationConfig
from common.interfaces import JSONSerializer

class InstanceStatus(Enum):
    STARTED = "started"
    INITIALIZED = "initialized"
    DATA_POINT = "data_point"
    MSG_SUCCESS = "msg_success"
    MSG_INFO = "msg_info"
    MSG_ERROR = "msg_error"
    FAILED = "failed"
    EXPERIMENT_FAILED = "exp_failed"
    EXPERIMENT_DONE = "exp_done"
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

# Downstream: Instance -> Controller
# Upstream:   Controller -> Instance

class InstanceManagerDownstream(JSONSerializer):
    def __init__(self, name: str, status: str, message: Any = None):
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

class ApplicationsMessageUpstream(JSONSerializer):
    def __init__(self, status: str, applications: List[ApplicationConfig] = None) -> None:
        self.status = status
        self.applications = applications

    @staticmethod
    def from_json(json):
        obj = ApplicationsMessageUpstream(**json)

        if obj.applications is None:
            return obj
        
        obj.applications = []
        for application in json["applications"]:
            obj.applications.append(ApplicationConfig(**application))

        return obj

