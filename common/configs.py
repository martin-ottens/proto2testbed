from common.interfaces import JSONSerializer

class InfluxDBConfig(JSONSerializer):
    def __init__(self, database: str, series_name: str, host: str, disabled: bool = False, 
                 port: int = 8086, user: str = None, password: str = None, 
                 timeout: int = 20, retries: int = 4):
        self.database = database
        self.series_name = series_name
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.disabled = disabled
        self.timeout = timeout
        self.retries = retries
