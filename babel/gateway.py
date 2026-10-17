"""AssemblyAI LLM Gateway client — OpenAI-compatible chat completions.

Ground truth (docs/llm-gateway/quickstart):
- POST https://llm-gateway.assemblyai.com/v1/chat/completions
- Auth: `authorization: <API_KEY>`
- OpenAI request/response shape; model used: qwen3.5-4b-32k-fast
"""

import httpx

from babel.audio import DICTATION_LANGUAGES

GATEWAY_URL = "https://llm-gateway.assemblyai.com/v1/chat/completions"
DEFAULT_MODEL = "qwen3.5-4b-32k-fast"

_LANG_NAME = {code: name for code, name in DICTATION_LANGUAGES}


def lang_name(code: str) -> str:
    return _LANG_NAME.get(code, code)


def build_interpreter_messages(*, text: str, source_lang: str, target_lang: str,
                               history: list | None = None) -> list[dict]:
    """Messages for a faithful live-interpretation turn."""
    source, target = lang_name(source_lang), lang_name(target_lang)
    system = (
        "You are a professional simultaneous interpreter in a live two-person conversation. "
        f"Translate the speaker's transcription from {source} into {target}.\n"
        "Rules:\n"
        "- Output ONLY the translation, ready to be spoken aloud. No explanations, no quotes, no notes.\n"
        "- Preserve the speaker's tone and intent, including questions and politeness.\n"
        "- Keep names, numbers, and technical terms exactly as written.\n"
        "- Sound natural when spoken: prefer short, clear sentences.\n"
        "- If the transcription is a fragment or trails off, translate the intended meaning.\n"
    )
    messages = [{"role": "system", "content": system}]
    for turn in (history or [])[-6:]:
        messages.append({
            "role": "user",
            "content": f"[{turn['side']}, {lang_name(turn['lang'])}] {turn['original']}",
        })
        messages.append({
            "role": "assistant",
            "content": turn["translation"],
        })
    messages.append({"role": "user", "content": text})
    return messages


class TranslationGateway:
    """Translate turns through the AssemblyAI LLM Gateway."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, base_url: str = GATEWAY_URL):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    async def translate(self, *, text: str, source_lang: str, target_lang: str,
                        history: list | None = None) -> str:
        messages = build_interpreter_messages(text=text, source_lang=source_lang,
                                             target_lang=target_lang, history=history)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(self.base_url,
                                     headers={"authorization": self.api_key},
                                     json={"model": self.model, "messages": messages,
                                           "max_tokens": 400, "temperature": 0.2})
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"].strip()


class MockGateway:
    """Offline deterministic gateway for tests/dev."""

    async def translate(self, *, text: str, source_lang: str, target_lang: str,
                        history: list | None = None) -> str:
        return f"[{target_lang}] {text}"
