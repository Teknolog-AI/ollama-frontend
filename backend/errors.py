import httpx


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after = retry_after


def json_object(response: httpx.Response, service: str) -> dict:
    try:
        value = response.json()
    except ValueError:
        value = None
    if not isinstance(value, dict):
        raise ServiceError(502, "invalid_response", f"{service} geçerli bir cevap döndürmedi.")
    return value
