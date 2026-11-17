"""Shared OpenAI-compatible LLM wrapper with caching and JSON validation."""
import hashlib
import json
import os
from pathlib import Path
from typing import Optional, Tuple, Type, TypeVar

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ValidationError


T = TypeVar("T", bound=BaseModel)
CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "llm"


class LLMConfigurationError(RuntimeError):
    """Raised when no supported API credential is configured."""


class LLMResponseError(RuntimeError):
    """Raised when the model response cannot be used safely."""


def _settings() -> Tuple[str, str, Optional[str]]:
    load_dotenv()
    explicit_model = os.getenv("DEVCREW_MODEL") or os.getenv("OPENAI_MODEL")
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")

    if api_key:
        return explicit_model or "gpt-4o-mini", api_key, base_url

    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if deepseek_key:
        return (explicit_model or "deepseek-chat", deepseek_key,
                os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))

    raise LLMConfigurationError(
        "Set OPENAI_API_KEY or DEEPSEEK_API_KEY in the environment or .env file."
    )


def _cache_path(model: str, system: str, user: str, response_mode: str) -> Path:
    raw = "\0".join((model, system, user, response_mode)).encode("utf-8")
    return CACHE_DIR / (hashlib.sha1(raw).hexdigest() + ".json")


def _read_cache(path: Path) -> Optional[Tuple[str, int]]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data["text"]), int(data.get("tokens", 0))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_cache(path: Path, text: str, tokens: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"text": text, "tokens": tokens}, ensure_ascii=False),
        encoding="utf-8",
    )


def _complete(system: str, user: str, *, agent: str, json_mode: bool) -> Tuple[str, int]:
    model, api_key, base_url = _settings()
    response_mode = "json" if json_mode else "text"
    cache_path = _cache_path(model, system, user, response_mode)
    cached = _read_cache(cache_path)
    if cached is not None:
        return cached

    client_args = {"api_key": api_key}
    if base_url:
        client_args["base_url"] = base_url
    client = OpenAI(**client_args)
    request = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
    }
    if json_mode:
        request["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**request)
    choice = response.choices[0]
    refusal = getattr(choice.message, "refusal", None)
    if refusal:
        raise LLMResponseError(f"{agent} model refused the request: {refusal}")
    if choice.finish_reason not in (None, "stop"):
        raise LLMResponseError(
            f"{agent} model response ended with finish_reason={choice.finish_reason!r}"
        )
    text = choice.message.content
    if not isinstance(text, str) or not text.strip():
        raise LLMResponseError(f"{agent} model returned no text")

    usage = getattr(response, "usage", None)
    tokens = int(getattr(usage, "total_tokens", 0) or 0)
    _write_cache(cache_path, text, tokens)
    return text, tokens


def chat(system: str, user: str, *, agent: str) -> Tuple[str, int]:
    """Return model text and total tokens, using a deterministic disk cache."""
    return _complete(system, user, agent=agent, json_mode=False)


def chat_json(system: str, user: str, schema: Type[T], *, agent: str) -> Tuple[T, int]:
    """Return a Pydantic-validated JSON response, retrying validation twice."""
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    json_system = (
        system
        + "\nReturn one JSON object only. It must match this JSON Schema:\n"
        + schema_json
    )
    current_user = user
    total_tokens = 0
    last_error = ""

    for attempt in range(3):
        text, tokens = _complete(json_system, current_user, agent=agent, json_mode=True)
        total_tokens += tokens
        try:
            return schema.model_validate_json(text), total_tokens
        except ValidationError as exc:
            last_error = str(exc)
            if attempt == 2:
                break
            current_user = (
                user
                + "\n\nYour previous JSON failed schema validation. Correct it without "
                  "adding commentary.\nValidation errors:\n"
                + last_error
                + "\nPrevious JSON:\n"
                + text
            )

    raise LLMResponseError(
        f"{agent} model did not return valid {schema.__name__} JSON: {last_error}"
    )
