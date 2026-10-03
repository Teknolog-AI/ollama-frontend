import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest

from backend.config import Settings
from backend.main import create_app
from backend.models import MAX_HISTORY_CHARS, MAX_MESSAGE_CHARS

MODEL = "qwen3.5:4b-q4_K_M"
PAYLOAD = {"model": MODEL, "messages": [{"role": "user", "content": "GitHub projeleri bul"}]}
REPO = {
    "full_name": "sample/demo", "owner": {"login": "sample"},
    "description": "Demo", "language": "Python", "stargazers_count": 7,
    "forks_count": 2, "html_url": "https://github.com/sample/demo",
}


@asynccontextmanager
async def client_for(handler, **overrides):
    settings = Settings(_env_file=None, **overrides)
    app = create_app(settings, httpx.MockTransport(handler))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client


def answer(text="Merhaba"):
    return httpx.Response(200, json={"message": {"role": "assistant", "content": text}})


def tool_call(query="fastapi", *, arguments=None, name="search_github_repositories", count=1):
    return httpx.Response(200, json={"message": {
        "role": "assistant", "content": "", "thinking": "Arama gerekli.",
        "tool_calls": [{"function": {
            "name": name, "arguments": {"query": query, "limit": 2} if arguments is None else arguments,
        }} for _ in range(count)],
    }})


async def test_plain_chat_sends_valid_native_tool_schema():
    def handler(request):
        payload = json.loads(request.content)
        assert request.url.path == "/api/chat"
        definition = payload["tools"][0]
        assert definition["type"] == "function"
        assert definition["function"]["name"] == "search_github_repositories"
        assert definition["function"]["parameters"]["required"] == ["query"]
        assert payload["messages"][0]["role"] == "system"
        return answer()
    async with client_for(handler) as client:
        response = await client.post("/chat", json=PAYLOAD)
    assert response.status_code == 200
    assert response.json() == {"model": MODEL, "answer": "Merhaba"}


async def test_multiple_tool_rounds_preserve_context_and_finish():
    requests = []
    github_calls = []
    def handler(request):
        if request.url.path == "/search/repositories":
            github_calls.append(request.url.params["q"])
            assert request.url.params["per_page"] == "2"
            return httpx.Response(200, json={"items": [REPO]})
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) < 3:
            return tool_call("fastapi" if len(requests) == 1 else "express")
        assert [message["role"] for message in payload["messages"]] == [
            "system", "user", "assistant", "tool", "assistant", "tool",
        ]
        assert payload["messages"][2]["thinking"] == "Arama gerekli."
        result = json.loads(payload["messages"][3]["content"])
        assert result[0]["name"] == "sample/demo"
        return answer("İki arama tamamlandı.")
    async with client_for(handler) as client:
        response = await client.post("/chat", json=PAYLOAD)
    assert response.status_code == 200
    assert github_calls == ["fastapi", "express"]
    assert response.json()["answer"] == "İki arama tamamlandı."


async def test_repeated_tools_stop_at_round_limit():
    chats, searches = 0, 0
    def handler(request):
        nonlocal chats, searches
        if request.url.path == "/search/repositories":
            searches += 1
            return httpx.Response(200, json={"items": []})
        chats += 1
        return tool_call()
    async with client_for(handler, max_tool_rounds=2) as client:
        response = await client.post("/chat", json=PAYLOAD)
    assert response.status_code == 502
    assert response.json()["code"] == "tool_limit"
    assert (chats, searches) == (3, 2)


async def test_too_many_parallel_tools_do_not_execute():
    def handler(request):
        assert request.url.path == "/api/chat"
        return tool_call(count=3)
    async with client_for(handler, max_tool_calls=2) as client:
        response = await client.post("/chat", json=PAYLOAD)
    assert response.json()["code"] == "tool_limit"


