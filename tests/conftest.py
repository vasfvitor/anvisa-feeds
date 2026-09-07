"""A Client whose transport answers from recorded ANVISA responses (copied from the anvisa
repo's fixtures; public data)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from anvisa import Client, Credentials
from anvisa.throttle import Throttle

FIXTURES = Path(__file__).parent / "fixtures"

ROUTES = {
    ("GET", "/api/v1/fila/areafila"): "areafila.json",
    ("GET", "/api/v1/fila/8/fila"): "fila_grupos.json",
    ("GET", "/api/v1/fila/285/subfila"): "subfilas.json",
    ("GET", "/api/v1/fila/281/subfila"): "subfilas_281.json",
}
QUEUES = {167: "fila_consulta.json", 161: "fila_consulta_161.json"}


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeApi:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/consultas-externas-api")
        headers = {"X-RateLimit-Remaining": "24"}
        if path.endswith("/token"):
            return httpx.Response(200, json=load("token.json"))
        if path == "/api/v1/fila/consulta":
            sub = json.loads(request.read())["filter"]["subfila"]
            if sub in QUEUES:
                return httpx.Response(200, json=load(QUEUES[sub]), headers=headers)
            return httpx.Response(404, headers=headers)  # an empty queue: empty-bodied 404
        name = ROUTES.get((request.method, path))
        if name:
            return httpx.Response(200, json=load(name), headers=headers)
        if request.method == "GET" and path.endswith("/subfila"):
            return httpx.Response(200, json=[], headers=headers)  # grupo without subfilas
        return httpx.Response(404, json={"error": path})


@pytest.fixture
def fake_api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def client(fake_api: FakeApi) -> Client:
    with Client(
        Credentials("id", "secret"),
        transport=httpx.MockTransport(fake_api.handler),
        throttle=Throttle(sleep=lambda s: None),
    ) as c:
        yield c
