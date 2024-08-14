from influxdb import InfluxDBClient

from common.configs import InfluxDBConfig

class InfluxDBAdapter():
    def __init__(self, influxdb_config: InfluxDBConfig, collector_name: str, instance_name: str):
        self.influxdb_config = influxdb_config
        self.collector_name = collector_name
        self.instance_name = instance_name
        
        if influxdb_config.disabled:
            self.client = None
        elif influxdb_config.user is not None:
            self.client = InfluxDBClient(host=influxdb_config.host, port=influxdb_config.port,
                                         user=influxdb_config.user, password=influxdb_config.password,
                                         retries=influxdb_config.retries, timeout=influxdb_config.timeout)
            self.client.switch_database(influxdb_config.database)
        else:
            self.client = InfluxDBClient(host=influxdb_config.host, port=influxdb_config.port,
                                         retries=influxdb_config.retries, timeout=influxdb_config.timeout)
            self.client.switch_database(influxdb_config.database)
    
    def add(self, series_name: str, points, additional_tags = None):
        if points is None:
            return

        if self.client is None:
            points_as_str = ", ".join(list(map(lambda x: f"{x[0]}={x[1]}", points.items())))
            print(f"DATA {series_name}@{self.collector_name} {f'({additional_tags})' if additional_tags is not None else ''}): {points_as_str}", flush=True)
            return

        data = [
            {
                "measurement": series_name,
                "tags": {
                    "collector": self.collector_name,
                    "instance": self.instance_name,
                    "experiment": self.influxdb_config.series_name
                },
                "fields": points
            }
        ]

        if additional_tags is not None:
            for k, v in additional_tags.items():
                data[0]["tags"][k] = v

        self.client.write_points(data)

    def close(self):
        if self.client is not None:
            self.client.close()
