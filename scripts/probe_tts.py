#!/usr/bin/env python3
"""Reverse-engineer the undocumented streaming TTS API (wss://streaming-tts.assemblyai.com/v1/ws).

Stage 0: key sanity — verify against the documented LLM Gateway + Dictation endpoints.
Stage 1: auth modes — token query param vs Authorization header (raw vs Bearer).
Stage 2: schema candidates — send each on a fresh connection; server error messages ARE the spec.
Stage 3: if audio arrives — save it, fingerprint the encoding.

Prints everything verbatim; never prints the key.
"""
import asyncio
import io
import json
import os
import sys
import wave

import httpx
import websockets

TTS_WS = "wss://streaming-tts.assemblyai.com/v1/ws"
GATEWAY = "https://llm-gateway.assemblyai.com/v1/chat/completions"
DICTATION_LIVE = "https://dictation.assemblyai.com/v1/transcribe/live"
KEY = os.environ.get("ASSEMBLYAI_API_KEY", "")
AUDIO_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out")
os.makedirs(AUDIO_OUT, exist_ok=True)


def hdr(raw: bytes) -> str:
    return raw[:24].hex()


def silence_wav(seconds: float = 0.5) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


async def stage0() -> None:
    print("=== STAGE 0: key sanity ===")
    print(f"key length: {len(KEY)}")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(GATEWAY, headers={"authorization": KEY},
                         json={"model": "qwen3.5-4b-32k-fast",
                               "messages": [{"role": "user", "content": "Say OK"}],
                               "max_tokens": 5})
        print("gateway:", r.status_code, r.text[:200])
        r2 = await c.post(
            DICTATION_LIVE,
            headers={"Authorization": KEY},
            files={"config": (None, json.dumps({"language_codes": ["en"]}), "application/json"),
                   "audio": ("silence.wav", silence_wav(), "audio/wav")},
        )
        print("dictation:", r2.status_code, r2.text[:300])


async def drain(ws, seconds: float, label: str):
    """Collect frames for `seconds`; print each verbatim; return (texts, audio)."""
    texts, audio = [], b""
    loop = asyncio.get_event_loop()
    end = loop.time() + seconds
    while True:
        left = end - loop.time()
        if left <= 0:
            break
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=left)
        except (asyncio.TimeoutError, websockets.ConnectionClosed) as e:
            print(f"  [{label}] recv-end: {type(e).__name__}")
            break
        if isinstance(msg, str):
            texts.append(msg)
            print(f"  [{label}] TEXT: {msg[:400]}")
        else:
            audio += msg
            print(f"  [{label}] BIN: {len(msg)}B head={hdr(msg)}")
    return texts, audio


async def stage1():
    print("\n=== STAGE 1: auth modes ===")
    working = []
    for name, url, headers in [
        ("token_query", TTS_WS + "?token=" + KEY, {}),
        ("auth_raw", TTS_WS, {"Authorization": KEY}),
        ("auth_bearer", TTS_WS, {"Authorization": "Bearer " + KEY}),
    ]:
        try:
            ws = await websockets.connect(url, additional_headers=headers, open_timeout=15)
            print(f"  {name}: CONNECTED")
            await drain(ws, 2.0, name + ".hello")
            working.append((name, url, headers))
            await ws.close()
        except Exception as e:
            print(f"  {name}: {type(e).__name__}: {str(e)[:200]}")
    return working


CANDIDATES = [
    ("flat_rich", [{"text": "Hello, this is a test.", "voice_id": "alba",
                    "language_code": "en", "audio_format": "pcm_16000"}]),
    ("flat_min", [{"text": "Hello, this is a test."}]),
    ("va_flat", [{"voice": "alba", "format": "pcm_16000", "text": "Hello, this is a test."}]),
    ("typed_speak", [{"type": "speak", "text": "Hello, this is a test.", "voice_id": "alba"}]),
    ("typed_tts_start", [{"type": "tts.start", "text": "Hello, this is a test.",
                          "voice": "alba", "format": "pcm_16000"}]),
    ("session_update_then_text", [
        {"type": "session.update", "session": {"output": {"voice": "alba", "format": "pcm_16000"}}},
        {"type": "text", "text": "Hello, this is a test."},
    ]),
    ("configure_then_speak", [
        {"type": "configure", "voice": "alba", "format": "pcm_16000", "sample_rate": 16000},
        {"type": "speak", "text": "Hello, this is a test."},
    ]),
    ("raw_string", ["Hello, this is a test."]),
]


async def stage2(auth_modes):
    print("\n=== STAGE 2: schema candidates ===")
    best = None
    for name, url, headers in auth_modes:
        for cand_name, msgs in CANDIDATES:
            try:
                ws = await websockets.connect(url, additional_headers=headers, open_timeout=15)
            except Exception as e:
                print(f"  {name}/{cand_name}: connect fail {str(e)[:120]}")
                continue
            try:
                await drain(ws, 1.0, f"{cand_name}.pre")
                for m in msgs:
                    await ws.send(m if isinstance(m, str) else json.dumps(m))
                    await asyncio.sleep(0.4)
                texts, audio = await drain(ws, 5.0, cand_name)
                if audio:
                    path = os.path.join(AUDIO_OUT, f"{cand_name}.bin")
                    with open(path, "wb") as f:
                        f.write(audio)
                    print(f"  {cand_name}: AUDIO SAVED -> {path} ({len(audio)}B)")
                    if best is None:
                        best = (cand_name, name, audio)
                    return best  # one working schema is enough for this pass
            finally:
                try:
                    await ws.close()
                except Exception:
                    pass
    return best


async def main():
    if not KEY:
        sys.exit("ASSEMBLYAI_API_KEY not set")
    await stage0()
    modes = await stage1()
    print("\nworking auth modes:", [m[0] for m in modes])
    if modes:
        best = await stage2(modes)
        if best:
            print(f"\n>>> WORKING SCHEMA: {best[0]} (auth={best[1]}, {len(best[2])}B audio)")


if __name__ == "__main__":
    asyncio.run(main())
