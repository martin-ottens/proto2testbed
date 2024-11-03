from abc import ABC

from typing import Any, Optional

from common.interfaces import JSONSerializer

class ApplicationConfig(ABC):
    pass

class ApplicationConfig(JSONSerializer):
    def __init__(self, name: str, application: str, delay: int = 0, 
                 runtime: int = 30, dont_store: bool = False, settings = Optional[Any]) -> None:
        self.name: str = name
        self.delay: int = delay
        self.runtime: int = runtime
        self.dont_store: bool = dont_store
        self.application = application
        self.settings: str = settings
