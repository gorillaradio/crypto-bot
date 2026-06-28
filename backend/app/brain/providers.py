import logging
from typing import Protocol
from app.core.config import settings

logger = logging.getLogger(__name__)


class ProviderAdapter(Protocol):
    def complete_json(self, system: str, user: str) -> str: ...


class OpenAICompatAdapter:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def complete_json(self, system: str, user: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content


class AnthropicAdapter:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def complete_json(self, system: str, user: str) -> str:
        resp = self.client.messages.create(
            model=self.model, max_tokens=2000,
            system=system, messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text


def make_adapter(provider: str, model: str) -> ProviderAdapter:
    if provider == "anthropic":
        import anthropic
        api_key = settings.provider_api_key(provider)
        if not api_key:
            logger.warning("No API key configured for provider '%s'; LLM calls will fail at runtime", provider)
            api_key = "placeholder"
        return AnthropicAdapter(
            anthropic.Anthropic(api_key=api_key), model
        )
    import openai
    api_key = settings.provider_api_key(provider)
    if not api_key:
        logger.warning("No API key configured for provider '%s'; LLM calls will fail at runtime", provider)
        api_key = "placeholder"
    client = openai.OpenAI(
        api_key=api_key,
        base_url=settings.provider_base_url(provider),
    )
    return OpenAICompatAdapter(client, model)
