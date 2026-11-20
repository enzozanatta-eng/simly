"""LLM access behind a small, provider-neutral protocol.

The rest of the package only sees ``LLMClient.call`` and a neutral
conversation history (``Turn`` objects). Each provider converts that history
to its own wire format, so switching provider never touches the agent logic.

Providers are optional dependencies: ``pip install -e ".[llm]"`` installs both.
Tests use a scripted fake client.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


# Neutral conversation turns
@dataclass
class UserText:
    text: str


@dataclass
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


Turn = UserText | ToolCall | ToolResult


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    def call(self, system: str, history: list[Turn], tools: list[Tool]) -> ToolCall:
        """Return the tool call the model chose (the model must call a tool)."""
        ...


def _provider_error(e: Exception) -> LLMError:
    """Turn SDK exceptions into one readable message (never leaks the key)."""
    name = type(e).__name__
    if "Authentication" in name or "PermissionDenied" in name:
        return LLMError("The AI provider rejected the API key. Check OPENAI_API_KEY or "
                        "ANTHROPIC_API_KEY on the server.")
    if "RateLimit" in name:
        return LLMError("The AI provider's rate limit or credit was reached; try again later.")
    return LLMError(f"The AI provider returned an error ({name}).")


def _import(module: str):
    try:
        return __import__(module)
    except ImportError as e:  # pragma: no cover - depends on environment
        raise LLMError(f"Install the LLM extras first: pip install -e '.[llm]' ({e})") from e


class AnthropicClient:
    default_model = "claude-sonnet-5-5"

    def __init__(self, model: str | None = None, max_tokens: int = 2048):
        self._client = _import("anthropic").Anthropic()
        self.model = model or os.environ.get("SIMLY_MODEL", self.default_model)
        self.max_tokens = max_tokens

    @staticmethod
    def to_messages(history: list[Turn]) -> list[dict]:
        out: list[dict] = []
        for t in history:
            if isinstance(t, UserText):
                out.append({"role": "user", "content": t.text})
            elif isinstance(t, ToolCall):
                out.append({"role": "assistant", "content": [
                    {"type": "tool_use", "id": t.id, "name": t.name, "input": t.input}
                ]})
            else:
                out.append({"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": t.call_id,
                    "content": t.content, "is_error": t.is_error,
                }]})
        return out

    def call(self, system: str, history: list[Turn], tools: list[Tool]) -> ToolCall:
        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                tools=[{"name": t.name, "description": t.description,
                        "input_schema": t.input_schema} for t in tools],
                tool_choice={"type": "any"},
                messages=self.to_messages(history),
            )
        except Exception as e:  # SDK errors -> one readable message
            raise _provider_error(e) from e
        for block in resp.content:
            if block.type == "tool_use":
                return ToolCall(block.id, block.name, dict(block.input))
        raise LLMError("model returned no tool call")


class OpenAIClient:
    default_model = "gpt-4.1-mini"

    def __init__(self, model: str | None = None):
        self._client = _import("openai").OpenAI()
        self.model = model or os.environ.get("SIMLY_MODEL", self.default_model)

    @staticmethod
    def to_messages(system: str, history: list[Turn]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for t in history:
            if isinstance(t, UserText):
                out.append({"role": "user", "content": t.text})
            elif isinstance(t, ToolCall):
                out.append({"role": "assistant", "content": None, "tool_calls": [{
                    "id": t.id, "type": "function",
                    "function": {"name": t.name, "arguments": json.dumps(t.input)},
                }]})
            else:
                prefix = "ERROR: " if t.is_error else ""
                out.append({"role": "tool", "tool_call_id": t.call_id,
                            "content": prefix + t.content})
        return out

    def call(self, system: str, history: list[Turn], tools: list[Tool]) -> ToolCall:
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=self.to_messages(system, history),
                tools=[{"type": "function", "function": {
                    "name": t.name, "description": t.description, "parameters": t.input_schema,
                }} for t in tools],
                tool_choice="required",
            )
        except Exception as e:  # SDK errors -> one readable message
            raise _provider_error(e) from e
        calls = resp.choices[0].message.tool_calls
        if not calls:
            raise LLMError("model returned no tool call")
        c = calls[0]
        try:
            args = json.loads(c.function.arguments)
        except json.JSONDecodeError as e:
            raise LLMError(f"model returned invalid JSON arguments: {e}") from e
        return ToolCall(c.id, c.function.name, args)


PROVIDERS = {"anthropic": AnthropicClient, "openai": OpenAIClient}
_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


def make_client(provider: str | None = None) -> LLMClient:
    """Pick the provider: explicit > SIMLY_PROVIDER > whichever API key is set."""
    provider = provider or os.environ.get("SIMLY_PROVIDER")
    if provider is None:
        provider = next((p for p, k in _KEYS.items() if os.environ.get(k)), None)
        if provider is None:
            raise LLMError("Set ANTHROPIC_API_KEY or OPENAI_API_KEY to use the AI features.")
    if provider not in PROVIDERS:
        raise LLMError(f"unknown provider '{provider}' (choose from {sorted(PROVIDERS)})")
    if not os.environ.get(_KEYS[provider]):
        raise LLMError(f"Set {_KEYS[provider]} to use the {provider} provider.")
    return PROVIDERS[provider]()


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve ``$ref``/``$defs`` from a pydantic JSON schema into one flat schema."""
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].split("/")[-1]])
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)
