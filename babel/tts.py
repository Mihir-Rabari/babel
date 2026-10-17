"""Streaming TTS client — the REAL reverse-engineered protocol (see docs/tts-protocol.md).

Discovered live 2026-10-17 by probing wss://streaming-tts.assemblyai.com/v1/ws:
- Auth: `?token=<key>` query param OR raw `Authorization: <key>` header. Bearer rejected.
  NOTE: token-query auth BREAKS if any other query param is present (server bug, FINDINGS F10)
  => this client authenticates with the raw-key Authorization header, leaving the query
  string free for future params.
- On connect the server sends Begin{id, expires_at, configuration{voice: "jane",
  language: "english", sample_rate: 24000, encoding: "pcm_s16le", word_boundaries: true,
  voice_clone: false, ...}}.
- Client messages: Generate{text, voice?, language?} | Flush | Terminate | KeepAlive |
  Cancel | VoiceReference{audio}.
- Generate buffers text; Flush synthesizes the buffer. voice/language override PER Generate
  (verified: language "spanish" + voice "lola" produced Spanish audio mid-connection).
- Server frames: Audio{audio: <base64 pcm_s16le>}* -> FlushDone{flush_id, audio_duration_ms}
  -> WordBoundaries{flush_id, audio_start_ms, words[{word, start, end, confidence}]}
  | Error{error_code, error} | Termination{...}.
- Error frames close the socket (close code = error code). Invalid voice/language values
  produce NO error and NO audio (silent no-op).
- One persistent connection speaks many turns (flush_id increments); Terminate ends the
  session cleanly with stats.

speak() yields ("format", {...}) once, then ("audio", bytes)..., then ("meta", {...}) for
FlushDone/WordBoundaries. Raises TTSError with the server's message verbatim.
"""

import asyncio
import base64
import json

import websockets

TTS_WS = "wss://streaming-tts.assemblyai.com/v1/ws"

# Dictation language codes -> TTS language names (server uses English full names).
LANG_NAMES = {
    "en": "english", "es": "spanish", "fr": "french", "de": "german",
    "it": "italian", "pt": "portuguese", "nl": "dutch", "sv": "swedish",
    "no": "norwegian", "da": "danish", "fi": "finnish", "hi": "hindi",
    "vi": "vietnamese", "he": "hebrew", "ur": "urdu", "ko": "korean",
    "ca": "catalan", "gl": "galician", "ru": "russian", "ro": "romanian",
    "et": "estonian", "fa": "persian", "yue": "cantonese", "af": "afrikaans",
    "mr": "marathi", "zu": "zulu", "xh": "xhosa", "nn": "nynorsk",
    "ar": "arabic", "ja": "japanese", "zh": "mandarin",
}


class TTSError(RuntimeError):
    def __init__(self, payload: dict):
        msg = payload.get("error") or json.dumps(payload)[:300]
        super().__init__(f"streaming-tts: {msg}")
        self.payload = payload


def tts_language_name(code_or_name: str) -> str:
    return LANG_NAMES.get(code_or_name, code_or_name)


