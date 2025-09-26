import ssl
import socket
import json
from telemetry_db import TelemetryDB
from cryptography.hazmat.primitives import serialization
from queue import Queue
import threading
import time
import logging
import os
import zlib
from typing import Dict, Any, List, Tuple

logging.basicConfig(filename='analytics_bridge.log', level=logging.INFO)

class AnalyticsBridge:
    def __init__(self, telemetry_db: TelemetryDB, cloud_host: str, port: int = 443):
        self.db = telemetry_db
        self.host = cloud_host
        self.port = port
        self.offline_queue = Queue(maxsize=1000)
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.client_cert = self._load_file('client_cert.pem')
        self.client_key = self._load_file('client_key.pem')
        self.ca_cert = self._load_file('ca_cert.pem')

    def _load_file(self, path: str) -> str:
        """Load PEM file or return empty string"""
        try:
            with open(path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            logging.warning(f"{path} not found, using empty placeholder")
            return ""

    def _create_secure_context(self) -> ssl.SSLContext:
        """Configure mutual TLS with strong ciphers"""
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        if self.ca_cert:
            context.load_verify_locations(cadata=self.ca_cert)
        if self.client_cert and self.client_key:
            context.load_cert_chain(certfile="client_cert.pem", keyfile="client_key.pem")
        context.set_ciphers("ECDHE-ECDSA-AES256-GCM-SHA384")
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        return context

    def sync_telemetry(self, force_full: bool = False):
        """Synchronize telemetry with cloud endpoint"""
        with self.lock:  # ensure single sync at a time
            try:
                with socket.create_connection((self.host, self.port), timeout=10) as sock:
                    with self._create_secure_context().wrap_socket(sock, server_hostname=self.host) as ssock:
                        payload = {
                            "last_sync": self.db.get_last_sync_timestamp(),
                            "schema_version": 1.2
                        }
                        ssock.sendall(json.dumps(payload).encode())
                        raw = ssock.recv(4096)
                        response = json.loads(raw.decode())

                        if response.get("delta_available") and not force_full:
                            self._send_delta(ssock, response["since"])
                        else:
                            self._send_full(ssock)
            except (ssl.SSLError, ConnectionError, TimeoutError, OSError) as e:
                logging.error(f"Sync failed: {e}, queuing for retry")
                try:
                    self.offline_queue.put_nowait(
                        ("delta" if not force_full else "full", time.time())
                    )
                except:
                    logging.warning("Offline queue full, dropping telemetry")

    def _send_delta(self, ssock: ssl.SSLSocket, since: float):
        records = self.db.get_telemetry_since(since)
        ssock.sendall(self._compress_records(records))

    def _send_full(self, ssock: ssl.SSLSocket):
        records = self.db.get_all_telemetry()
        ssock.sendall(self._compress_records(records))

    def _compress_records(self, records: List[Dict[str, Any]]) -> bytes:
        """Apply JSON serialization + zlib compression with checksum"""
        raw = json.dumps(records).encode()
        compressed = zlib.compress(raw, level=9)
        checksum = zlib.crc32(raw)
        package = {
            "compressed": True,
            "algo": "zlib",
            "checksum": checksum,
            "payload": compressed.hex()
        }
        return json.dumps(package).encode()

    def start_background_sync(self, interval: int = 300):
        def worker():
            while not self.stop_event.is_set():
                self.sync_telemetry()
                time.sleep(interval)
        threading.Thread(target=worker, daemon=True).start()

    def stop_background_sync(self):
        self.stop_event.set()


# Example usage
if __name__ == "__main__":
    db = TelemetryDB()
    bridge = AnalyticsBridge(db, "analytics.example.com")
    bridge.start_background_sync(interval=60)
    time.sleep(5)
    bridge.stop_background_sync()
