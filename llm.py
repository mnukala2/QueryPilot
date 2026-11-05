"""Provider-agnostic chat model factory (OpenAI, Anthropic, AWS Bedrock) using LangChain."""
from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from .config import settings

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-5",
    "bedrock": "anthropic.claude-3-5-sonnet-20240620-v1:0",
}


def get_llm(provider: str | None = None, model: str | None = None) -> BaseChatModel:
    provider = (provider or settings.provider).lower()
    model = model or settings.model or DEFAULT_MODELS.get(provider, "")
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, temperature=settings.temperature)
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, temperature=settings.temperature, max_tokens=1024)
    if provider == "bedrock":
        from langchain_aws import ChatBedrockConverse
        return ChatBedrockConverse(model=model, temperature=settings.temperature)
    raise ValueError(f"Unknown QP_LLM_PROVIDER: {provider!r} (use openai | anthropic | bedrock)")
