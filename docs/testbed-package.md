# Testbed Package

## Testbed Configuration
The testbed is configured with the `testbed.json` file. See `sample-config.json` for a full example. Most parts of this config are checked against the JSON schema located at `controller/assets/config.schema.json`. The top-level of the testbed configuration has the following structure:
```json
{
    "settings": {}, // Settings for testbed runs
    "networks": [], // Definition for virtual networks in testbed
    "integration": [], // Definition of Integrations
    "instances": [] // Definition of Instances
}
```

In all parts of the testbed configuration placeholder variables in the form `{{ PLACEHOLDER }}` can be inserted. These are replaces by the value of the corresponding environment variables upon testbed startup and before the JSON is validated. Environment variables must be set for all placeholders used in the testbed configuration, otherwise the startup will be aborted.

## Settings
The following settings are possible via the testbed configuration. All settings are optional.
```json
{
    "management_network": "auto",
    "diskimage_basepath": "/images/",
    "startup_init_timeout": 120,
    "experiment_timeout": 120,
    "file_preservation_timeout": 30,
    "appstart_timesync_offset": 1,
    "allow_gso_gro": false
}
```
- **`management_network`**: The subnet for the management network. If omitted, the management network is disabled for all Instances - they are not reachable via SSH or have automatic internet access. Values:
  - *auto*: A free subnet is selected automatically (default)
  - Subnet definition (e.g., `172.16.1.0/24`): Instances get IP addresses from the given subnet. The Testbed Host will always receive the first valid address from this subnet.
