from typing import Literal
import json
from urllib import error, request
import httpx

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500", "http://localhost:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
GITHUB_API_URL = "https://api.github.com"

GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2026-03-10",
    "User-Agent": "Gurkan-AI"
}

# Ollama tool definition for GitHub search
GITHUB_SEARCH_TOOL = {
    "name": "search_github_repositories",
    "description": "Search GitHub repositories by query. Returns a list of repositories.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10}
        },
        "required": ["query"]
    }
}

ALLOWED_MODELS = [
    "qwen3.5:4b-q4_K_M",
    "gurkan-ai",
]
async def search_github_repositories(
    query: str,
    limit: int = 5
) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{GITHUB_API_URL}/search/repositories",
                params={
                    "q": query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": limit
                },
                headers=GITHUB_HEADERS
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub bağlantısı kurulamadı: {exc}"
        )

    if response.status_code == 403:
        raise HTTPException(
            status_code=429,
            detail="GitHub API kullanım sınırına ulaşıldı"
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"GitHub API hatası: {response.status_code}"
        )

    repositories = response.json().get("items", [])

    return [
        {
            "name": repo["full_name"],
            "owner": repo["owner"]["login"],
            "description": repo["description"],
            "language": repo["language"],
            "stars": repo["stargazers_count"],
            "forks": repo["forks_count"],
            "url": repo["html_url"]
        }
        for repo in repositories
    ]


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[Message]


@app.get("/models")
def get_models():
    return {"models": ALLOWED_MODELS}


@app.post("/chat")
async def chat(request: ChatRequest):
    if request.model not in ALLOWED_MODELS:
        raise HTTPException(
            status_code=400,
            detail="Geçersiz model"
        )

    messages = [
        {
            "role": "system",
            "content": (
                "Sen yardımcı bir yapay zeka asistanısın. "
                "Kullanıcı GitHub repository veya açık kaynak proje "
                "araması istediğinde GitHub aracını kullan. "
                "Araçtan gelmeyen repository bilgilerini uydurma."
            )
        },
        *[
            message.model_dump()
            for message in request.messages
        ]
    ]

    ollama_data = {
        "model": request.model,
        "messages": messages,
        "tools": [GITHUB_SEARCH_TOOL],
        "stream": False
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            # Birinci Ollama çağrısı: Araç gerekip gerekmediğine karar verir.
            response = await client.post(
                OLLAMA_CHAT_URL,
                json=ollama_data
            )
            response.raise_for_status()
            result = response.json()

            assistant_message = result["message"]
            tool_calls = assistant_message.get("tool_calls", [])

            # Araç istenmediyse normal AI cevabını döndürür.
            if not tool_calls:
                return {
                    "model": request.model,
                    "answer": assistant_message["content"]
                }

            messages.append(assistant_message)

            for tool_call in tool_calls:
                function = tool_call.get("function", {})
                function_name = function.get("name")
                arguments = function.get("arguments", {})

                if function_name != "search_github_repositories":
                    tool_result = {
                        "error": f"Bilinmeyen araç: {function_name}"
                    }
                else:
                    query = str(arguments.get("query", "")).strip()

                    try:
                        limit = int(arguments.get("limit", 5))
                    except (TypeError, ValueError):
                        limit = 5

                    limit = max(1, min(limit, 10))

                    if len(query) < 2:
                        tool_result = {
                            "error": "GitHub sorgusu en az 2 karakter olmalı"
                        }
                    else:
                        try:
                            tool_result = await search_github_repositories(
                                query=query,
                                limit=limit
                            )
                        except HTTPException as exc:
                            tool_result = {
                                "error": exc.detail
                            }

                messages.append({
                    "role": "tool",
                    "tool_name": function_name,
                    "content": json.dumps(
                        tool_result,
                        ensure_ascii=False
                    )
                })

            # İkinci Ollama çağrısı: GitHub sonuçlarını yorumlar.
            final_response = await client.post(
                OLLAMA_CHAT_URL,
                json={
                    "model": request.model,
                    "messages": messages,
                    "tools": [GITHUB_SEARCH_TOOL],
                    "stream": False
                }
            )
            final_response.raise_for_status()
            final_result = final_response.json()

    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Ollama bağlantısı kurulamadı: {exc}"
        )

    return {
        "model": request.model,
        "answer": final_result["message"]["content"]
    }
@app.get("/github/search")
async def github_search(
    query: str = Query(min_length=2),
    limit: int = Query(default=5, ge=1, le=10)
):
    repositories = await search_github_repositories(
        query=query,
        limit=limit
    )

    return {
        "source": "GitHub REST API",
        "query": query,
        "count": len(repositories),
        "repositories": repositories
    }