from abc import ABC, abstractmethod

class NamedInstance(ABC):
    @abstractmethod
    def get_name(self) -> str:
        pass

class Dismantable(NamedInstance):
    @abstractmethod
    def dismantle(self, force: bool = False) -> None:
        pass

    def dismantle_parallel(self) -> bool:
        return False
