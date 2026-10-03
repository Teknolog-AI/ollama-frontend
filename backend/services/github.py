import math
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from backend.config import Settings
from backend.errors import ServiceError, json_object
from backend.models import GitHubSearchArguments


def retry_delay(headers: httpx.Headers) -> int | None:
    value = headers.get("retry-after")
    if value:
        try:
            return max(0, math.ceil(float(value)))
        except (ValueError, OverflowError):
            try:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                return max(0, math.ceil((date - datetime.now(timezone.utc)).total_seconds()))
            except (ValueError, TypeError, OverflowError):
                pass
    if headers.get("x-ratelimit-remaining") == "0":
        try:
            return max(0, math.ceil(float(headers["x-ratelimit-reset"]) - time.time()))
        except (KeyError, ValueError, OverflowError):
            pass
    return None


class GitHubService:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.client = client
        self.settings = settings

    async def search(self, arguments: GitHubSearchArguments) -> list[dict]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.settings.github_api_version,
            "User-Agent": "Gurkan-AI",
        }
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token.get_secret_value()}"
        try:
            response = await self.client.get(
                f"{self.settings.github_api_url}/search/repositories",
                params={"q": arguments.query, "sort": "stars", "order": "desc", "per_page": arguments.limit},
                headers=headers, timeout=self.settings.github_timeout_seconds,
            )
        except httpx.TimeoutException:
            raise ServiceError(504, "github_timeout", "GitHub zamanında cevap vermedi. Tekrar deneyin.")
        except httpx.RequestError:
            raise ServiceError(502, "github_unavailable", "GitHub bağlantısı kurulamadı.")

        if response.status_code in {403, 429}:
            try:
                body = response.json()
                reason = str(body.get("message", "")).lower() if isinstance(body, dict) else ""
            except ValueError:
                reason = ""
            rate_limited = (
                response.status_code == 429
                or response.headers.get("x-ratelimit-remaining") == "0"
                or "retry-after" in response.headers
                or "rate limit" in reason
                or "abuse detection" in reason
            )
            if rate_limited:
                delay = retry_delay(response.headers)
                wait = f" {delay} saniye sonra tekrar deneyin." if delay else " Biraz sonra tekrar deneyin."
                raise ServiceError(429, "github_rate_limit", "GitHub kullanım sınırına ulaşıldı." + wait, delay)
            raise ServiceError(502, "github_forbidden", "GitHub erişime izin vermedi. Erişim ayarlarını kontrol edin.")
        if response.status_code == 401:
            raise ServiceError(502, "github_auth", "GitHub erişim anahtarı geçersiz. Sunucu ayarını kontrol edin.")
        if response.status_code == 422:
            raise ServiceError(400, "github_query", "GitHub arama sorgusu geçersiz. Daha kısa bir sorgu deneyin.")
        if response.status_code != 200:
            raise ServiceError(502, "github_error", "GitHub araması şu anda tamamlanamadı.")

        items = json_object(response, "GitHub").get("items")
        if not isinstance(items, list):
            raise ServiceError(502, "invalid_response", "GitHub arama sonucu geçersiz.")
        repositories = []
        try:
            for repo in items[:arguments.limit]:
                entry = {
                    "name": repo["full_name"], "owner": repo["owner"]["login"],
                    "description": repo.get("description"), "language": repo.get("language"),
                    "stars": repo["stargazers_count"], "forks": repo["forks_count"], "url": repo["html_url"],
                }
                if any(not isinstance(entry[key], str) for key in ("name", "owner", "url")):
                    raise ValueError("Invalid repository")
                if any(type(entry[key]) is not int or entry[key] < 0 for key in ("stars", "forks")):
                    raise ValueError("Invalid count")
                repositories.append(entry)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ServiceError(502, "invalid_response", "GitHub arama sonucu eksik veya geçersiz.")
        return repositories
