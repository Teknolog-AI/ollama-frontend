from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

MAX_MESSAGE_CHARS = 8_000
MAX_HISTORY_MESSAGES = 40
MAX_HISTORY_CHARS = 64_000


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_CHARS)
    ]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    messages: list[Message] = Field(min_length=1, max_length=MAX_HISTORY_MESSAGES)

    @model_validator(mode="after")
    def validate_history(self):
        if self.messages[-1].role != "user":
            raise ValueError("Son mesaj kullanıcıya ait olmalı")
        for index, message in enumerate(self.messages):
            if message.role != ("user" if index % 2 == 0 else "assistant"):
                raise ValueError("Kullanıcı ve asistan mesajları sırayla ilerlemeli")
        if sum(len(message.content) for message in self.messages) > MAX_HISTORY_CHARS:
            raise ValueError("Sohbet boyutu sınırı aşıldı; yeni sohbet başlatın")
        return self


class GitHubSearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]
    limit: int = Field(default=5, ge=1, le=10, strict=True)


class ChatResponse(BaseModel):
    model: str
    answer: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


def client_limits() -> dict[str, int]:
    return {
        "max_message_chars": MAX_MESSAGE_CHARS,
        "max_messages": MAX_HISTORY_MESSAGES,
        "max_total_chars": MAX_HISTORY_CHARS,
    }
