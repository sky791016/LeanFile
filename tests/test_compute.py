import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from guicang.compute import (
    ComputeChain,
    EndpointProvider,
    LocalBasicProvider,
    build_chain,
)

TEXT = "归藏是一款管理 AI 生成资产的开源应用。\n它用内容哈希确定资产身份，用版本图代替文件名管理版本。"


class FakeOpenAI(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        body = {
            "choices": [{"message": {"content": "一句话摘要：资产身份与版本管理。"}}],
            "usage": {"total_tokens": 42},
        }
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


def run():
    # T0 works fully offline
    r = LocalBasicProvider().summarize(TEXT)
    assert r.provider == "local-basic" and "归藏" in r.text

    # endpoint provider against a local fake OpenAI-compatible server
    server = HTTPServer(("127.0.0.1", 0), FakeOpenAI)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ep = EndpointProvider("my-a800", f"http://127.0.0.1:{port}/v1", "qwen-test")
    r2 = ep.summarize(TEXT)
    assert r2.text.startswith("一句话摘要") and r2.cost_units == 42

    # chain falls back when the first provider is a dead endpoint
    dead = EndpointProvider("dead", "http://127.0.0.1:9/v1", "x", timeout=2)
    chain = ComputeChain([dead, LocalBasicProvider()])
    r3 = chain.summarize(TEXT)
    assert r3.provider == "local-basic"

    # config-driven chain: cloud/bYO are just endpoints; local-basic兜底
    cfg = {
        "compute": {
            "providers": [
                {"name": "local-basic", "type": "local-basic"},
                {
                    "name": "guicang-cloud",
                    "type": "endpoint",
                    "base_url": "http://127.0.0.1:9/v1",
                    "model": "guicang-summary",
                },
            ],
            "routes": {"summarize": ["guicang-cloud", "local-basic"]},
        }
    }
    r4 = build_chain(cfg).summarize(TEXT)
    assert r4.provider == "local-basic"

    server.shutdown()
    print("COMPUTE TESTS PASSED")


if __name__ == "__main__":
    run()
