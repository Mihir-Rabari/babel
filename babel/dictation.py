"""AssemblyAI Dictation API client — live streaming multipart upload.

Ground truth (docs/api-reference/dictation-api/transcribe-live):
- POST https://dictation.assemblyai.com/v1/transcribe/live
- Auth: `Authorization: <API_KEY>` (raw key, no Bearer)
- multipart/form-data with a `config` JSON part first, then an `audio` part
- raw PCM (`audio/pcm`) requires `sample_rate` + `channels` in config, 16-bit S16LE only
- config part must arrive before the first audio byte; chunks stream while the user
  is still speaking ("uploading while recording"); the chunked body can't be replayed
- <= 120 s per call, <= 256 MB; response JSON: `text` (verbatim) + `llm_response` (cleaned)
- GET /warm pre-establishes the TLS connection off the critical path

Audio-source contract across Babel: an ASYNC ITERATOR yielding PCM chunks;
exhaustion = end of turn.
"""

import json
import uuid

import httpx

DICTATION_BASE = "https://dictation.assemblyai.com"
LIVE_PATH = "/v1/transcribe/live"
WARM_PATH = "/warm"
MAX_TURN_SECONDS = 120


class DictationError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(f"dictation {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


def build_multipart(config: dict, audio_iter, boundary: str,
                    audio_content_type: str = "audio/pcm", filename: str = "audio.pcm"):
    """Async generator emitting a streaming multipart body: config part, audio chunks, epilogue."""
    async def gen():
        cfg = json.dumps(config)
        yield (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="config"\r\n'
            f"Content-Type: application/json\r\n\r\n{cfg}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="audio"; filename="{filename}"\r\n'
            f"Content-Type: {audio_content_type}\r\n\r\n"
        ).encode()
        async for chunk in audio_iter:
            if chunk:
                yield chunk
        yield f"\r\n--{boundary}--\r\n".encode()
    return gen()


class DictationClient:
    """Live Dictation over raw HTTP (no SDK — the protocol is the product here)."""

    def __init__(self, api_key: str, base_url: str = DICTATION_BASE):
        self.api_key = api_key
        self.base_url = base_url
        self._timeout = httpx.Timeout(connect=10.0, read=90.0, write=30.0, pool=10.0)

    async def warm(self) -> None:
        """Pre-warm the TLS connection (GET /warm). Best-effort, never fatal."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.get(self.base_url + WARM_PATH, headers={"Authorization": self.api_key})
        except httpx.HTTPError:
            pass  # warming is a latency optimization, not a requirement

    async def transcribe_live(self, *, audio_iter, language_codes: list[str],
                              keyterms: list[str] | None = None, stt_prompt: str | None = None,
                              llm_instruction: str | None = None, sample_rate: int = 16000,
                              channels: int = 1) -> dict:
        """Stream PCM chunks while the user speaks; return {'text', 'llm_response', ...}."""
        boundary = "b" + uuid.uuid4().hex
        config: dict = {"sample_rate": sample_rate, "channels": channels,
                        "language_codes": language_codes}
        if keyterms:
            config["keyterms_prompt"] = keyterms
        if stt_prompt:
            config["stt_prompt"] = stt_prompt
        if llm_instruction:
            config["llm_instruction"] = llm_instruction
        body = build_multipart(config, audio_iter, boundary)
        headers = {"Authorization": self.api_key,
                   "Content-Type": f"multipart/form-data; boundary={boundary}"}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream("POST", self.base_url + LIVE_PATH, headers=headers,
                                     content=body) as resp:
                if resp.status_code != 200:
                    raw = (await resp.aread()).decode("utf-8", "ignore")[:2000]
                    raise DictationError(resp.status_code, raw)
                payload = json.loads((await resp.aread()).decode("utf-8"))
        return payload


class MockDictationClient:
    """Offline development client: serves planted-truth transcripts from fixtures."""

    def __init__(self, scripted: dict | None = None):
        self.scripted = scripted or {}
        self.warmed = 0

    async def warm(self) -> None:
        self.warmed += 1

    async def transcribe_live(self, *, audio_iter, language_codes: list[str],
                              keyterms=None, stt_prompt=None, llm_instruction=None,
                              sample_rate: int = 16000, channels: int = 1) -> dict:
        raw = bytearray()
        async for chunk in audio_iter:
            raw.extend(chunk)
        served = dict(self.scripted.get(len(raw), {"text": "", "llm_response": ""}))
        served.setdefault("audio_bytes", len(raw))
        return served
