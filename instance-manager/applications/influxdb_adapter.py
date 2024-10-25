from management_client import ManagementClient, DownstreamMassage
from common.instance_manager_message import InstanceStatus

class InfluxDBAdapter():
    def __init__(self, application_name: str, instance_name: str, manager: ManagementClient) -> None:
        self.application_name = application_name
        self.instance_name = instance_name
        self.manager = manager
    
    def add(self, series_name: str, points, additional_tags = None):
        if points is None:
            return

        data = [
            {
                "measurement": series_name,
                "tags": {
                    "application": self.application_name,
                    "instance": self.instance_name,
                },
                "fields": points
            }
        ]

        if additional_tags is not None:
            for k, v in additional_tags.items():
                data[0]["tags"][k] = v

        message: DownstreamMassage = DownstreamMassage(InstanceStatus.DATA_POINT, data)
        self.manager.send_to_server(message)
