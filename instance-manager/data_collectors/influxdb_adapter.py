from common.configs import InfluxDBConfig

class InfluxDBAdapter():
    def __init__(self, influxdb_config: InfluxDBConfig):
        self.influxdb_config = influxdb_config

        
        print("Init InfluxDB", vars(self.influxdb_config))

    def close(self):
        print("Close InfluxDB")
