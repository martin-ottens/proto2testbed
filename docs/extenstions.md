# Extending Proto²Testbed

Some parts of Proto²Testbed are implemented in a modular way and can be easily extended. For Applications and Integration the Interface is identical whether the module is packaged inside the Instance Manager or Testbed Controller or dynamically loaded.

## Applications
See `applications/base_application.py` for the full interface. Any Application needs to extend the `BaseApplication` abstract base class. Each Application is executed in an own subprocess, so no direct interaction with the Instance Manager is possible. Therefore, each Application has access to an `ApplicationInterface` (using `self.interface`), this is used to push data to the InfluxDB or interact with the Instance Manager and Testbed Controller. See `applications/generic_application_interface.py` for the full interface.

By design, Applications are always loaded from within the Instance Managers (or Testbed Controllers) Python Path. Therefore, other files can be referenced relative to the source roots for imports. This especially means, that other parts of the Application subsystem (e.g., the `BaseApplication` and `GenericApplicationInterface`) must be referenced relative to the root, e.g.:
```python
from applications.base_application import *
from applications.generic_application_interface import LogMessageLevel
from common.application_configs import ApplicationSettings
```


## Integrations

## Top-Level Commands (Executors)

## Futher Proto²Testbed Interfaces
Statefiles, TTY-Socket