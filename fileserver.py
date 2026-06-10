#!/usr/bin/env python3
"""
Serves the trading dashboard and trades.csv from the VPS.
- GET /           → dashboard/index.html
- GET /trades.csv → logs/trades.csv (live, no cache)
Port: 8888
"""
import http.server
import os

PORT      = 8888
BASE_DIR  = "/root/stock-trading-agent-v2"
LOGS_DIR  = os.path.join(BASE_DIR, "logs")
DASH_FILE = os.path.join(BASE_DIR, "dashboard", "index.html")

class Handler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        path = self.path.split("?")[0]

        if path in ("/", "/index.html", "/dashboard"):
            self._serve_file(DASH_FILE, "text/html")
        elif path == "/trades.csv":
            self._serve_file(os.path.join(LOGS_DIR, "trades.csv"), "text/csv")
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_file(self, filepath, content_type):
        if not os.path.exists(filepath):
            self.send_response(404)
            self.end_headers()
            return
        with open(filepath, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    with http.server.HTTPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Dashboard running at http://72.61.233.142:{PORT}")
        httpd.serve_forever()