- **`diskimage_basepath`**: Base path for the disk images for the Instances. If relative path are given for the Instances, they are relative to this value (defaults to */*)
- **`startup_init_timeout`**: Timeout in seconds for startup and setup of the Instances (defaults to *30* seconds)
- **`experiment_timeout`**: Timeout for the experiments in seconds. Select *-1* so that the timeout is calculated based on the application with the longest duration (defaults to *-1*)
- **`file_preservation_timeout`**: Timeout for the file preservation stage (before testbed shutdown, defaults to *30* seconds)
- **`appstart_timesync_offset`**: The Instance's clock is synchronized to the controller's clock via KVM PTP during initialization. The first Applications will be started with a delay after the initialization is completed, to ensure that all clock are synced correctly. Use this value to give the Instances more time for clock synchronization (defaults to *1* second)
- **`allow_gso_gro`**: Since virtio drivers and bridge devices are just buffers (there is no physical transmission), no implicit pacing is introduced. This allows various components in the testbed's network to bundle multiple packets to GSO packets, which is often unwanted. This behavior is disabled by default, use this option to re-enable GSO packets in the testbed.

## Networks
Array of all networks used to build the virtual topology. Each network needs a **`name`**. Optionally, physical interfaces of the Testbed Host (**`host_ports`**) can be attached to a network.
```json
{
    "name": "name",
    "host_ports": ["eno2"] // or null
}
```

## Instances
Array of all Instances in a testbed. At least, `name`, `diskimage` and `networks` are required.
```json
{
    "name": "name",
    "diskimage": "/path/to/diskimage.qcow2",
    "setup_script": "path/to/setup_script.sh", // or null
    "environment": { // or null
        "KEY": "VALUE"
    },
    "cores": 2,
    "memory": 1024,
    "management_address": "172.16.0.2",
    "networks": [
        "name", // Option: string
        { // Option: object
            "name": "name",
            "mac": "AA:BB:CC:DD:EE:FF",
            "netmodel": "virtio",
            "vhost": true
        }
    ],
    "preserve_files": [ // or null
        "/path/to/preserve_files_or_directories"
    ],
    "applications": [
        // See "Applications" subsection
    ]
}
```
- **`name`**: Self-selected name of the Instance, used for internal reference, file preservation and labeling of the data pushed to the InfluxDB. Should be unique in a single testbed.
- **`diskimage`**: Disk image the Instance is based on. Relative to `settings.diskimage_basepath`.
- **`setup_script`**: Path to the setup script, that is executed on the Instance upon start. This script must be located inside the Testbed Package and the path is relative to its root. The setup script must be executable. Can be `null` or omitted if no setup is needed for the Instance. A valid bash script that exists with 0 on success is expected.
- **`environment`**: Environment variables passed to the setup script as a `string:string` object. Can be `null` or omitted, when no variables are needed.
- **`cores`**: CPU cores assigned to the Instance, optional (defaults to *2*)
- **`memory`**: Memory assigned to the Instance in MB, optional (defaults to *1024MB*)
- **`management_address`**: Optional fixed management IP address for the Instance. The address must be from configured management network and will be checked for conflicts (e.g. default gateway). Be cautious when using this setting only for a part of the Instances since auto generated addresses since unwanted conflicts could occur. (Address will be auto generated for the Instance when this setting is omitted and the management network enabled.)
- **`networks`**: List of networks the Instance will be attached to. All networks must be defined in the `networks` section. At most, an Instance can be attached to 4 networks (management network not included). The interfaces on the Instances will be assigned to networks by list positions and named `eth1` to `eth4`. The management network is always named `mgmt`, when enabled. Two types are possible, both can be mixed in the array:
    - **string**: Name of the attached network. A random MAC address will be assigned and `virtio` will be used as QEMU netmodel.
    - **object**: For more precise control of the interface settings. At least `name` is required:
        - **`name`**: Name of the attached network.
        - **`mac`**: MAC address for the interface with `:` delimiter. Random generated if omitted.
        - **`netmodel`**: QEMU emulation model for the virtual network interfaces from `virtio`, `e1000` and `rtl8139` (defaults to `virtio`)
        - **`vhost`**: Change the Zero-Copy behavior of the selected netmodel driver (defaults to `true` = Zero-Copy enabled)
- **`preserve_files`**: List of files that are copied to the Testbed Host before the Instance is terminated, if enabled during the testbed run. Absolute paths from the root of the Instance's file system. Can be omitted if no files should be preserved.

### Applications
Array of Applications installed on the Instance. Leave empty when the Instance should not execute any Applications. Each Application object consists of common settings and an Application-specific `settings` section.
```json
{
    "application": "type-of-application",
    "name": "name",
    "delay": 0,
    "runtime": 30, // or null for daemon Applications
    "dont_store": false,
    "settings": {
        // Application-specific settings
    },
    "depends": {
        // Dependencies for this Application
    }
}
```
- **`application`**: Type of the Application. First, Applications bundled in the Instance Manager are loaded. If the type is not found in these Applications, this value is interpreted as a path relative to the Testbed Package root, from there, the Instance Manager will attempt to dynamically load the Application. Have a look in the `applications/` directory of the repo to see what Applications are available bundled in the Instance Manager.
- **`name`**: Self-selected name of the Application, used for logs and result data labeling. Should be unique for each Instance in a testbed.
- **`delay`**: Delay in seconds for the start of Application after the Experiments are started on all Instances or the dependencies of the Application are met (defaults to *0* seconds)
- **`runtime`**: Maximum runtime in seconds for the Application, after this time, the Application will be terminated. It is up to the Application, if this value is used or another runtime is defined. If set to *null*, the Application is a daemon process that will run until testbed shutdown and will does not hold up the testbed execution (defaults to *30* seconds)
- **`dont_store`**: Boolean value if the Application should be executed without pushing data to the InfluxDB (defaults to `false`)
- **`load_from_instance`**: Load Application from an absolute path on the Instance's file system (cannot be used to export data, defaults to `false`)
- **`settings`**: Application-specific configuration, this object is passed to the Application Type selected by `application`. See the documentation in each Application of in the `applications/` and `extra-applications/` directories for the specific settings.
- **`depends`**: See below.

### Application Dependencies
Each application can have a list of dependencies that is used to determine when the Application should be started. Whenever the `depends` field is *null* or omitted, the Application will be started directly after the testbed enters the experiment stage, in other words without any dependencies. All Applications that are started in this way are synced, e.g. their starting timestamps are synced to sub-ms accuracy even across different Instances (using KVM PTP). Any configured `delay` is used as an offset from this common starting timestamp.

After an Application is started (or when the Application is ready, e.g. a server, can be controlled in the Applications implementation), it yields a `started` event, when the Application is finished (or failed), is yields a `finished` event. These events are used by the controller to resolve the dependencies of other Applications. Dependencies are configured in the following way, when multiple dependencies are defined, the Application will be invoked when all dependencies are met (*logical AND*).
```json
"depends": [
    {
        "at": "start-type",
        "instance": "previous-app-instance",
        "application": "previous-app-name"
    }
]
```
- **`at`**: The event type of the dependency: `started` or `finished`. Please not, that the `finished` event is not yielded by a daemon Application (when its runtime is set to *null*).
- **`instance`**: Name of the Instance the event is yielded from.
- **`application`**: Name of the Application (must be on `instance`) the event is yielded from.

Dependencies must build a directed acyclic graph (DAG) and all dependencies must be resolvable, e.g. all nodes of the DAG must be reachable from set of Applications that are started at the testbed startup. These constraints are checked at the startup of Proto²Testbed.

<details>
<summary>Example of an iPerf3 Server/Client using dependencies</summary>

#### On the first Instance (*Server*):
```json
// [...]
"applications": [
    {
        "application": "iperf3-server",
        "name": "iperf-server",
        "delay": 0,
        "runtime": null,
        "settings": {}
    }
],
// [...]
```

#### On the second Instance: (*Client*):
```json
// [...]
"applications": [
    {
        "application": "iperf3-client",
        "name": "iperf-client",
        "delay": 0,
        "runtime": 30,
        "settings": {
            "host": "10.0.0.1"
        },
        "depends": [
            {
                "at": "started",
                "instance": "first",
                "application": "iperf-server"
            }
        ]
    }
],
// [...]
```
</details>

## Integrations

> **Please Note:** Integrations can be disabled for all testbeds using the `disable_integrations` flag in the config at `/etc/proto2testbed/proto2testbed_defaults.json`. In this case, the `integrations` section must be fully omitted from the testbed config.

Integrations are programs executed on the Testbed Host during the testbed execution (e.g., for running a simulator or manipulating physical interfaces). There are several important things to consider when using Integrations:
- Integrations modify can change configurations of the Testbed Host - these changes are not rolled back automatically. The user must ensure, that the Integrations resets these changes upon termination of a testbed (e.g., by a shutdown script). For systems with concurrent testbed executions, unwanted side effects may occur.
- Integrations can be started at different phases of a testbed run, depending on when the configuration done by the Integration or software executed by the Integration needs to be available
- Integrations cannot push data to the InfluxDB. If you need to store data, you should rework your setup to use an Application for that.
 
Any number of Integrations can be executed on the Testbed Host, definitions are provided in an array:
```json
{
    "type": "type-of-integration",
    "name": "name",
    "environment": { // or null
        "KEY": "VALUE",
    },
    "invoke_after": "startup", // or "network", "init",
    "wait_after_invoke": 0,
    "settings": {
        // Integration-specific settings
    }
}
```
- **`type`**: Type of the Integration. First, Integrations bundled in the Testbed Controller are loaded. If the type is not found in these Integrations, this value is interpreted as a path relative to the Testbed Package root, from there, the Controller will attempt to dynamically load the Integration. Have a look in the `controller/src/integrations/` directory of the repo to see what Integrations are available bundled in the Controller.
- **`name`**: Self-selected name of the Integration, used for logging. Should be unique for each testbed run.
- **`environment`**: Environment variables passed to the Integration as a `string:string` object. Can be `null` or omitted, when no variables are needed.
- **`invoke_after`**: Stage, when the Integration will be started. The following stages are available:
  - `startup`: Directly after the testbed controller has been started (before the Instances or networks are started. If the Integrations provide network interfaces (e.g., simulation software), they can be used in `networks.host_ports` after this stage)
  - `network`: After the Instances and networks are started. All bridges and TAP interfaces are available at this stage, but the setup on the Instances is not started.
  - `init`: After the setup of the Instances is completed, but before any experiments are started.
- **`wait_after_invoke`**: Time in seconds the testbed Controller waits after the Integration was started before proceeding (defaults to *0* seconds)
- **`settings`**: Integration-specific configuration, this object is passed to the Integration Type selected by `tyüe`. See the documentation in the `controller/src/integrations/` directory for the specific settings.

## Other Files in the Testbed Package

All files contained in the Testbed Package are made available in the file system of all Instances at `/opt/testbed` in a read only way. The Testbed Package should contain only files that can be checked out in a version control system, so binaries etc. should be copied to the Testbed Package before execution.

### Dynamically Loaded Applications and Integrations
The Testbed Package can contain Python files for Applications and Integrations that are dynamically loaded during the testbed execution. See [`docs/extensions.md`](docs/extensions.md) for further details.

### Setup Script
The setup script is executed on an Instance once at the startup, before any experiments are started. It should perform the Instance-specific configuration and installation of additional dependencies in a one-shot way. Foreground programs used on the Instances should be handled using Applications. Startup scripts need to be executable.

Alongside the environment variables defined in `instances.environment`, the following environment variables are always passed to the setup script:
- `TESTBED_PACKAGE`: Path to the directory, where the Testbed Package is mounted on the Instance. Additional dependencies or configuration files can be copied from there.
- `INSTANCE_NAME`: The name of the Instance the script is executed on.

### Additional Scripts
Besides the dependencies and configurations required by the setup script, the Testbed Package can also contain files that are used by different parts of the framework:
- **Applications**: Scripts used by applications, e.g., the `run-program` Application found at `applications/run_program_application.py`.
- **Integrations**: Scripts executed by Integrations, e.g., the start- and stop-scripts executed by the `startstop` Integration found at `controller/src/integration/start_stop_integration.py`