class StreamingTTSClient:
    """Persistent streaming-TTS session; one connection speaks many turns."""

    def __init__(self, api_key: str, url: str = TTS_WS):
        self.api_key = api_key
        self.url = url
        self._ws = None
        self._config: dict = {}
        self._lock = asyncio.Lock()

    async def _connect(self) -> None:
        ws = await websockets.connect(
            self.url,
            additional_headers={"Authorization": self.api_key},
            open_timeout=15,
            max_size=64 * 1024 * 1024,
        )
        begin = json.loads(await ws.recv())
        if begin.get("type") == "Error":
            await ws.close()
            raise TTSError(begin)
        self._ws = ws
        self._config = begin.get("configuration", {})

    async def _ensure_connected(self) -> None:
        if self._ws is None:
            await self._connect()

    async def speak(self, *, text: str, voice: str = "jane", language: str = "en"):
        """Yield ("format", {...}), ("audio", bytes)..., ("meta", {...}). Reconnects once."""
        lang = tts_language_name(language)
        async with self._lock:
            for attempt in (1, 2):
                try:
                    await self._ensure_connected()
                    async for event in self._speak_once(text=text, voice=voice, language=lang):
                        yield event
                    return
                except websockets.ConnectionClosed:
                    self._ws = None
                    if attempt == 2:
                        raise

    async def _speak_once(self, *, text: str, voice: str, language: str):
        yield ("format", {"encoding": self._config.get("encoding", "pcm_s16le"),
                          "sample_rate": self._config.get("sample_rate", 24000),
                          "voice": voice, "language": language})
        await self._ws.send(json.dumps({"type": "Generate", "text": text,
                                       "voice": voice, "language": language}))
        await self._ws.send(json.dumps({"type": "Flush"}))
        got_audio = False
        while True:
            try:
                msg = await asyncio.wait_for(self._ws.recv(), timeout=60.0)
            except asyncio.TimeoutError:
                raise TTSError({"error": "timed out waiting for FlushDone"})
            except websockets.ConnectionClosed:
                if got_audio:
                    break  # server closed after the final FlushDone burst
                raise
            payload = json.loads(msg)
            ftype = payload.get("type")
            if ftype == "Audio":
                got_audio = True
                yield ("audio", base64.b64decode(payload.get("audio", "")))
            elif ftype == "FlushDone":
                yield ("meta", payload)
                # WordBoundaries follows immediately; grab it without stalling.
                try:
                    tail = await asyncio.wait_for(self._ws.recv(), timeout=1.0)
                    tp = json.loads(tail)
                    if tp.get("type") == "WordBoundaries":
                        yield ("meta", tp)
                    elif tp.get("type") == "Error":
                        raise TTSError(tp)
                except asyncio.TimeoutError:
                    pass
                break
            elif ftype == "WordBoundaries":
                yield ("meta", payload)
            elif ftype == "Error":
                raise TTSError(payload)
            elif ftype == "Termination":
                self._ws = None
                break

    async def keepalive(self) -> None:
        """Best-effort KeepAlive ping for idle sessions."""
        async with self._lock:
            if self._ws is None:
                return
            try:
                await self._ws.send(json.dumps({"type": "KeepAlive"}))
            except websockets.ConnectionClosed:
                self._ws = None

    async def close(self) -> None:
        """Terminate the session cleanly (frees the concurrent-session slot)."""
        async with self._lock:
            if self._ws is None:
                return
            try:
                await self._ws.send(json.dumps({"type": "Terminate"}))
                try:
                    await asyncio.wait_for(self._ws.recv(), timeout=3.0)  # Termination stats
                except (asyncio.TimeoutError, websockets.ConnectionClosed):
                    pass
            except websockets.ConnectionClosed:
                pass
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None


class MockStreamingTTS:
    """Offline TTS: a soft fading 220 Hz tone as 16 kHz S16LE PCM, chunked."""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    async def speak(self, *, text: str, voice: str = "alba", language: str = "en"):
        yield ("format", {"encoding": "pcm_s16le", "sample_rate": 16000,
                          "voice": voice, "language": language})
        import math
        total = 16000 * min(2.0, max(0.4, len(text) / 60.0))
        samples = []
        for i in range(int(total)):
            t = i / 16000
            envelope = min(1.0, t * 8) * max(0.0, 1 - t / (total / 16000))
            samples.append(int(8000 * envelope * math.sin(2 * math.pi * 220 * t)))
        pcm = b"".join(abs(v).to_bytes(2, "little", signed=True) for v in samples)
        for i in range(0, len(pcm), 3200):
            yield ("audio", pcm[i:i + 3200])
        yield ("meta", {"type": "FlushDone", "audio_duration_ms": int(total / 16)})

    async def keepalive(self) -> None:
        pass

    async def close(self) -> None:
        pass