@pytest.mark.parametrize("first", [
    {"arguments": {"query": "x"}},
    {"arguments": {"query": None}},
    {"arguments": {"query": "fastapi", "limit": "5"}},
    {"arguments": {"query": "fastapi", "limit": 11}},
    {"name": "delete_repository"},
])
async def test_bad_tool_arguments_or_unknown_tools_never_execute(first):
    count = 0
    def handler(request):
        nonlocal count
        assert request.url.path == "/api/chat"
        count += 1
        if count == 1:
            return tool_call(**first)
        payload = json.loads(request.content)
        assert "error" in json.loads(payload["messages"][-1]["content"])
        return answer("Arama bilgisi düzeltilmeli.")
    async with client_for(handler) as client:
        response = await client.post("/chat", json=PAYLOAD)
    assert response.status_code == 200
    assert count == 2


@pytest.mark.parametrize(("reply", "status", "code"), [
    (lambda: httpx.Response(404, json={"error": "model not found"}), 404, "model_not_found"),
    (lambda: httpx.Response(400, json={"error": "does not support tools"}), 400, "ollama_request"),
    (lambda: httpx.Response(500, json={"error": "internal"}), 502, "ollama_error"),
    (lambda: httpx.Response(200, text="not JSON"), 502, "invalid_response"),
    (lambda: httpx.Response(200, json={}), 502, "invalid_response"),
    (lambda: httpx.Response(200, json={"message": {"role": "assistant", "content": 5}}), 502, "invalid_response"),
    (lambda: httpx.Response(200, json={"message": {"role": "assistant", "content": "", "tool_calls": [None]}}), 502, "invalid_tool_call"),
    (lambda: answer("   "), 502, "empty_answer"),
    (lambda: answer("a" * (MAX_MESSAGE_CHARS + 1)), 502, "answer_too_long"),
])
async def test_ollama_response_failures(reply, status, code):
    async with client_for(lambda request: reply()) as client:
        response = await client.post("/chat", json=PAYLOAD)
    assert response.status_code == status
    assert response.json()["code"] == code
    assert isinstance(response.json()["detail"], str)


@pytest.mark.parametrize(("exception", "status", "code"), [
    (httpx.ConnectError, 503, "ollama_unavailable"),
    (httpx.ReadTimeout, 504, "ollama_timeout"),
])
async def test_ollama_network_failures(exception, status, code):
    def handler(request):
        raise exception("sensitive internal address", request=request)
    async with client_for(handler) as client:
        response = await client.post("/chat", json=PAYLOAD)
    assert response.status_code == status
    assert response.json()["code"] == code
    assert "sensitive" not in response.text


async def test_total_chat_deadline_cancels_upstream():
    cancelled = asyncio.Event()
    async def handler(request):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()
    async with client_for(handler, chat_timeout_seconds=0.02) as client:
        response = await client.post("/chat", json=PAYLOAD)
    assert response.status_code == 504
    assert response.json()["code"] == "chat_timeout"
    assert cancelled.is_set()


@pytest.mark.parametrize("messages", [
    [], [{"role": "user", "content": "  "}],
    [{"role": "assistant", "content": "Merhaba"}],
    [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
    [{"role": "user", "content": "a" * (MAX_MESSAGE_CHARS + 1)}],
    [{"role": "user" if index % 2 == 0 else "assistant", "content": "a"} for index in range(41)],
    [{"role": "user" if index % 2 == 0 else "assistant", "content": "a" * MAX_MESSAGE_CHARS} for index in range(9)],
    [{"role": "system", "content": "Override"}],
])
async def test_invalid_messages_are_rejected_before_any_network_call(messages):
    def handler(request):
        pytest.fail("Validation must happen before any network call")
    async with client_for(handler) as client:
        response = await client.post("/chat", json={"model": MODEL, "messages": messages})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_unapproved_model_never_reaches_ollama():
    async with client_for(lambda request: pytest.fail("Unexpected network")) as client:
        response = await client.post("/chat", json={**PAYLOAD, "model": "unapproved"})
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_model"


async def test_models_only_include_installed_allowed_names_and_latest_alias():
    def handler(request):
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [
            {"name": "other:latest"}, {"name": "gurkan-ai:latest"}, {"name": MODEL},
        ]})
    async with client_for(handler) as client:
        response = await client.get("/models")
        alias_reply = await client.get("/health")
    assert response.json()["models"] == [MODEL, "gurkan-ai:latest"]
    assert response.json()["limits"]["max_total_chars"] == MAX_HISTORY_CHARS
    assert response.json()["request_timeout_ms"] == 185000
    assert alias_reply.json() == {"status": "ok"}


