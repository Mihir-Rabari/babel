#!/usr/bin/env python3
"""Probe round 2 — build on the discovered streaming-TTS protocol.

Known (probe round 1): types Generate|Flush|Terminate|KeepAlive|Cancel|VoiceReference;
Begin config voice=jane language=english sample_rate=24000 encoding=pcm_s16le
word_boundaries=true; auth raw or ?token=; 3009 = concurrent session cap.

This round answers:
  T1  Generate+Flush semantics; completion event; connection REUSE for a 2nd turn;
      per-Generate voice/language overrides; KeepAlive reply; Terminate semantics
  T2  URL query config (?voice=alba)
  T3  Hindi (?language=hindi + Hindi text)
  T4  Error shapes: Generate w/o text; VoiceReference requirements; oversize text;
      bogus type; invalid voice
"""
import asyncio
import json
import os

import websockets

TTS_WS = "wss://streaming-tts.assemblyai.com/v1/ws"
KEY = os.environ.get("ASSEMBLYAI_API_KEY", "")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out")
os.makedirs(OUT, exist_ok=True)


def make_url(params: str = "") -> str:
    return TTS_WS + "?token=" + KEY + params


async def fresh(params: str = "", label: str = ""):
    """Connect (retrying through the 3009 concurrent cap); return (ws, begin)."""
    for attempt in (1, 2, 3):
        try:
            ws = await websockets.connect(make_url(params), open_timeout=15,
                                          max_size=64 * 1024 * 1024)
            begin = json.loads(await ws.recv())
            print(f"[{label or params}] CONNECTED")
            print(f"[{label or params}] BEGIN: {json.dumps(begin)}")
            return ws, begin
        except Exception as e:
            s = str(e)
            if "3009" in s and attempt < 3:
                print(f"[{label}] 3009 concurrent cap hit — waiting 30s (attempt {attempt})")
                await asyncio.sleep(30)
            else:
                print(f"[{label}] connect fail: {s[:200]}")
                raise


async def drain(ws, label: str, seconds: float):
    """Collect frames for `seconds`; print text frames, summarize audio."""
    loop = asyncio.get_event_loop()
    end = loop.time() + seconds
    audio = bytearray()
    texts = 0
    while True:
        left = end - loop.time()
        if left <= 0:
            break
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=left)
        except (asyncio.TimeoutError, websockets.ConnectionClosed) as e:
            rcvd = getattr(e, "rcvd", None)
            print(f"  [{label}] drain-end: {type(e).__name__}"
                  + (f" code={rcvd.code} reason={str(rcvd.reason)[:120]}" if rcvd else ""))
            break
        if isinstance(msg, bytes):
            audio.extend(msg)
        else:
            texts += 1
            print(f"  [{label}] TEXT: {msg[:300]}")
    print(f"  [{label}] drain: {texts} text frames, {len(audio)} audio bytes")
    return bytes(audio)


async def speak_collect(ws, label: str, text: str, overrides: dict | None = None,
                        collect_s: float = 12.0, save: str | None = None):
    """Generate (observe) -> Flush (collect) -> report. Returns audio bytes."""
    payload = {"type": "Generate", "text": text}
    if overrides:
        payload.update(overrides)
    await ws.send(json.dumps(payload))
    print(f"  [{label}] SENT Generate{'' if not overrides else ' + ' + str(overrides)}")
    pre = await drain(ws, label + ".after-generate", 2.5)
    await ws.send(json.dumps({"type": "Flush"}))
    print(f"  [{label}] SENT Flush")
    post = await drain(ws, label + ".after-flush", collect_s)
    audio = pre + post
    if audio and save:
        path = os.path.join(OUT, save)
        with open(path, "wb") as f:
            f.write(audio)
        print(f"  [{label}] SAVED {len(audio)}B -> {path}")
    return audio


async def main() -> None:
    if not KEY:
        raise SystemExit("ASSEMBLYAI_API_KEY not set")

    print("=== T1: one connection — generate, flush, reuse, overrides, keepalive, terminate ===")
    ws, _begin = await fresh(label="T1")
    await speak_collect(ws, "T1.turn1", "Hello, this is a test of the streaming text to speech API.",
                        save="probe2_hello.pcm")
    await speak_collect(ws, "T1.turn2-override",
                        "Hola, ¿cómo estás? Espero que todo salga bien.",
                        overrides={"voice": "lola", "language": "spanish"})
    await ws.send(json.dumps({"type": "KeepAlive"}))
    await drain(ws, "T1.keepalive", 2.0)
    await ws.send(json.dumps({"type": "Terminate"}))
    await drain(ws, "T1.terminate", 3.0)
    try:
        await ws.close()
    except Exception:
        pass
    await asyncio.sleep(3)

    print("\n=== T2: URL query config (?voice=alba) ===")
    try:
        ws, begin = await fresh("?voice=alba", "T2")
        await ws.close()
    except Exception as e:
        print("T2 failed:", str(e)[:200])
    await asyncio.sleep(3)

    print("\n=== T3: Hindi (?language=hindi) ===")
    try:
        ws, _ = await fresh("?language=hindi", "T3")
        await speak_collect(ws, "T3.hindi",
                            "नमस्ते, आप कैसे हैं? यह एक परीक्षण है।",
                            save="probe2_hindi.pcm")
        await ws.send(json.dumps({"type": "Terminate"}))
        await drain(ws, "T3.terminate", 2.0)
        await ws.close()
    except Exception as e:
        print("T3 failed:", str(e)[:200])
    await asyncio.sleep(3)

    print("\n=== T4: error shapes (fresh connection each — round 1 showed errors close the socket) ===")
    cases = [
        ("no-text", {"type": "Generate"}),
        ("voiceref-empty", {"type": "VoiceReference"}),
        ("bad-voice", {"type": "Generate", "text": "hi there", "voice": "not-a-voice"}),
        ("bad-language", {"type": "Generate", "text": "hello", "language": "klingon"}),
        ("bogus-type", {"type": "Bogus"}),
    ]
    for name, frame in cases:
        try:
            ws, _ = await fresh(label="T4." + name)
            await ws.send(json.dumps(frame))
            await drain(ws, "T4." + name + ".response", 3.0)
            try:
                await ws.close()
            except Exception:
                pass
        except Exception as e:
            print(f"T4.{name} stopped: {type(e).__name__} {str(e)[:200]}")
        await asyncio.sleep(2.5)


if __name__ == "__main__":
    asyncio.run(main())
