#!/usr/bin/env python3
"""
Simple CORS-enabled file server for trading dashboard.
Serves /root/stock-trading-agent-v2/logs/ on port 8888.
"""
import http.server
import os

PORT = 8888
SERVE_DIR = "/root/stock-trading-agent-v2/logs"

class CORSHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SERVE_DIR, **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def log_message(self, format, *args):
        pass  # silence request logs

if __name__ == "__main__":
    os.chdir(SERVE_DIR)
    with http.server.HTTPServer(("0.0.0.0", PORT), CORSHandler) as httpd:
        print(f"Serving {SERVE_DIR} on port {PORT}")
        httpd.serve_forever()
