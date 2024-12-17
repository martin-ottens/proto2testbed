import time

from typing import Dict, List, Optional, Tuple

from applications.base_application import *
from common.application_configs import ApplicationSettings
from applications.generic_application_interface import LogMessageLevel

"""
Monitors different system and/or process parameters:
- "interfaces": A list of interfaces of which different stats (like 
   raw sent/received bytes/packets) are monitored
- "processes": A list of command lines. All processes running on the Instance
   when the Application is started are checked against the entries, when a
   process matches, its PID will be monitored. Therefore, the process has to be
   launched before the Application and the PID should not change (e.g. the 
   process should not be restarted)
- "system": A boolean value whether different global system parameters, like CPU
  and memory usage should be monitored
All statistics are checked every "interval" seconds (defaults to 2). If the check
duration is longer, a log message will be logged to the Controller.

Example config:
    {
        "application": "procmon",
        "name": "check-iperf",
        "delay": 0,
        "runtime": 60,
        "settings": {
            "interval": 2, // every two second
            "processes": ["iperf3 -s"], // cmdline of the monitored process
            "interfaces": ["enp0s3"], // name of monitored interfaces
            "system": true // monitor global system parameters
        }
    }
"""

class ProcmonApplicationConfig(ApplicationSettings):
    def __init__(self, interval: int = 2, interfaces: List[str] = None,
                 processes: List[str] = None, system: bool = True) -> None:
        self.interval = interval
        self.interfaces = interfaces
        self.processes = processes
        self.system = system


