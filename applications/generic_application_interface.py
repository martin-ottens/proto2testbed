from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Dict, Any


class LogMessageLevel(Enum):
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    DEBUG = "DEBUG"
    WARNING = "WARNING"

    def __str__(self):
        return str(self.value)
    
    @staticmethod
    def from_str(level: str):
        return LogMessageLevel(level)


class GenericApplicationInterface(ABC):
    def __init__(self, app_name: str, socket_path: str) -> None:
        self.app_name = app_name
        self.socket_path = socket_path
    
    @abstractmethod
    def connect(self):
        pass

    @abstractmethod
    def disconnect(self):
        pass

    @abstractmethod
    def log(self, level: LogMessageLevel, message: str) -> bool:
        pass

    @abstractmethod
    def data_point(self, series_name: str, 
                   points: Dict[str, int | float], 
                   additional_tags: Optional[Dict[str, str]] = None) -> bool:
        pass

    @abstractmethod
    def preserve_file(self, path: str) -> bool:
        pass

