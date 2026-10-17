"""Interpreter orchestration: one turn = dictation -> translation -> spoken audio.

Event contract (consumed by server.py):
  ("json",   {"type": "status" | "captions" | "translation" | "audio-format" | "turn-done", ...})
  ("binary", <pcm bytes>)
"""

import time


def _monotonic_ms() -> float:
    return time.monotonic() * 1000.0


class InterpreterSession:
    """Stateful two-sided interpreter: languages, keyterms, conversation history."""

    def __init__(self, *, dictation, gateway, tts, config: dict):
        self.dictation = dictation
        self.gateway = gateway
        self.tts = tts
        self.config = config
        self.history: list[dict] = []
        self.turn_count = 0

    def side_config(self, side: str) -> dict:
        side = side.upper()
        return self.config.get(side, {})

    def other_side(self, side: str) -> str:
        return "B" if side.upper() == "A" else "A"

    async def handle_turn(self, *, side: str, audio_iter):
        """Run one speaking turn end-to-end. `audio_iter` yields PCM chunks; exhaustion = turn end."""
        side = side.upper()
        other = self.other_side(side)
        side_cfg = self.side_config(side)
        out_cfg = self.side_config(other)
        source_lang = side_cfg.get("language", "en")
        target_lang = out_cfg.get("language", "en")
        voice = out_cfg.get("voice", "jane")
        self.turn_count += 1
        turn_id = self.turn_count
        t_start = _monotonic_ms()
        t_stop = None
        latencies: dict = {"turn_id": turn_id, "side": side, "source": source_lang,
                           "target": target_lang}

        async def timed_audio():
            nonlocal t_stop
            async for chunk in audio_iter:
                yield chunk
            t_stop = _monotonic_ms()

        yield ("json", {"type": "status", "stage": "dictation", "side": side,
                        "turn_id": turn_id})
        result = await self.dictation.transcribe_live(
            audio_iter=timed_audio(),
            language_codes=[source_lang],
            keyterms=side_cfg.get("keyterms") or self.config.get("keyterms"),
            stt_prompt=f"A person speaking {source_lang} in a live interpreted conversation.",
            llm_instruction=side_cfg.get("llm_instruction"),
        )
        verbatim = (result.get("text") or "").strip()
        clean = (result.get("llm_response") or verbatim).strip()
        t_dict = _monotonic_ms()
        latencies["stop_to_dictation_ms"] = round(t_dict - (t_stop or t_dict))

        yield ("json", {"type": "captions", "side": side, "verbatim": verbatim,
                        "clean": clean, "lang": source_lang, "turn_id": turn_id})

        if not clean:
            yield ("json", {"type": "turn-done", "no_speech": True, "latencies": latencies})
            return

        yield ("json", {"type": "status", "stage": "translation", "side": side,
                        "turn_id": turn_id})
        translation = await self.gateway.translate(
            text=clean, source_lang=source_lang, target_lang=target_lang,
            history=self.history)
        t_llm = _monotonic_ms()
        latencies["translation_ms"] = round(t_llm - t_dict)

        self.history.append({"side": side, "lang": source_lang, "original": clean,
                             "translation": translation})
        if len(self.history) > 12:
            del self.history[:-12]

        yield ("json", {"type": "translation", "side": side, "text": translation,
                        "lang": target_lang, "voice": voice, "turn_id": turn_id})

        yield ("json", {"type": "status", "stage": "synthesis", "side": side,
                        "turn_id": turn_id})
        t_first_audio = None
        audio_bytes = 0
        async for kind, payload in self.tts.speak(text=translation, voice=voice,
                                                  language=target_lang):
            if kind == "audio":
                audio_bytes += len(payload)
                if t_first_audio is None:
                    t_first_audio = _monotonic_ms()
                yield ("binary", payload)
            elif kind == "format":
                yield ("json", {"type": "audio-format", "encoding": payload.get("encoding"),
                                "sample_rate": payload.get("sample_rate"),
                                "voice": payload.get("voice"),
                                "turn_id": turn_id})
            elif kind == "meta":
                yield ("json", {"type": "audio-meta", "meta": payload, "turn_id": turn_id})

        latencies["tts_first_audio_ms"] = round(t_first_audio - t_llm) if t_first_audio else None
        latencies["stop_to_spoken_ms"] = round(t_first_audio - (t_stop or t_first_audio)) \
            if t_first_audio else None
        latencies["audio_bytes"] = audio_bytes
        yield ("json", {"type": "turn-done", "latencies": latencies})
