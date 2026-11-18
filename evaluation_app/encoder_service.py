"""Serve CLAP text vectors on loopback with CPU PyTorch and no FAISS imports."""

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

from spotify.src.embeddings import Clap


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8062)
    parser.add_argument("--revision", help="Hugging Face checkpoint revision matching the FAISS index")
    args = parser.parse_args()
    encoder = Clap(device="cpu", revision=args.revision)

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self.reply(200, {"ready": True, "device": "cpu"})
            else:
                self.reply(404, {"error": "Unknown endpoint."})

        def do_POST(self):
            if self.path != "/embed":
                self.reply(404, {"error": "Unknown endpoint."})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 8192:
                    raise ValueError
                text = json.loads(self.rfile.read(size))["text"]
                if not isinstance(text, str) or not 0 < len(text.strip()) <= 1000:
                    raise ValueError
            except (TypeError, ValueError, KeyError):
                self.reply(400, {"error": "Supply a text request."})
                return
            vector = encoder.embed_text([text])[0].tolist()
            self.reply(200, {"vector": vector})

    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