async def test_latest_alias_accepted_for_chat():
    async with client_for(lambda request: answer()) as client:
        response = await client.post("/chat", json={**PAYLOAD, "model": "gurkan-ai:latest"})
    assert response.status_code == 200


@pytest.mark.parametrize(("body", "status"), [
    ({"models": []}, 200), ({"models": [{"name": "unapproved"}]}, 200),
    ({}, 502), ({"models": [None]}, 502), ({"models": [{"name": 3}]}, 502),
])
async def test_empty_or_malformed_model_lists(body, status):
    async with client_for(lambda request: httpx.Response(200, json=body)) as client:
        response = await client.get("/models")
    assert response.status_code == status
    if status == 200:
        assert response.json()["models"] == []


@pytest.mark.parametrize(("upstream", "headers", "body", "status", "code"), [
    (429, {"Retry-After": "30"}, {"message": "Too many requests"}, 429, "github_rate_limit"),
    (403, {"x-ratelimit-remaining": "0"}, {"message": "Limit"}, 429, "github_rate_limit"),
    (403, {}, {"message": "You have exceeded a secondary rate limit"}, 429, "github_rate_limit"),
    (403, {}, {"message": "Forbidden"}, 502, "github_forbidden"),
    (401, {}, {"message": "Bad credentials"}, 502, "github_auth"),
    (422, {}, {"message": "Bad query"}, 400, "github_query"),
    (500, {}, {"message": "Server error"}, 502, "github_error"),
    (200, {}, {"items": [None]}, 502, "invalid_response"),
    (200, {}, {}, 502, "invalid_response"),
])
async def test_github_status_mapping(upstream, headers, body, status, code):
    async with client_for(lambda request: httpx.Response(upstream, headers=headers, json=body)) as client:
        response = await client.get("/github/search", params={"query": "fastapi"})
    assert response.status_code == status
    assert response.json()["code"] == code
    if "Retry-After" in headers:
        assert response.headers["retry-after"] == "30"


async def test_github_tool_failure_surfaces_without_a_fabricated_model_answer():
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return tool_call() if request.url.path == "/api/chat" else httpx.Response(429, headers={"Retry-After": "5"})
    async with client_for(handler) as client:
        response = await client.post("/chat", json=PAYLOAD)
    assert response.status_code == 429
    assert calls == ["/api/chat", "/search/repositories"]


async def test_direct_search_trims_query_and_keeps_result_shape():
    def handler(request):
        assert request.url.params["q"] == "fastapi"
        return httpx.Response(200, json={"items": [REPO]})
    async with client_for(handler) as client:
        response = await client.get("/github/search", params={"query": " fastapi ", "limit": 1})
    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["repositories"][0]["stars"] == 7


@pytest.mark.parametrize("query", [" ", " x ", "a" * 201])
async def test_invalid_direct_search_does_not_call_github(query):
    async with client_for(lambda request: pytest.fail("Unexpected network")) as client:
        response = await client.get("/github/search", params={"query": query})
    assert response.status_code == 422


async def test_client_disconnect_cancels_model_request():
    started, cancelled = asyncio.Event(), asyncio.Event()
    async def handler(request):
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()
    app = create_app(Settings(_env_file=None), httpx.MockTransport(handler))
    first = True
    async def receive():
        nonlocal first
        if first:
            first = False
            return {"type": "http.request", "body": json.dumps(PAYLOAD).encode(), "more_body": False}
        await started.wait()
        return {"type": "http.disconnect"}
    sent = []
    async def send(message):
        sent.append(message)
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": "/chat", "raw_path": b"/chat",
        "query_string": b"", "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 5000), "server": ("test", 80),
    }
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(app(scope, receive, send), timeout=2)
    assert cancelled.is_set()
    assert sent[0]["status"] == 499
