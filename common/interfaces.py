import json

from abc import ABC

class JSONSerializer(ABC):
    def to_json(self) -> str:
        return json.dumps(self.__dict__, default=lambda obj: obj.__dict__)
