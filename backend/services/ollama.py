import httpx

from backend.config import Settings, canonical_model
from backend.errors import ServiceError, json_object


class OllamaService:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.client, self.settings = client, settings

    async def request(self, method: str, path: str, *, payload: dict | None = None) -> dict:
        timeout = self.settings.model_list_timeout_seconds if path == "/api/tags" else self.settings.ollama_timeout_seconds
        try:
            response = await self.client.request(
                method, f"{self.settings.ollama_base_url}{path}", json=payload, timeout=timeout
            )
        except httpx.TimeoutException:
            raise ServiceError(504, "ollama_timeout", "Ollama zamanında cevap vermedi. Model yükleniyor olabilir; tekrar deneyin.")
        except httpx.RequestError:
            raise ServiceError(503, "ollama_unavailable", "Ollama'ya ulaşılamıyor. Bilgisayarınızda Ollama'nın açık olduğunu kontrol edin.")
        if response.status_code == 404 and path == "/api/chat":
            raise ServiceError(404, "model_not_found", "Seçilen model Ollama'da bulunamadı. Model listesini yenileyin veya modeli kurun.")
        if response.status_code == 400:
            raise ServiceError(400, "ollama_request", "Ollama isteği kabul etmedi. Modelin araç çağırma desteğini ve Ollama sürümünü kontrol edin.")
        if response.status_code >= 400:
            raise ServiceError(502, "ollama_error", "Ollama isteği işleyemedi. Ollama durumunu kontrol edip tekrar deneyin.")
        return json_object(response, "Ollama")

    async def models(self) -> list[str]:
        models = (await self.request("GET", "/api/tags")).get("models")
        if not isinstance(models, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip()
            for item in models
        ):
            raise ServiceError(502, "invalid_response", "Ollama model listesi geçersiz.")
        installed = {canonical_model(item["name"]): item["name"] for item in models}
        return list(dict.fromkeys(
            installed[canonical_model(name)] for name in self.settings.allowed_models
            if canonical_model(name) in installed
        ))

    async def chat(self, model: str, messages: list[dict], tools: list[dict]) -> dict:
        body = await self.request("POST", "/api/chat", payload={
            "model": model, "messages": messages, "tools": tools, "stream": False,
        })
        message = body.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise ServiceError(502, "invalid_response", "Ollama geçerli bir asistan cevabı döndürmedi.")
        if not isinstance(message.get("content"), str) or not isinstance(message.get("tool_calls", []), list):
            raise ServiceError(502, "invalid_response", "Ollama cevap biçimi geçersiz.")
        return message
