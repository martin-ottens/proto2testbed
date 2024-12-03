import json
import dataclasses

from abc import ABC

class JSONSerializer(ABC):
    def to_json(self) -> str:
        return json.dumps(self.__dict__, default=lambda obj: obj.__dict__)
    
class DataclassJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if dataclasses.is_dataclass(obj):
            return dataclasses.asdict(obj)
        return super().default(obj)
