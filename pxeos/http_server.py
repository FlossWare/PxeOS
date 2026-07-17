"""Lightweight HTTPS server for autoinstall file serving."""

from __future__ import annotations

import ssl
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Optional

from pxeos.engine import ProvisioningEngine


class _AutoinstallHandler(SimpleHTTPRequestHandler):

    engine: Optional[ProvisioningEngine] = None

    def do_GET(self) -> None:
        if self.path.startswith("/autoinstall/"):
            self._serve_autoinstall()
        elif self.path.startswith("/boot/"):
            self._serve_boot_script()
        elif self.path == "/health":
            self._respond(200, "ok")
        else:
            self._respond(404, "not found")

    def _serve_autoinstall(self) -> None:
        mac = self.path.split("/autoinstall/", 1)[-1]
        mac = mac.strip("/")
        if not mac or self.engine is None:
            self._respond(400, "missing mac or engine")
            return
        try:
            content = self.engine.get_autoinstall(mac)
            self._respond(200, content, "text/plain")
        except ValueError as exc:
            self._respond(404, str(exc))

    def _serve_boot_script(self) -> None:
        mac = self.path.split("/boot/", 1)[-1]
        mac = mac.strip("/")
        if not mac or self.engine is None:
            self._respond(400, "missing mac or engine")
            return
        try:
            content = self.engine.render_ipxe_script(mac)
            self._respond(200, content, "text/plain")
        except ValueError as exc:
            self._respond(404, str(exc))

    def _respond(
        self,
        code: int,
        body: str,
        content_type: str = "text/plain",
    ) -> None:
        encoded = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(
        self, format: str, *args: object
    ) -> None:
        pass


class AutoinstallServer:

    def __init__(
        self,
        engine: ProvisioningEngine,
        host: str = "0.0.0.0",
        port: int = 8443,
        tls_cert: Optional[Path] = None,
        tls_key: Optional[Path] = None,
    ) -> None:
        self._engine = engine
        self._host = host
        self._port = port
        self._tls_cert = tls_cert
        self._tls_key = tls_key
        self._server: Optional[HTTPServer] = None

    def start(self) -> None:
        _AutoinstallHandler.engine = self._engine

        self._server = HTTPServer(
            (self._host, self._port), _AutoinstallHandler
        )

        if self._tls_cert and self._tls_key:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(
                str(self._tls_cert), str(self._tls_key)
            )
            self._server.socket = ctx.wrap_socket(
                self._server.socket, server_side=True
            )

        self._server.serve_forever()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
