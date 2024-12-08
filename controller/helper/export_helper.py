from typing import List, Optional, Callable, Any
from loguru import logger
from dataclasses import dataclass

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
        self.reader = self.adapter.get_reader_client()
        if self.reader is None:
            raise Exception("Unable to create InfluxDB data reader")

        self.loader = ApplicationLoader(CommonSettings.app_base_path, testbed_package_path, 
                                        [""])
        self.loader.read_packaged_apps()

    
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

        database_entries = self.reader.get_list_database(tags={
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
            options = {k: v for k, v in map(lambda y: (y[0], y[1], ), map(lambda x: x.split("="), option_str))}
            result.append(ExportSubtype(type, options))
        
        return result

    def _process_series(self, export_callback: Callable) -> bool:
        for instance in self.config.instances:
            if instance.name in self.exclude_instances:
                logger.debug(f"Skipping instance '{instance.name}': Name in exclude list.")
                continue

            if instance.applications is None or len(instance.applications) != 0:
                logger.debug(f"Skipping instance '{instance.name}': No application configured.")
                continue

            for application in instance.applications:
                if application.application in self.exclude_applications:
                    logger.debug(f"Skipping application '{application.name}' of type '{application.application}' from instance '{instance.name}': Type in exclude list.")
                    continue

                if application.dont_store:
                    logger.debug(f"Skipping application '{application.name}' of type '{application.application}' from instance '{instance.name}': Data store disabled.")
                    continue

                logger.debug(f"Processing application '{application.name}' of type '{application.application}' from instance '{instance.name}'")
                app_cls = self._map_to_application_class(application)
                if app_cls is None:
                    return False
                
                app_instance: BaseApplication = app_cls()
                if not app_instance.exports_data():
                    logger.debug(f"Skipping application '{application.name}' of type '{application.application}': Does not export any data")
                    continue
                
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
                
                for subtype in subtypes:
                    try:
                        data_mappings = app_instance.get_export_mapping(subtype)
                        if data_mappings is None or len(data_mappings) == 0:
                            logger.warning(f"Application '{application.name}' of type '{application.application}' from instance '{instance.name}' does not define export outputs, even data exists.")
                            continue
                    except Exception as ex:
                        logger.opt(exception=ex).error(f"Error getting export mappings for application '{application.name}' of type '{application.application}' from instance '{instance.name}'")
                        return False
                    
                    for series in data_mappings:
                        bind_params = {
                            "experiment": CommonSettings.experiment,
                            "instance": instance.name,
                            "application": application.name
                        }
                        query_suffix = ""

                        for selector, value in series.additional_selectors.items():
                            bind_params[selector] = value
                            query_suffix += f" AND \"{selector}\" = ${selector}"
                        
                        query = f"SELECT \"{series.name}\" FROM \"{subtype.name}\" WHERE \"application\" = $application AND \"experiment\" = $experiment AND \"instance\" = $instance{query_suffix}"
                        
                        try:
                            points = self.reader.query(query, bind_params=bind_params).get_points()
                        except Exception as ex:
                            logger.opt(exception=ex).error(f"Unable to fetch series for '{series.name}' from '{subtype.name}'")
                            return False
                        
                        if points is None or len(points) == 0:
                            logger.warning(f"Query for '{series.name}' from '{subtype.name}' has not yield any results")
                            continue
                        
                        data_points = []
                        for point in points:
                            data_points.append((int(dateparser.parse(point["time"]).timestamp()), point[series.name]))

                        t_0 = min(map(lambda x: x[0], data_points))
                        x = []
                        y = []
                        for data_point in data_points:
                            x.append(data_point[0] - t_0 + application.delay)
                            y.append(data_point[1])
                        
                        series_container = SeriesContainer(
                            instance=instance.name,
                            app_config=application,
                            export_mapping=series,
                            type_name=subtype.name,
                            x=x,
                            y=y
                        )

                        export_callback(series_container)

        
    def output_to_plot(self, output_path: str, format: str = "pdf") -> bool:
        def plot_export_callback(conatiner: SeriesContainer):
            pass
        
        self._process_series(plot_export_callback)

    def output_to_flatfile(self, output_path: str) -> bool:
        def flatfile_export_callback(container: SeriesContainer):
            pass

        self._process_series(flatfile_export_callback)
