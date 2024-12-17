#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2024 Martin Ottens
# 
# This program is free software: you can redistribute it and/or modify 
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful, 
# but WITHOUT ANY WARRANTY; without even the implied warranty of 
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the 
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License 
# along with this program. If not, see https://www.gnu.org/licenses/.
#

import os

from typing import List, Optional, Callable, Any
from loguru import logger
from dataclasses import dataclass
from pathlib import Path

import dateutil.parser as dateparser

from utils.influxdb import InfluxDBAdapter
from utils.settings import CommonSettings, TestbedConfig, ApplicationConfig
from applications.base_application import *
from common.application_loader import ApplicationLoader


@dataclass
class SeriesContainer:
    instance: str
    app_config: ApplicationConfig
    export_mapping: ExportResultMapping
    type_name: str
    x: List[int]
    y: List[Any]


class ResultExportHelper:
    def __init__(self, output_path: str, config: TestbedConfig,
                 testbed_package_path: str,
                 exclude_instances: Optional[List[str]] = None,
                 exclude_applications: Optional[List[str]] = None) -> None:
        self.output_path = output_path
        self.config = config
        self.exclude_instances = exclude_instances
        self.exclude_applications = exclude_applications
        self.adapter = InfluxDBAdapter(warn_on_no_database=True, 
                                       config_path=CommonSettings.influx_path)
        self.reader = self.adapter.get_access_client()
        if self.reader is None:
            raise Exception("Unable to create InfluxDB data reader")

        self.loader = ApplicationLoader(CommonSettings.app_base_path, testbed_package_path, 
                                        ["exports_data", "get_export_mapping"])
        self.loader.read_packaged_apps()

    def __del__(self) -> None:
        self.adapter.close_access_client()
    
    def _map_to_application_class(self, app_config: ApplicationConfig) -> Optional[BaseApplication]:
        try: 
            app, status = self.loader.load_app(app_config.application, True)
            if app is None:
                logger.error(f"Unable to load application class for type '{app_config.application}': {status}")
                return None
            logger.debug(f"Application Loader status for '{app_config.application}': {status}")
            return app
        except Exception as ex:
            logger.opt(exception=ex).error(f"Unable to load application class for type '{app_config.application}'")
            return None
        
    def _get_internal_subtypes(self, instance_name: str, app_config: ApplicationConfig) -> List[ExportSubtype]:
        result = []

        database_entries = self.reader.get_list_series(tags={
            "experiment": CommonSettings.experiment,
            "application": app_config.name,
            "instance": instance_name
        })

        if len(database_entries) == 0:
            logger.error(f"Unable to find results for application '{app_config.name}' of type '{app_config.application}' for instance {instance_name}")
            return result

        for database_entry in database_entries:
            parts = database_entry.split(",", maxsplit=1)
            if len(parts) != 2:
                logger.warning(f"Invalid database results for application '{app_config.name}' of type '{app_config.application}' for instance {instance_name}")
                continue
            
            type, option_str = parts
            option_list = option_str.split(",")
            options = {k: v for k, v in map(lambda y: (y[0], y[1], ), map(lambda x: x.split("="), option_list))}
            result.append(ExportSubtype(type, options))
        
        return result
    
    def _handle_application_series(self, subtypes: List[ExportSubtype], application: ApplicationConfig, 
                                   app_instance: BaseApplication, instance_name: str,
                                   export_callback: Callable[[SeriesContainer], bool]) -> bool:
        for subtype in subtypes:
            try:
                data_mappings = app_instance.get_export_mapping(subtype)
                if data_mappings is None or len(data_mappings) == 0:
                    logger.warning(f"Application '{application.name}' of type '{application.application}' from instance '{instance_name}' does not define export outputs, even data exists.")
                    continue
            except Exception as ex:
                logger.opt(exception=ex).error(f"Error getting export mappings for application '{application.name}' of type '{application.application}' from instance '{instance_name}'")
                return False
            
            for series in data_mappings:
                bind_params = {
                    "experiment": CommonSettings.experiment,
                    "instance": instance_name,
                    "application": application.name
                }
                query_suffix = ""
                
                if series.additional_selectors is not None:
                    for selector, value in series.additional_selectors.items():
                        bind_params[selector] = value
                        query_suffix += f" AND \"{selector}\" = ${selector}"
                
                query = f"SELECT \"{series.name}\" FROM \"{subtype.name}\" WHERE \"application\" = $application AND \"experiment\" = $experiment AND \"instance\" = $instance{query_suffix}"
                
                try:
                    points = self.reader.query(query, bind_params=bind_params).get_points()
                except Exception as ex:
                    logger.opt(exception=ex).error(f"Unable to fetch series for '{series.name}' from '{subtype.name}'")
                    return False
                
                if points is None:
                    logger.warning(f"Query for '{series.name}' from '{subtype.name}' has not yield any results")
                    continue
                
                data_points = []
                for point in points:
                    data_points.append((int(dateparser.parse(point["time"]).timestamp()), point[series.name]))

                if len(data_points) == 0:
                    logger.warning(f"Query for '{series.name}' from '{subtype.name}' has not yield any results")
                    continue

                t_0 = min(map(lambda x: x[0], data_points))
                x = []
                y = []
                for data_point in data_points:
                    x.append(data_point[0] - t_0 + application.delay)
                    y.append(data_point[1])
                
                series_container = SeriesContainer(
                    instance=instance_name,
                    app_config=application,
                    export_mapping=series,
                    type_name=subtype.name,
                    x=x,
                    y=y
                )
                try:
                    export_callback(series_container)
                except Exception as ex:
                    logger.opt(exception=ex).error(f"Unable to run exporter for application '{application.application}', instance '{instance_name}', type '{subtype.name}'")
                    return False

        return True

    def _process_series(self, export_callback: Callable[[SeriesContainer], bool]) -> bool:
        for instance in self.config.instances:
            if self.exclude_instances is not None and instance.name in self.exclude_instances:
                logger.debug(f"Skipping instance '{instance.name}': Name in exclude list.")
                continue

            if instance.applications is None or len(instance.applications) == 0:
                logger.debug(f"Skipping instance '{instance.name}': No application configured.")
                continue

            logger.debug(f"Processing instance '{instance.name}'")

            for application in instance.applications:
                if self.exclude_applications is not None and application.application in self.exclude_applications:
                    logger.debug(f"Skipping application '{application.name}' of type '{application.application}' from instance '{instance.name}': Type in exclude list.")
                    continue

                if application.dont_store:
                    logger.debug(f"Skipping application '{application.name}' of type '{application.application}' from instance '{instance.name}': Data store disabled.")
                    continue

                app_cls = self._map_to_application_class(application)
                if app_cls is None:
                    return False
                
                app_instance: BaseApplication = app_cls()
                if not app_instance.exports_data():
                    logger.info(f"Skipping application '{application.name}' of type '{application.application}': Does not export any data")
                    continue
                
                logger.info(f"Processing application '{application.name}' of type '{application.application}' from instance '{instance.name}'")

                subtypes = self._get_internal_subtypes(instance.name, application)
                if len(subtypes) == 0:
                    continue

                try:
                    status, message = app_instance.set_and_validate_config(application.settings)
                    if not status:
                        if message:
                            logger.error(f"Config validation for '{application.name}' of type '{application.application}' from instance '{instance.name}' failed: {message}")
                        else:
                            logger.debug(f"Config validation for '{application.name}' of type '{application.application}' from instance '{instance.name}' failed without message")
                        return False
                    elif message:
                        logger.debug(f"Config validation for '{application.name}' of type '{application.application}' from instance '{instance.name}' succeeded: {message}")
                except Exception as ex:
                    logger.opt(exception=ex).error(f"Error passing the testbed config to application '{application.name}' of type '{application.application}' from instance '{instance.name}'")
                    return False
                
                if not self._handle_application_series(
                    subtypes=subtypes,
                    application=application,
                    app_instance=app_instance,
                    instance_name=instance.name,
                    export_callback=export_callback
                ):
                    logger.error(f"Unable to process application '{application.application}' for instance '{instance.name}'")
                    continue

        return True

    def output_to_plot(self, output_path: str, format: str = "pdf") -> bool:
        path = Path(output_path)

        try:
            import matplotlib.pyplot as plt
            import matplotlib.ticker as ticker
            import numpy as np
        except Exception as ex:
            logger.opt(exception=ex).critical("Dependencies for plotting missing on this system")
            return False

        def plot_export_callback(container: SeriesContainer) -> bool:
            _, ax = plt.subplots()
            ax.plot(np.array(container.x), np.array(container.y))
            plt.xlabel("Seconds", fontsize=7)
            plt.ylabel(f"{container.export_mapping.name} {f'({container.export_mapping.type.value[0]})' if container.export_mapping.type.value[0] != '' else ''}", 
                       fontsize=7)

            ax.yaxis.set_major_formatter(ticker.FuncFormatter(container.export_mapping.type.value[2]))

            title = f"Experiment: {CommonSettings.experiment}, Series: {container.app_config.name}@{container.instance}, "
            title += f"Application: {container.export_mapping.name}@{container.app_config.application}"
            if container.export_mapping.title_suffix is not None:
                title += f" ({container.export_mapping.title_suffix})"

            basepath = path / container.instance / container.app_config.name

            if not basepath.exists():
                logger.debug(f"Creating output path '{basepath}'")
                os.makedirs(basepath, exist_ok=True)

            filename = basepath / f"{container.app_config.application}_{container.export_mapping.name}.{format}"

            plt.title(title, fontsize=7)
            plt.tight_layout()
            plt.savefig(filename)
            plt.close()
            logger.debug(f"Plot rendered to file: {filename}")#
            logger.success(f"Rendered Plot: instance={container.instance}, application={container.app_config.application}, app_mame={container.app_config.name}, type={container.type_name}, series={container.export_mapping.name}")

            return True

        return self._process_series(plot_export_callback)

    def output_to_flatfile(self, output_path: str) -> bool:
        path = Path(output_path)

        def flatfile_export_callback(container: SeriesContainer):
            basepath = path / container.instance / container.app_config.name

            if len(container.x) != len(container.y):
                logger.error(f"Exporting of {container.type_name} from series {container.export_mapping.name} failed: len(x) != len(y)")
                return False

            if not basepath.exists():
                logger.debug(f"Creating output path '{basepath}'")
                os.makedirs(basepath, exist_ok=True)
            
            filename = basepath / f"{container.app_config.application}_{container.export_mapping.name}.csv"

            with open(filename, "w") as handle:
                handle.write(f"time,{container.export_mapping.type.value[1]}\n")
                for index in range(0, len(container.x)):
                    handle.write(f"{container.x[index]},{container.y[index]}\n")

            logger.debug(f"CSV file rendered to file: {filename}")#
            logger.success(f"Exported CSV file: instance={container.instance}, application={container.app_config.application}, app_mame={container.app_config.name}, type={container.type_name}, series={container.export_mapping.name}")

            return True

        self._process_series(flatfile_export_callback)
