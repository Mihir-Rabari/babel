#!/usr/bin/env python3
"""End-to-end smoke against the REAL AssemblyAI stack (needs ASSEMBLYAI_API_KEY).

Per planted-truth fixture: Dictation (verbatim + cleaned) -> Gateway translate
-> streaming TTS audio. Asserts dictation markers hard; LLM gist checks are
warnings (translation wording varies), TTS must yield audio.
Prints a latency table. Run AFTER scripts/gen_fixtures.py.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from babel.dictation import DictationClient  # noqa: E402
from babel.gateway import TranslationGateway  # noqa: E402
from babel.tts import StreamingTTSClient  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "..", "fixtures")
OUT = os.path.join(HERE, "..", "out")
os.makedirs(OUT, exist_ok=True)

TARGETS = {"en": "es", "es": "en", "hi": "en"}  # demo translation directions


async def dictation_of(client: DictationClient, wav_path: str, lang: str,
                       keyterms=None) -> dict:
    data = open(wav_path, "rb").read()

    async def gen():
        yield data
    return await client.transcribe_live(audio_iter=gen(), language_codes=[lang],
                                        keyterms=keyterms)


async def main() -> None:
    key = os.environ.get("ASSEMBLYAI_API_KEY", "")
    if not key:
        raise SystemExit("ASSEMBLYAI_API_KEY not set")
    manifest = json.load(open(os.path.join(FIXTURES, "manifest.json")))
    dictation = DictationClient(key)
    gateway = TranslationGateway(key)
    tts = StreamingTTSClient(key)
    failures = []

    print(f"{'clip':<14}{'verbatim':<42}{'clean':<34}{'lat(s)':<8}result")
    for clip in manifest["clips"]:
        wav_path = os.path.join(FIXTURES, clip["name"] + ".wav")
        if not os.path.exists(wav_path):
            failures.append(f"{clip['name']}: fixture missing — run gen_fixtures.py")
            continue
        lang = clip["voice"]
        planted = clip.get("planted", {})
        result = await dictation_of(dictation, wav_path, lang,
                                   keyterms=clip.get("keyterms"))
        verbatim = (result.get("text") or "").strip()
        clean = (result.get("llm_response") or verbatim).strip()
        ok = True

        for marker in planted.get("verbatim_markers", []):
            if marker.lower() not in verbatim.lower():
                failures.append(f"{clip['name']}: verbatim missing {marker!r} -> {verbatim[:80]}")
                ok = False
        for marker in planted.get("clean_absent_markers", []):
            if marker.lower() in clean.lower():
                failures.append(f"{clip['name']}: clean still contains filler {marker!r} -> {clean[:80]}")
                ok = False
        for marker in planted.get("clean_gist", []):
            if marker.lower() not in clean.lower():
                failures.append(f"{clip['name']}: clean gist missing {marker!r} -> {clean[:80]}")
                ok = False

        translation = await gateway.translate(text=clean, source_lang=lang,
                                              target_lang=TARGETS[lang])
        for marker in planted.get("translation_en_gist", []):
            if marker.lower() not in translation.lower():
                failures.append(f"{clip['name']}: translation gist missing {marker!r} -> {translation[:80]}")

        audio_bytes = 0
        first_meta = None
        audio_buf = bytearray()
        async for kind, payload in tts.speak(text=translation,
                                             voice="lola" if TARGETS[lang] == "es" else "alba",
                                             language=TARGETS[lang]):
            if kind == "format":
                first_meta = payload
            elif kind == "audio":
                audio_bytes += len(payload)
                audio_buf.extend(payload)
        if audio_bytes < 1000:
            failures.append(f"{clip['name']}: TTS produced only {audio_bytes} bytes")
            ok = False
        if audio_bytes:
            with open(os.path.join(OUT, clip["name"] + "_tts.pcm"), "wb") as f:
                f.write(audio_buf)

        lat_s = (result.get("request_time_ms") or 0) / 1000.0
        print(f"{clip['name']:<14}{verbatim[:40]:<42}{clean[:32]:<34}{lat_s:<8.2f}"
              f"{'PASS' if ok else 'FAIL'}")
        print(f"  translation[{TARGETS[lang]}]: {translation[:100]}")
        print(f"  tts: {audio_bytes} bytes, meta={json.dumps(first_meta)[:160]}")

    print()
    if failures:
        print("FAILURES:")
        for f in failures:
            print(" -", f)
        raise SystemExit(1)
    print("SMOKE: all assertions passed")


if __name__ == "__main__":
    asyncio.run(main())
