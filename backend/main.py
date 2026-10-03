import asyncio
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from backend.config import ROOT, Settings
from backend.errors import ServiceError
from backend.models import ChatRequest, ChatResponse, GitHubSearchArguments, client_limits
from backend.services.chat import ChatService
from backend.services.github import GitHubService
from backend.services.ollama import OllamaService


async def until_disconnect(request: Request):
    # FastAPI has already consumed the request body before entering the route.
    # Await the ASGI event directly so task cancellation is not swallowed by a
    # nested cancellation scope in a polling implementation.
    while True:
        message = await request.receive()
        if message["type"] == "http.disconnect":
            return


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(transport=transport) as client:
            app.state.ollama = OllamaService(client, settings)
            app.state.github = GitHubService(client, settings)
            app.state.chat = ChatService(app.state.ollama, app.state.github, settings)
            yield

    app = FastAPI(title="Gürkan AI", lifespan=lifespan)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=settings.cors_origins,
            allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
        )

    @app.exception_handler(ServiceError)
    async def service_error(_request: Request, exc: ServiceError):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
        return JSONResponse(status_code=exc.status, content={"detail": exc.message, "code": exc.code}, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _exc: RequestValidationError):
        return JSONResponse(status_code=422, content={
            "detail": "Mesaj veya arama bilgisi geçersiz. Boş içerik göndermeyin; uzun sohbetlerde yeni sohbet başlatın.",
            "code": "validation_error",
        })

    @app.get("/models")
    async def get_models():
        return {
            "models": await app.state.ollama.models(), "limits": client_limits(),
            "request_timeout_ms": int(settings.chat_timeout_seconds * 1000) + 5_000,
        }

    @app.post("/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest, request: Request):
        task = asyncio.create_task(app.state.chat.chat(payload))
        disconnected = asyncio.create_task(until_disconnect(request))
        try:
            done, _ = await asyncio.wait({task, disconnected}, return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                return task.result()
            raise ServiceError(499, "request_cancelled", "İstek durduruldu.")
        finally:
            for pending in (task, disconnected):
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(task, disconnected, return_exceptions=True)

    @app.get("/github/search")
    async def github_search(
        query: Annotated[str, Query(min_length=2, max_length=200)],
        limit: Annotated[int, Query(ge=1, le=10)] = 5,
    ):
        try:
            arguments = GitHubSearchArguments(query=query, limit=limit)
        except ValidationError:
            raise ServiceError(422, "validation_error", "Arama metni 2–200 karakter olmalı.")
        repositories = await app.state.github.search(arguments)
        return {"source": "GitHub REST API", "query": arguments.query, "count": len(repositories), "repositories": repositories}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(ROOT / "frontend" / "index.html")

    app.mount("/assets", StaticFiles(directory=ROOT / "frontend"), name="assets")
    return app


app = create_app()
