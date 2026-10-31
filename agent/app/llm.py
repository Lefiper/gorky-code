"""Единственный LLM проекта: GigaChat через langchain-gigachat."""

from __future__ import annotations

from langchain_gigachat import GigaChat

from app.config import ConfigError, Settings


def build_chat_model(settings: Settings) -> GigaChat:
    if not settings.llm_configured:
        raise ConfigError("Задайте GIGACHAT_CREDENTIALS и GIGACHAT_SCOPE в .env.")
    kwargs = {
        "credentials": settings.gigachat_credentials,
        "scope": settings.gigachat_scope,
        "model": settings.gigachat_model,
        "verify_ssl_certs": settings.gigachat_verify_ssl,
        "temperature": 0.2,
        "timeout": 60,
    }
    if settings.gigachat_ca_bundle_file:
        kwargs["ca_bundle_file"] = settings.gigachat_ca_bundle_file
    return GigaChat(**kwargs)
