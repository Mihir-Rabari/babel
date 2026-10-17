"""Babel server: one WebSocket session per browser, one interpreter per session.

Client -> server JSON: {type: "configure", config}, {type: "turn-start", side},
{type: "turn-end"}, {type: "abort"}, {type: "prewarm"}.
Client binary frames: raw S16LE PCM 16 kHz mono chunks for the open turn.
Server -> client: JSON events + binary audio frames for playback.
"""

import asyncio
import json
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from babel.dictation import DictationClient, MockDictationClient
from babel.gateway import TranslationGateway, MockGateway
from babel.interpreter import InterpreterSession
from babel.tts import MockStreamingTTS, StreamingTTSClient

KEY = os.environ.get("ASSEMBLYAI_API_KEY", "")
ENGINE = os.environ.get("BABEL_ENGINE", "assemblyai" if KEY else "mock")
MAX_CHUNK_BYTES = 32_768

app = FastAPI(title="Babel", version="0.1.0")
app.mount("/static", StaticFiles(directory="static"), name="static")


def _make_engines():
    if ENGINE == "assemblyai" and KEY:
        return (DictationClient(KEY), TranslationGateway(KEY), StreamingTTSClient(KEY))
    return MockDictationClient(), MockGateway(), MockStreamingTTS()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(os.path.join("static", "index.html"))


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "engine": ENGINE, "key_present": bool(KEY)}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    dictation, gateway, tts = _make_engines()
    session = InterpreterSession(dictation=dictation, gateway=gateway, tts=tts,
                                 config={"A": {"language": "en"},
                                         "B": {"language": "es"}})
    audio_queue: asyncio.Queue | None = None
    turn_task: asyncio.Task | None = None
    keepalive_task: asyncio.Task | None = None

    def queue_to_iter(queue: asyncio.Queue):
        async def gen():
            while True:
                item = await queue.get()
                if item is None:
                    return
                yield item
        return gen()

    async def pump_turn(side: str, queue: asyncio.Queue) -> None:
        try:
            async for kind, payload in session.handle_turn(
                    side=side, audio_iter=queue_to_iter(queue)):
                if kind == "json":
                    await websocket.send_text(json.dumps(payload))
                elif kind == "binary":
                    await websocket.send_bytes(payload)
        except Exception as exc:  # surface pipeline failures to the client
            await websocket.send_text(json.dumps(
                {"type": "error", "stage": "pipeline", "message": str(exc)[:500]}))
        finally:
            await websocket.send_text(json.dumps({"type": "turn-finished"}))

    async def keepalive_loop() -> None:
        while True:
            await asyncio.sleep(30)
            try:
                await tts.keepalive()
            except Exception:
                return

    try:
        keepalive_task = asyncio.create_task(keepalive_loop())
        while True:
            msg = await websocket.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if "text" in msg and msg["text"] is not None:
                data = json.loads(msg["text"])
                mtype = data.get("type")
                if mtype == "configure":
                    session.config = data.get("config", session.config)
                    await websocket.send_text(json.dumps({"type": "configured",
                                                          "engine": ENGINE}))
                elif mtype == "prewarm":
                    await dictation.warm()
                elif mtype == "turn-start":
                    if turn_task and not turn_task.done():
                        await websocket.send_text(json.dumps(
                            {"type": "error", "stage": "turn",
                             "message": "turn already in progress"}))
                        continue
                    audio_queue = asyncio.Queue()
                    turn_task = asyncio.create_task(
                        pump_turn(data.get("side", "A"), audio_queue))
                elif mtype == "turn-end":
                    if audio_queue is not None:
                        await audio_queue.put(None)
                elif mtype == "abort":
                    if turn_task and not turn_task.done():
                        turn_task.cancel()
                    if audio_queue is not None:
                        await audio_queue.put(None)
                    await websocket.send_text(json.dumps({"type": "aborted"}))
            elif "bytes" in msg and msg["bytes"] is not None:
                if audio_queue is not None and len(msg["bytes"]) <= MAX_CHUNK_BYTES:
                    await audio_queue.put(msg["bytes"])
    except WebSocketDisconnect:
        pass
    finally:
        if turn_task and not turn_task.done():
            turn_task.cancel()
        if keepalive_task and not keepalive_task.done():
            keepalive_task.cancel()
        try:
            await tts.close()  # Terminate frees the TTS concurrent-session slot
        except Exception:
            pass
