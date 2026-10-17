"""Offline unit tests — no network, no API key (mocks + fakes only)."""

import asyncio

from babel.audio import float32_to_pcm16, pcm16_to_float32, pcm16_to_wav
from babel.dictation import MockDictationClient, build_multipart
from babel.gateway import MockGateway, build_interpreter_messages, lang_name
from babel.interpreter import InterpreterSession
from babel.tts import MockStreamingTTS, TTSError, tts_language_name


def aiter(items):
    async def gen():
        for item in items:
            yield item
    return gen()


def test_wav_header_roundtrip():
    pcm = b"\x01\x00\x02\x00\xff\xff\x00\x00"
    wav = pcm16_to_wav(pcm, sample_rate=16000)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert wav[36:] == b"data" + (8).to_bytes(4, "little") + pcm


def test_pcm_conversion_roundtrip():
    floats = [0.0, 0.5, -0.5, 0.99, -1.0]
    pcm = float32_to_pcm16(floats)
    back = pcm16_to_float32(pcm)
    for a, b in zip(floats, back):
        assert abs(a - b) < 0.001


def test_multipart_config_arrives_before_audio():
    boundary = "btest123"
    gen = build_multipart({"sample_rate": 16000, "channels": 1},
                          aiter([b"AAAA", b"BBBB"]), boundary)
    assert gen.__name__ == "gen"

    async def collect():
        return b"".join([chunk async for chunk in gen])
    body = asyncio.run(collect())
    assert body.count(f"--{boundary}".encode()) == 3  # config, audio, epilogue
    config_idx = body.find(b'"sample_rate"')
    audio_idx = body.find(b"AAAA")
    assert 0 < config_idx < audio_idx
    assert body.endswith(f"\r\n--{boundary}--\r\n".encode())


def test_interpreter_messages_contain_language_and_history():
    msgs = build_interpreter_messages(text="hola", source_lang="es", target_lang="en",
                                      history=[{"side": "A", "lang": "es",
                                                "original": "buenos días",
                                                "translation": "good morning"}])
    assert msgs[0]["role"] == "system"
    assert "Spanish" in msgs[0]["content"] and "English" in msgs[0]["content"]
    assert any("buenos días" in m["content"] for m in msgs)
    assert msgs[-1]["content"] == "hola"
    assert lang_name("hi") == "Hindi"


def test_tts_error_raises():
    try:
        raise TTSError({"type": "Error", "error_code": 1008, "error": "Unauthorized"})
    except TTSError as e:
        assert "Unauthorized" in str(e)


def test_tts_language_mapping():
    assert tts_language_name("es") == "spanish"
    assert tts_language_name("spanish") == "spanish"
    assert tts_language_name("hi") == "hindi"


def test_mock_tts_event_order():
    async def collect():
        events = []
        async for ev in MockStreamingTTS().speak(text="hello there friend",
                                                 voice="alba", language="en"):
            events.append(ev)
        return events
    events = asyncio.run(collect())
    kinds = [e[0] for e in events]
    assert kinds[0] == "format"
    assert kinds[1] == "audio"
    total = sum(len(p) for k, p in events if k == "audio")
    assert total > 1000


def _make_session(scripted=None):
    scripted = scripted or {3: {"text": "so umm hi", "llm_response": "Hi"}}
    return InterpreterSession(
        dictation=MockDictationClient(scripted),
        gateway=MockGateway(),
        tts=MockStreamingTTS(),
        config={"A": {"language": "en", "voice": "alba"},
                "B": {"language": "es", "voice": "lola"}})


def _run_turn(session, side, chunks):
    return asyncio.run(_collect_turn(session, side, chunks))


async def _collect_turn(session, side, chunks):
    return [ev async for ev in session.handle_turn(side=side, audio_iter=aiter(chunks))]


def test_interpreter_full_turn_event_order():
    session = _make_session()
    events = _run_turn(session, "A", [b"\x00\x01", b"\x00"])
    json_types = [e[1]["type"] for e in events if e[0] == "json"]
    assert "captions" in json_types and "translation" in json_types and "turn-done" in json_types
    assert json_types.index("captions") < json_types.index("translation")
    assert json_types.index("translation") < json_types.index("turn-done")
    captions = [e[1] for e in events if e[0] == "json" and e[1]["type"] == "captions"][0]
    assert captions["verbatim"] == "so umm hi"
    assert captions["clean"] == "Hi"
    translation = [e[1] for e in events if e[0] == "json"
                   and e[1]["type"] == "translation"][0]
    assert translation["lang"] == "es" and translation["side"] == "A"
    done = [e[1] for e in events if e[0] == "json" and e[1]["type"] == "turn-done"][0]
    assert done["latencies"]["audio_bytes"] > 0
    assert session.history[-1]["original"] == "Hi"


def test_interpreter_no_speech_short_circuits():
    session = _make_session(scripted={2: {"text": "", "llm_response": ""}})
    events = _run_turn(session, "B", [b"\x00\x00"])
    json_types = [e[1]["type"] for e in events if e[0] == "json"]
    assert "translation" not in json_types
    done = [e[1] for e in events if e[0] == "json" and e[1]["type"] == "turn-done"][0]
    assert done.get("no_speech") is True


def test_interpreter_history_kept_bounded():
    session = _make_session()
    for _ in range(15):
        _run_turn(session, "A", [b"\x00\x01", b"\x00"])
    assert len(session.history) == 12
