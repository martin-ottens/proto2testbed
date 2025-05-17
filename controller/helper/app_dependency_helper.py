#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2024-2025 Martin Ottens
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

import networkx as nx

from typing import List, Dict
from dataclasses import dataclass

from utils.settings import TestbedConfig
from common.application_configs import StartAppAfter


@dataclass
class DeferredStartApplication:
    instance: str
    application: str


@dataclass
class ReverseDependencyContainer:
    name: str
    after: StartAppAfter
    satisfied: bool = False


class ReverseApplicationDependency:
    def __init__(self, app: DeferredStartApplication) -> None:
        self.app = app
        self.reverse_depdendencies: Dict[str, ReverseDependencyContainer] = {}

    def add_dependency(self, dependency: str, after: StartAppAfter) -> None:
        self.reverse_depdendencies[dependency] = ReverseDependencyContainer(
            name=dependency,
            after=after
        )
    
    def satisfy_and_check(self, dependecy: str, after: StartAppAfter) -> bool:
        if dependecy not in self.reverse_depdendencies.keys():
            return False
        
        reverse_dependency = self.reverse_depdendencies[dependecy]
        if reverse_dependency.after != after or reverse_dependency.satisfied:
            return False
        
        reverse_dependency.satisfied = True

        return all(map(lambda x: x.satisfied, self.reverse_depdendencies.values()))

class AppDependencyHelper:
    def __init__(self, config: TestbedConfig) -> None:
        self.config = config
        self.dependencies: List[ReverseApplicationDependency] = None

        self.graph = nx.DiGraph()
        self.start_init: List[str] = []
        self.daemon_apps: List[str] = []

        # Collecting graph nodes
        for instance in self.config.instances:
            if instance.applications is None:
                continue

            for app in instance.applications:
                app_name = f"{app.name}@{instance.name}"
                self.graph.add_node(app_name)

                if app.runtime is None:
                    self.daemon_apps.append(app_name)

                if not app.depends:
                    self.start_init.append(app_name)

        # Building graph edges
        for instance in self.config.instances:
            if instance.applications is None:
                continue

            for app in instance.applications:
                app_name = f"{app.name}@{instance.name}"
                
                if app.depends:
                    for app_start in app.depends:
                        app_start_name = f"{app_start.application}@{app_start.instance}"

                        if not self.graph.has_node(app_start_name):
                            raise Exception(f"Application {app_name} depends on {app_start_name}, but this application does not exist.")

                        if app_start.at == StartAppAfter.FINISH and app_start_name in self.daemon_apps:
                            raise Exception(f"Application {app_start_name} is a daemon application, cannot start {app_name} after its finished.")

                        self.graph.add_edge(app_start_name, app_name)
        
        # Checking graph
        reachable_nodes = set()
        for start_init_app in self.start_init:
            reachable_nodes.add(start_init_app)
            reachable_nodes.update(nx.descendants(self.graph, start_init_app))

        all_nodes = set(self.graph.nodes)
        if reachable_nodes != all_nodes:
            raise Exception(f"Some nodes are not reachable by start condition: {all_nodes - reachable_nodes}, disconnected subgraph?")

        try:
            graph_cycle = list(nx.find_cycle(self.graph, orientation='original'))
            if graph_cycle is not None:
                raise Exception(f"Application dependency graph has at least one cyle: {graph_cycle}")
        except Exception:
            pass

    def compile_dependency_list(self) -> List[DeferredStartApplication]:
        self.dependencies = []
        instant_start: List[DeferredStartApplication] = []

        for instance in self.config.instances:
            if instance.applications is None:
                continue

            for app in instance.applications:
                deferred_app = DeferredStartApplication(instance.name, app.name)
                reverse_dependencies = ReverseApplicationDependency(deferred_app)

                if app.depends:
                    for app_start in app.depends:
                        reverse_dependencies.add_dependency(f"{app_start.application}@{app_start.instance}", app_start.at)
                    self.dependencies.append(reverse_dependencies)
                else:
                    instant_start.append(deferred_app)
                    del reverse_dependencies

    def get_next_applications(self, instance_finished: str, 
                              app_finished: str, state: StartAppAfter) -> List[DeferredStartApplication]:
        app_str = f"{app_finished}@{instance_finished}"
        result_list: List[DeferredStartApplication] = []

        for dependency in self.dependencies:
            if dependency.satisfy_and_check(app_str, state):
                result_list.append(dependency.app)
        
        return result_list
