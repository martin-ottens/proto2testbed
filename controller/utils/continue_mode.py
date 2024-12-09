from enum import Enum

class PauseAfterSteps(Enum):
    SETUP = 1
    INIT = 2
    EXPERIMENT = 3
    DISABLE = 4


class ContinueMode(Enum):
    EXIT = "exit"
    RESTART = "restart"
    CONTINUE_TO = "continue_to"


class CLIContinue():
    def __init__(self, stopped_at: PauseAfterSteps):
        self.stopped_at = stopped_at
        self.mode = ContinueMode.EXIT
        self.pause = PauseAfterSteps.DISABLE

    def update(self, mode: ContinueMode, pause: PauseAfterSteps = PauseAfterSteps.DISABLE) -> bool:
        if self.stopped_at.value >= pause.value:
            return False
        
        self.mode = mode
        self.pause = pause
        return True
