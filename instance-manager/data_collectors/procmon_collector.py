import psutil
import time

from typing import Dict

from data_collectors.base_collector import BaseCollector
from data_collectors.influxdb_adapter import InfluxDBAdapter
from common.collector_configs import CollectorConfig, ProcmonCollectorConfig

class ProcmonCollector(BaseCollector):
    def start_collection(self, settings: CollectorConfig, runtime: int, adapter: InfluxDBAdapter) -> bool:
        if not isinstance(settings, ProcmonCollectorConfig):
            raise Exception("Received invalid config type!")
        

        if settings.system is False and settings.interfaces is None and settings.processes is None:
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
                adapter.add("proc-system", system_)
            for k, v in processes_.items(): 
                adapter.add("proc-process", v, {"process": k})
            for k, v in interfaces_.items():
                adapter.add("proc-interface", v, {"interface": k})
        
        # Processes -> t=0 Offset
        processes = {}
        if settings.processes is not None:
            for psutil_proc in psutil.process_iter(["cmdline", "pid"]):
                cmdline = " ".join(psutil_proc.info["cmdline"])
                if cmdline not in settings.processes:
                    continue
                
                if cmdline in processes.keys():
                    raise Exception(f"Process cmdline identifier '{cmdline}' is ambiguous!")

                processes[cmdline] = {
                    "pid": psutil_proc.info["pid"],
                    "offset": proc_to_dict(psutil_proc),
                    "proc": psutil_proc
                }
            
            for proc_name in settings.processes:
                if proc_name not in processes.keys():
                    raise Exception(f"Unable to find process with cmdline '{proc_name}'!")
    

        # Interfaces -> t=0 Offset
        interfaces = {}
        if settings.interfaces is not None:
            net_io_list = psutil.net_io_counters(pernic=True, nowrap=False)
            for if_name in settings.interfaces:
                if if_name not in net_io_list.keys():
                    raise Exception(f"Unable to find interface {if_name}")
                interfaces[if_name] = snetio_to_dict(net_io_list[if_name])
        
        # System
        system = None
        if settings.system is True:
            system = system_to_dict()
        
        tracking_error_flag = 0
        sleep_left = runtime
        while sleep_left >= settings.interval:
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
                except Exception as ex:
                    run_interfaces[int_name] = elem
                    tracking_error_flag += 1
            
            # System
            if system is not None:
                run_system = diff_two_dicts(system, system_to_dict())
            else:
                run_system = None
            
            report(run_system, run_processes, run_interfaces)
            
            time.sleep(min(sleep_left, settings.interval))
            sleep_left -= settings.interval
            
        return tracking_error_flag == 0
