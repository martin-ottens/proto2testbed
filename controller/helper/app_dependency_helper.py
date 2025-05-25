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

from typing import List, Optional
from dataclasses import dataclass
from loguru import logger

from utils.settings import TestbedConfig, TestbedInstance
from common.application_configs import AppStartStatus, ApplicationConfig


@dataclass
class DeferredStartApplication:
    instance: str
    application: ApplicationConfig


@dataclass
class ReverseDependencyContainer:
    instance_name: str
    application_name: str
    after: AppStartStatus
    satisfied: bool = False


class ReverseApplicationDependency:
    def __init__(self, app: DeferredStartApplication) -> None:
        self.app = app
        self.reverse_depdendencies: List[ReverseDependencyContainer] = []

    def add_dependency(self, dependency: ReverseDependencyContainer) -> None:
        self.reverse_depdendencies.append(dependency)
    
    def satisfy_and_check(self, reporting_instance: str, reporting_app: str, 
                          after: AppStartStatus) -> Optional[DeferredStartApplication]:
        if all(map(lambda x: x.satisfied, self.reverse_depdendencies)):
            return None

        for dependecy in self.reverse_depdendencies:
            if not dependecy.instance_name == reporting_instance:
                continue
            
            if not dependecy.application_name == reporting_app:
                continue

            if not dependecy.after == after:
                continue

            dependecy.satisfied = True

        if all(map(lambda x: x.satisfied, self.reverse_depdendencies)):
            return self.app
        else:
            return None

class AppDependencyHelper:
    __PER_HOP_DELAY_OFFSET = 1

    def __init__(self, config: TestbedConfig) -> None:
        self.config = config
        self.dependencies: List[ReverseApplicationDependency] = None

        self.graph = nx.DiGraph()
        self.start_init: List[ApplicationConfig] = []
        self.daemon_apps: List[ApplicationConfig] = []

        # Collecting graph nodes
        for instance in self.config.instances:
            if instance.applications is None:
                continue

            for app in instance.applications:
                self.graph.add_node(app)

                if app.runtime is None:
                    self.daemon_apps.append(app)

                if not app.depends:
                    self.start_init.append(app)

        # Building graph edges
        for instance in self.config.instances:
            if instance.applications is None:
                continue

            for app in instance.applications:
                if app.depends:
                    for app_start in app.depends:
                        app_name = f"{app.name}@{instance.name}"

                        instance_config: TestbedInstance = next((x for x in self.config.instances if x.name == app_start.instance), None)
                        if instance_config is None or instance_config.applications is None:
                            raise Exception(f"Application {app_name} depends on {app_start.instance}, but this Instance does not exist.")

                        app_config: ApplicationConfig =  next((x for x in instance_config.applications if x.name == app_start.application), None)
                        if app_config is None:
                            raise Exception(f"Application {app_name} depends on {app_start.application}@{app_start.instance}, but this Application does not exist.")

                        app_start_name = f"{app_start.application}@{app_start.instance}"

                        if not self.graph.has_node(app_config):
                            raise Exception(f"Application {app_name} depends on {app_start_name}, but this Application does not exist.")

                        if app_start.at == AppStartStatus.FINISH and app_config in self.daemon_apps:
                            raise Exception(f"Application {app_start_name} is a daemon Application, cannot start {app_name} after its finished.")

                        self.graph.add_edge(app_config, app)
        
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
        
        # Fallback check without pretty print
        if not nx.is_directed_acyclic_graph(self.graph):
            raise Exception(f"Dependecy graph must be a DAG, but is not.")


    def get_maximum_runtime(self) -> int:
        if set(self.daemon_apps) == set(self.graph.nodes):
            return 0

        start_nodes = [n for n in self.graph.nodes if self.graph.in_degree(n) == 0]
        end_nodes = [n for n in self.graph.nodes if self.graph.out_degree(n) == 0]

        paths = []
        for start in start_nodes:
            for end in end_nodes:
                path = list(nx.all_simple_paths(self.graph, source=start, target=end))
                paths.extend(path)

        max_runtime = 0

        for path in paths:
            runtime = 0
            for index, node in enumerate(path):
                app: ApplicationConfig = node
                if index == 0:
                    if app.depends is None or len(app.depends) != 0:
                        raise Exception("In-Node if DAG cannot have dependencies!")
                else:
                    start_type = None
                    prev_runtime = None

                    prev_app: ApplicationConfig = path[index - 1]
                    prev_instance_config: Optional[TestbedInstance] = None
                    for instance in self.config.instances:
                        if instance.applications is None:
                            continue

                        for application in instance.applications:
                            if prev_app == application:
                                prev_instance_config = instance
                                break

                    if prev_instance_config is None:
                        raise Exception(f"Unable to lookup owner of Application '{prev_app}'")
                        
                    for dependency in app.depends:
                        if dependency.application == prev_app.name and dependency.instance == prev_instance_config.name:
                            start_type = dependency.at
                            prev_runtime = prev_app.runtime
                            break
                    
                    if start_type is None:
                        raise Exception(f"Unable to resolve dependency from '{node}' back to '{path[index -1]}'")

                    if start_type == AppStartStatus.START and prev_runtime is not None:
                    # Case 1: depends to previous node is "started"
                    #         -> Delete previous runtime from runtime sum
                        runtime -= prev_runtime
                    elif start_type == AppStartStatus.FINISH and prev_runtime is None:
                    # Case 2: depends to previous node is "finished"
                    #         -> previous runtime has to be != None
                        raise Exception(f"Daemon process cannot finish, invalid dependency!")
                    
                    # Add 1s offset per hop
                    runtime += AppDependencyHelper.__PER_HOP_DELAY_OFFSET

                if app.runtime is not None:
                    runtime += app.runtime
                    
                if app.delay is not None:
                    runtime += app.delay

            max_runtime = max(max_runtime, runtime)

        return max_runtime

    def compile_dependency_list(self) -> List[DeferredStartApplication]:
        self.dependencies = []
        instant_start: List[DeferredStartApplication] = []

        for instance in self.config.instances:
            if instance.applications is None:
                continue

            for app in instance.applications:
                deferred_app = DeferredStartApplication(instance.name, app)

                if app.depends:
                    reverse_dependencies = ReverseApplicationDependency(deferred_app)
                    for app_start in app.depends:
                        dependency = ReverseDependencyContainer(
                            application_name=app_start.application, 
                            instance_name=app_start.instance, 
                            after=app_start.at)

                        reverse_dependencies.add_dependency(dependency)
                    self.dependencies.append(reverse_dependencies)
                else:
                    instant_start.append(deferred_app)

        logger.debug(f"Application Dependency List: {len(instant_start)} start inital, {len(self.dependencies)} deferred.")
        return instant_start

    def get_next_applications(self, reporting_instance: str, 
                              reporting_app: str, state: AppStartStatus) -> List[DeferredStartApplication]:
        result_list: List[DeferredStartApplication] = []

        for dependency in self.dependencies:
            app = dependency.satisfy_and_check(reporting_instance, reporting_app, state)
            if app is not None:
                logger.trace(f"Application ready: '{app.application}@{app.instance}', caused by '{reporting_app}@{reporting_instance}' in state '{state}'.")
                result_list.append(app)
        
        return result_list
