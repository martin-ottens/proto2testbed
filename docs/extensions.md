# Extending Proto²Testbed

Some parts of Proto²Testbed are implemented in a modular way and can be easily extended. 
For Applications and Integration the Interface is identical whether the module is packaged inside the Instance Manager or Testbed Controller or dynamically loaded.

## Applications
See `applications/base_application.py` for the full interface. 
Any Application needs to extend the `BaseApplication` abstract base class. Each Application is executed in an own subprocess, so no direct interaction with the Instance Manager is possible. 
Therefore, each Application has access to an `ApplicationInterface` (using `self.interface`), this is used to push data to the InfluxDB or interact with the Instance Manager and Testbed Controller. 
See `applications/generic_application_interface.py` for the full interface.

Application-specific settings from the corresponding entry in the Testbed Configuration are passed as a dictionary to the `set_and_validate_config` method, the Application has to take care of parsing and storing the settings.

By design, Applications are always loaded from within the Instance Managers (or Testbed Controllers) Python Path. Therefore, other files can be referenced relative to the source roots for imports. 
This especially means, that other parts of the Application subsystem (e.g., the `BaseApplication` and `GenericApplicationInterface`) must be referenced relative to the root, e.g.:
```python
from applications.base_application import *
from applications.generic_application_interface import LogMessageLevel
from common.application_configs import ApplicationSettings
```

When adding a new Application that should be packaged with the Instance Manager, it can simply be placed in the `applications/` directory before the Instance Manager is rebuilt. 
In order for the data export to work, the new application must also be available to the Controller by placing it in the `applications/` directory on the Testbed Host. 
It is recommended to test and develop new Applications while loading them dynamically from within a Testbed Package.

## Integrations
Adding custom Integrations is similar to the method for Applications. 
See `controller/base_integration.py` for the full interface, each Integration must extend the `BaseIntegration` abstract base class. 
Since most parts of an Integration is executed in an own subprocess, direct Interaction with the rest of the Testbed Controller is not possible: 
Communication is handled via the `IntegrationStatusContainer` that is made available to each Integration during execution. 
The `IntegrationStatusContainer` can also be found in the file `controller/base_integration.py`.

Integration-specific settings from the corresponding entry in the Testbed Configuration are passed as a dictionary to the `set_and_validate_config` method, the Integration has to take care of parsing and storing the settings.

Integrations are loaded from within the Testbed Controllers Python Path. 
Therefore, other files need to be referenced relative to the root of the Testbed Controller. 
This means, for example, for the `BaseIntegration` and the `IntegrationStatusConatiner`:
```python
from utils.settings import IntegrationSettings
from base_integration import BaseIntegration, IntegrationStatusContainer
```
When adding a new Integration that should be packaged with the Testbed Controller, it can simply be placed in the `controller/integrations/` directory of the installation of the Testbed Host. 
It is recommended to test and develop new Integrations while loading them dynamically from within a Testbed Package.

## Top-Level Commands (Executors)
Additional commands can be added to the Testbed Controllers top-level CLI interface, each command is implemented as an Executor. 
See `controller/executors/` for examples, each executor has to implement the `BaseExecutor` abstract base class. 
During the `__init__` method call, the Executor can populate its subparser for CLI arguments, the `invoke` method is called, when the subcommand is selected. 
Common arguments are provided via the `CommonSettings` static class.

## Further Proto²Testbed Interfaces
Additional options to extend the functionality of the Proto²Testbed Controller are the contents of the temporary files for each Instance in `/tmp/ptb-i-*`. 
Each directory has a State File `state.json` containing details of that Instance (see `MachineStateFile` in `controller/helper/state_file_helper.py` for further details). 
Also, a Unix Domain Socket `tty.sock` is provided, that enables communication with the serial TTY console to that Instance. 
`mgmt.sock` is used by the Testbed Controller's Management Server and should not be touched.
