#!/usr/bin/env python3
"""Probe round 3 — close the last unknowns:

T5  Hindi via per-Generate language override (round-2 T3 failed only because of
    the token-query-param auth bug; per-Generate overrides are the real mechanism)
T6  Header auth + ?voice=alba query param — does URL config work when auth is a header?
T7  Re-confirm the token-query + extra-param auth bug (FINDINGS F10) once.
"""
import asyncio
import json
import os

import websockets

TTS_WS = "wss://streaming-tts.assemblyai.com/v1/ws"
KEY = os.environ.get("ASSEMBLYAI_API_KEY", "")


async def drain(ws, label, seconds):
    loop = asyncio.get_event_loop()
    end = loop.time() + seconds
    frames = 0
    audio_b64_chars = 0
    word_events = []
    while True:
        left = end - loop.time()
        if left <= 0:
            break
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=left)
        except (asyncio.TimeoutError, websockets.ConnectionClosed) as e:
            print(f"  [{label}] end: {type(e).__name__}")
            break
        frames += 1
        try:
            payload = json.loads(msg)
        except Exception:
            print(f"  [{label}] NON-JSON: {str(msg)[:80]}")
            continue
        t = payload.get("type")
        if t == "Audio":
            audio_b64_chars += len(payload.get("audio", ""))
        elif t == "WordBoundaries":
            word_events.append(payload)
            words = [w.get("word") for w in payload.get("words", [])][:12]
            print(f"  [{label}] WORDS: {words}")
        elif t in ("Error", "FlushDone", "Termination", "Begin"):
            print(f"  [{label}] {t}: {json.dumps(payload)[:260]}")
        else:
            print(f"  [{label}] {t}: {json.dumps(payload)[:160]}")
    print(f"  [{label}] summary: {frames} frames, {audio_b64_chars} base64 audio chars, "
          f"{len(word_events)} word-events")
    return audio_b64_chars


async def speak(ws, label, text, voice, language, collect_s=10):
    await ws.send(json.dumps({"type": "Generate", "text": text,
                             "voice": voice, "language": language}))
    await asyncio.sleep(0.3)
    await ws.send(json.dumps({"type": "Flush"}))
    return await drain(ws, label, collect_s)


async def main():
    print("=== T5: Hindi via per-Generate language ===")
    try:
        ws = await websockets.connect(TTS_WS, additional_headers={"Authorization": KEY},
                                      open_timeout=15, max_size=64 * 1024 * 1024)
        print("  [T5] connected:", json.dumps(json.loads(await ws.recv()))[:200])
        await speak(ws, "T5.hindi", "नमस्ते, आप कैसे हैं? यह एक परीक्षण है।",
                    voice="jane", language="hindi")
        await ws.send(json.dumps({"type": "Terminate"}))
        await drain(ws, "T5.terminate", 2)
        await ws.close()
    except Exception as e:
        print("T5 failed:", type(e).__name__, str(e)[:200])
    await asyncio.sleep(3)

    print("=== T6: header auth + ?voice=alba query param ===")
    try:
        ws = await websockets.connect(TTS_WS + "?voice=alba",
                                     additional_headers={"Authorization": KEY},
                                     open_timeout=15, max_size=64 * 1024 * 1024)
        print("  [T6] connected:", json.dumps(json.loads(await ws.recv()))[:300])
        await speak(ws, "T6.voice-check", "Checking the voice configuration.",
                    voice="alba", language="english")
        await ws.send(json.dumps({"type": "Terminate"}))
        await ws.close()
    except Exception as e:
        print("T6 failed:", type(e).__name__, str(e)[:200])
    await asyncio.sleep(3)

    print("=== T7: re-confirm token+param auth bug (F10) ===")
    try:
        ws = await websockets.connect(TTS_WS + "?token=" + KEY + "&voice=alba",
                                      open_timeout=15)
        print("  [T7] first frame:", (await ws.recv())[:160])
        await ws.close()
    except Exception as e:
        print("T7:", type(e).__name__, str(e)[:200])


if __name__ == "__main__":
    asyncio.run(main())
