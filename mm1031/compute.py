"""ComputeProvider layer: the open-core compute tiers.

Every smart feature goes through this interface, never a model directly.
Tiers (see 附篇 B):
  T0 local-basic  : pure algorithms, zero compute requirement, offline
  T1/T2/T3 endpoint: any OpenAI-compatible endpoint - local MLX/Ollama,
                    the user's own GPU box, a third-party API key, or the
                    official Guicang Cloud. Cloud is just a managed endpoint.
A chain tries providers in route order and falls back automatically;
every result carries its compute provenance (provider, model, cost).
"""
import json
import os
import re
import urllib.request
from collections import Counter


class ComputeError(Exception):
    pass


class Result:
    def __init__(self, text, provider, model="", cost_units=0):
        self.text = text
        self.provider = provider
        self.model = model
        self.cost_units = cost_units

    def provenance(self):
        return {
            "provider": self.provider,
            "model": self.model,
            "cost_units": self.cost_units,
        }


class LocalBasicProvider:
    """T0: extractive summary + keyword tags. No model, no network."""

    name = "local-basic"
    model = "extractive-v1"

    def summarize(self, text):
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            raise ComputeError("empty text")
        head = lines[0]
        summary = head[:140]
        tokens = re.findall(r"[A-Za-z0-9_]+", text.lower())
        chars = re.findall(r"[一-鿿]", text)
        bigrams = [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]
        top = [w for w, _ in Counter(tokens + bigrams).most_common(5)]
        if top:
            summary += " ｜ 关键词：" + "、".join(top)
        return Result(summary, self.name, self.model, 0)


class EndpointProvider:
    """Any OpenAI-compatible endpoint (T1 local / T2 BYO / T3 cloud)."""

    def __init__(self, name, base_url, model, api_key=None, timeout=20):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def summarize(self, text):
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": "用一句话概括以下内容，并给出3个关键词：\n" + text[:4000],
                }
            ],
        }
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        if self.api_key:
            req.add_header("Authorization", "Bearer " + self.api_key)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            raise ComputeError(f"{self.name} unreachable: {e}")
        try:
            content = data["choices"][0]["message"]["content"].strip()
        except Exception:
            raise ComputeError(f"{self.name} bad response shape")
        cost = (data.get("usage") or {}).get("total_tokens", 0)
        return Result(content, self.name, self.model, cost)


class ComputeChain:
    def __init__(self, providers):
        self.providers = providers

    def summarize(self, text):
        errors = []
        for p in self.providers:
            try:
                return p.summarize(text)
            except ComputeError as e:
                errors.append(str(e))
        raise ComputeError("all providers failed: " + "; ".join(errors))


def build_chain(config, feature="summarize"):
    """config: parsed JSON dict (see mm1031.config.example.json)."""
    compute = (config or {}).get("compute") or {}
    specs = {p["name"]: p for p in compute.get("providers") or []}
    routes = (compute.get("routes") or {}).get(feature) or ["local-basic"]
    providers = []
    for name in routes:
        spec = specs.get(name) or {"type": "local-basic", "name": "local-basic"}
        if spec.get("type") == "endpoint":
            key = spec.get("api_key") or os.environ.get(
                spec.get("api_key_env") or "", ""
            )
            providers.append(
                EndpointProvider(
                    name,
                    spec.get("base_url", ""),
                    spec.get("model", ""),
                    key or None,
                )
            )
        else:
            providers.append(LocalBasicProvider())
    return ComputeChain(providers)


def load_config(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}
