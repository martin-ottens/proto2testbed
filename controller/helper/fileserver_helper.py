from http.server import HTTPServer as BaseHTTPServer, SimpleHTTPRequestHandler
from loguru import logger

import os
import threading

class HTTPHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        path = SimpleHTTPRequestHandler.translate_path(self, path)
        relpath = os.path.relpath(path, os.getcwd())
        fullpath = os.path.join(self.server.base_path, relpath)
        return fullpath

    def log_error(self, format, *args) -> None:
        logger.error(f"FileServer Error: {self.address_string()} -> {format % args}")

    def log_message(self, format, *args):
        logger.debug(f"FileServer Request: {self.address_string()} -> {format % args}")

class HTTPServer(BaseHTTPServer):
    def __init__(self, base_path, server_address, RequestHandlerClass=HTTPHandler):
        self.base_path = base_path
        self._stop_event = threading.Event()
        BaseHTTPServer.__init__(self, server_address, RequestHandlerClass)

    def serve(self, poll_interval: int = 0.5):
        self.timeout = poll_interval
        logger.info(f"FileServer serving '{self.base_path}' at {self.server_address[0]}:{self.server_address[1]}")
        while not self._stop_event.is_set():
            self.handle_request()
        logger.info(f"FileServer was stopped")

    def serve_stop(self):
        self._stop_event.set()

class FileServer():
    def __init__(self, path, bind_address, poll_interval = 0.5):
        self.server = HTTPServer(path, bind_address)
        self.thread = threading.Thread(target=self.server.serve, 
                                       args=(poll_interval, ),
                                       daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.serve_stop()
        self.thread.join()
