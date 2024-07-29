from abc import ABC, abstractmethod

class BaseCollector(ABC):
    @abstractmethod
    def start_collection(self, runtime: int = -1) -> None:
        pass

    @abstractmethod
    def is_running(self) -> bool:
        pass
