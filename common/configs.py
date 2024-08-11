from common.interfaces import JSONSerializer

class InfluxDBConfig(JSONSerializer):
    def __init__(self, database: str, series_name: str, host: str, disabled: bool = False, 
                 port: int = 8086, token: str = None, org: str = None):
        self.database = database
        self.series_name = series_name
        self.host = host
        self.port = port
        self.token = token
        self.org = org
        self.disabled = disabled