class ProcmonApplication(BaseApplication):
    NAME = "procmon"

    def set_and_validate_config(self, config: ApplicationSettings) -> Tuple[bool, Optional[str]]:
        try:
            self.settings = ProcmonApplicationConfig(**config)
            return True, None
        except Exception as ex:
            return False, f"Config validation failed: {ex}"
        
    def get_runtime_upper_bound(self, runtime: int) -> int:
        return runtime + 2 * self.settings.interval

    def start(self, runtime: int) -> bool:
        import psutil

        if self.settings is None:
            return False

        if self.settings.system is False and self.settings.interfaces is None and self.settings.processes is None:
            raise Exception("Procmon has nothing to do (system, process, and interface monitoring disabled!")
        
        def proc_to_dict(process: psutil.Process) -> Dict[str, float]:
            cpu = process.cpu_times()
            mem = process.memory_info()
            return {
                    "cpu_user": cpu.user,
                    "cpu_system": cpu.system,
                    "cpu_child_user": cpu.children_user,
                    "cpu_child_system": cpu.children_system,
                    "mem_rss": mem.rss,
                    "mem_vms": mem.vms,
                    "mem_shared": mem.shared 
            }
        
        def snetio_to_dict(snetio) -> Dict[str, float]:
            return {
                    "bytes_sent": snetio.bytes_sent,
                    "bytes_recv": snetio.bytes_recv,
                    "packets_sent": snetio.packets_sent,
                    "packets_recv": snetio.packets_recv,
                    "errin": snetio.errin,
                    "errout": snetio.errout,
                    "dropin": snetio.dropin,
                    "dropout": snetio.dropout
            }
        
        def system_to_dict() -> Dict[str, float]:
            cpu = psutil.cpu_times(percpu=False)
            mem = psutil.virtual_memory()
            return {
                "cpu_user": cpu.user,
                "cpu_system": cpu.system,
                "cpu_idle": cpu.idle,
                "cpu_iowait": cpu.iowait,
                "cpu_irq": cpu.irq,
                "cpu_softirq": cpu.softirq,
                "mem_used": mem.used,
                "mem_free": mem.free,
                "mem_buffers": mem.buffers,
                "mem_chached": mem.cached
            }
        
        def diff_two_dicts(dict_offset: Dict[str, float], dict_current: Dict[str, float]) -> Dict[str, float]:
            result = {}
            for k, v in dict_current.items():
                result[k] = v - dict_offset[k]
            return result
        
        def report(system_, processes_, interfaces_) -> None:
            if system_ is not None:
                self.interface.data_point("proc-system", system_)
            for k, v in processes_.items(): 
                self.interface.data_point("proc-process", v, {"process": k})
            for k, v in interfaces_.items():
                self.interface.data_point("proc-interface", v, {"interface": k})
        
        # Processes -> t=0 Offset
        processes = {}
        if self.settings.processes is not None:
            for psutil_proc in psutil.process_iter(["cmdline", "pid"]):
                cmdline = " ".join(psutil_proc.info["cmdline"])
                found = None
                for config_process in self.settings.processes:
                    if cmdline.startswith(config_process):
                        found = config_process
                        break

                if found is None:
                    continue
                
                if found in processes.keys():
                    raise Exception(f"Process cmdline identifier '{cmdline}' is ambiguous!")

                processes[config_process] = {
                    "pid": psutil_proc.info["pid"],
                    "offset": proc_to_dict(psutil_proc),
                    "proc": psutil_proc
                }
            
            for proc_name in self.settings.processes:
                if proc_name not in processes.keys():
                    raise Exception(f"Unable to find process with cmdline '{proc_name}'!")
    

        # Interfaces -> t=0 Offset
        interfaces = {}
        if self.settings.interfaces is not None:
            net_io_list = psutil.net_io_counters(pernic=True, nowrap=False)
            for if_name in self.settings.interfaces:
                if if_name not in net_io_list.keys():
                    raise Exception(f"Unable to find interface {if_name}")
                interfaces[if_name] = snetio_to_dict(net_io_list[if_name])
        
        # System
        system = None
        if self.settings.system is True:
            system = system_to_dict()
        
        tracking_error_flag = 0
        print_cant_keep_up = True
        time_left = runtime
        while True:
            start = time.time()

            # Processes
            run_processes = {}
            for proc_name, elem in processes.items():
                try:
                    if not elem["proc"].is_running():
                        raise Exception(f"Process {proc_name} no longer running!")
                    run_processes[proc_name] = diff_two_dicts(elem["offset"], proc_to_dict(elem["proc"]))
                except Exception as ex:                    
                    run_processes[proc_name] = elem["offset"]
                    tracking_error_flag += 1
            
            # Interfaces
            run_interfaces = {}
            net_io_list = psutil.net_io_counters(pernic=True, nowrap=False)
            for int_name, elem in interfaces.items():
                try:
                    run_interfaces[int_name] = diff_two_dicts(elem, snetio_to_dict(net_io_list[int_name]))
                except Exception as _:
                    run_interfaces[int_name] = elem
                    tracking_error_flag += 1
            
            # System
            if system is not None:
                run_system = diff_two_dicts(system, system_to_dict())
            else:
                run_system = None
            
            report(run_system, run_processes, run_interfaces)

            took = time.time() - start

            if took >= self.settings.interval:
                if print_cant_keep_up:
                    self.interface.log(LogMessageLevel.WARNING, "Can't keep up with logging interval!")
                    print_cant_keep_up = False
                time_left -= took
            else:
                sleep_for = min(time_left - took, self.settings.interval - took)
                time.sleep(sleep_for)
                time_left -= sleep_for
            
            if time_left < self.settings.interval:
                break
            
        return tracking_error_flag == 0
    
    def get_export_mapping(self, subtype: ExportSubtype) -> Optional[List[ExportResultMapping]]:
        match subtype.name:
            case "proc-system":
                return [
                    ExportResultMapping(
                        name="cpu_user",
                        type=ExportResultDataType.SECONDS, 
                        description="User CPU Time"
                    ),
                    ExportResultMapping(
                        name="cpu_system", 
                        type=ExportResultDataType.SECONDS,
                        description="System/Kernel CPU Time"
                    ),
                    ExportResultMapping(
                        name="cpu_idle", 
                        type=ExportResultDataType.SECONDS,
                        description="Idle CPU Time"
                    ),
                    ExportResultMapping(
                        name="mem_used", 
                        type=ExportResultDataType.DATA_SIZE,
                        description="Used System Memory"
                    ),
                    ExportResultMapping(
                        name="mem_free", 
                        type=ExportResultDataType.DATA_SIZE,
                        description="Free System Memory"
                    )
                ]
            case "proc-process":
                return [
                    ExportResultMapping(
                        name="cpu_user", 
                        type=ExportResultDataType.SECONDS,
                        description="Process CPU User Time",
                        additional_selectors={"process": subtype.options["process"]},
                        title_suffix=f'Process: {subtype.options["process"]}'
                    ),
                    ExportResultMapping(
                        name="cpu_system",
                        type=ExportResultDataType.SECONDS,
                        description="Process CPU System Time",
                        additional_selectors={"process": subtype.options["process"]},
                        title_suffix=f'Process: {subtype.options["process"]}'
                    ),
                    ExportResultMapping(
                        name="mem_rss",
                        type=ExportResultDataType.DATA_SIZE,
                        description="Process Memory Resident Set Size",
                        additional_selectors={"process": subtype.options["process"]},
                        title_suffix=f'Process: {subtype.options["process"]}'
                    ),
                    ExportResultMapping(
                        name="mem_vms",
                        type=ExportResultDataType.DATA_SIZE,
                        description="Process Virtual Memory Size",
                        additional_selectors={"process": subtype.options["process"]},
                        title_suffix=f'Process: {subtype.options["process"]}'
                    ),
                    ExportResultMapping(
                        name="mem_shared",
                        type=ExportResultDataType.DATA_SIZE,
                        description="Proces Shared Memory Size",
                        additional_selectors={"process": subtype.options["process"]},
                        title_suffix=f'Process: {subtype.options["process"]}'
                    )
                ]
            case "proc-interface":
                return [
                    ExportResultMapping(
                        name="bytes_sent",
                        type=ExportResultDataType.DATA_SIZE,
                        description="Bytes sent via Interface",
                        additional_selectors={"interface": subtype.options["interface"]},
                        title_suffix=f'Interface: {subtype.options["interface"]}'
                    ),
                    ExportResultMapping(
                        name="bytes_recv",
                        type=ExportResultDataType.DATA_SIZE,
                        description="Bytes received via Interface",
                        additional_selectors={"interface": subtype.options["interface"]},
                        title_suffix=f'Interface: {subtype.options["interface"]}'
                    ),
                    ExportResultMapping(
                        name="packets_sent",
                        type=ExportResultDataType.COUNT,
                        description="Packets sent via Interface",
                        additional_selectors={"interface": subtype.options["interface"]},
                        title_suffix=f'Interface: {subtype.options["interface"]}'
                    ),
                    ExportResultMapping(
                        name="packets_recv",
                        type=ExportResultDataType.COUNT,
                        description="Packets received via Interface",
                        additional_selectors={"interface": subtype.options["interface"]},
                        title_suffix=f'Interface: {subtype.options["interface"]}'
                    ),
                    ExportResultMapping(
                        name="errin",
                        type=ExportResultDataType.COUNT,
                        description="Interface Input Errors",
                        additional_selectors={"interface": subtype.options["interface"]},
                        title_suffix=f'Interface: {subtype.options["interface"]}'
                    ),
                    ExportResultMapping(
                        name="errout",
                        type=ExportResultDataType.COUNT,
                        description="Interface Output Errors",
                        additional_selectors={"interface": subtype.options["interface"]},
                        title_suffix=f'Interface: {subtype.options["interface"]}'
                    ),
                    ExportResultMapping(
                        name="dropin",
                        type=ExportResultDataType.COUNT,
                        description="Interface Input Drops",
                        additional_selectors={"interface": subtype.options["interface"]},
                        title_suffix=f'Interface: {subtype.options["interface"]}'
                    ),
                    ExportResultMapping(
                        name="dropout",
                        type=ExportResultDataType.COUNT,
                        description="Interface Output Drops",
                        additional_selectors={"interface": subtype.options["interface"]},
                        title_suffix=f'Interface: {subtype.options["interface"]}'
                    )
                ]
            case _:
                raise Exception(f"Unknown subtype '{subtype.name}' for procmon application")
