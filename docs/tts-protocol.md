# The AssemblyAI Streaming TTS WebSocket Protocol

**Reverse-engineered live on 2026-10-17** from `wss://streaming-tts.assemblyai.com/v1/ws` —
the API AssemblyAI's Voice Hackathon Week is themed on, which shipped with **zero public
documentation** (0 mentions in the entire 3.66 MB `/docs/llms-full.txt` dump; the public
FAQ even states "AssemblyAI does not offer standalone text-to-speech as a separate
service"). Everything below was observed by probing the production endpoint with our own
API key; probe scripts: `scripts/probe_tts.py`, `probe_tts2.py`, `probe_tts3.py`.
Raw session transcripts are quoted at the bottom of `FINDINGS.md`.

This document is what we wish the docs page had been. Server: `Python/3.13 websockets/15.0.1`.

## Connection & auth

```
GET wss://streaming-tts.assemblyai.com/v1/ws
```

- Auth **either** via query param: `?token=<API_KEY>` **or** raw header `Authorization: <API_KEY>`.
- `Authorization: Bearer <key>` is **rejected** (`1008 Unauthorized: Invalid API key`).
- **Flaky auth parsing (F10):** with token-query auth, an additional query param
  **intermittently** broke auth — `?token=<key>&voice=alba` returned
  `1008 Invalid API key` twice (round 2), then connected fine on retest (round 3).
  Same URL shape, different outcomes minutes apart. If you need query params,
  prefer raw-key header auth — `?voice=alba` under header auth applied cleanly.
- The upgrade (HTTP `101`) is sent **before** any auth check — unauthenticated clients
  get the handshake + server banner, then a JSON error frame, then close.
- **Concurrent-session cap per account** (error 3009 "Too many concurrent sessions for
  this account; try again later"). Sessions linger: `inactivity_timeout: null`. Terminate
  cleanly (`Terminate`) to free the slot. Sessions also have `expires_at`.

## Session lifecycle

On connect the server immediately sends:

```json
{"type": "Begin", "id": "<uuid>", "expires_at": <unix-seconds>,
 "configuration": {"voice": "jane", "language": "english", "sample_rate": 24000,
                  "encoding": "pcm_s16le", "inactivity_timeout": null,
                  "word_boundaries": true, "voice_clone": false,
                  "voice_clone_preprocess": false}}
```

The connection is **persistent and reusable**: you may speak many turns over one
connection; `flush_id` increments per turn; the audio timeline is cumulative per session.

## Client messages

| Message | Purpose |
|---|---|
| `{"type": "Generate", "text": "..."}` | Buffer text for synthesis. Required field: `text`. Optional overrides: `voice`, `language` (see below). |
| `{"type": "Flush"}` | Synthesize everything buffered so far. |
| `{"type": "KeepAlive"}` | Keep the session alive while idle. No visible reply. |
| `{"type": "Terminate"}` | End the session cleanly. |
| `{"type": "Cancel"}` | (not exercised by us) presumably cancels buffered-but-unflushed text. |
| `{"type": "VoiceReference", "audio": ...}` | Voice cloning by reference audio. Requires an `audio` field (we did NOT exercise cloning). |

`Generate` **buffers silently** — nothing is spoken until `Flush`. This means you can
stream text in incrementally (e.g., token-by-token from an LLM) and flush to end an
utterance: a text-in / audio-out analogue of the streaming STT API.

### Per-Generate overrides (verified)

`voice` and `language` can be sent **inside each Generate**, overriding the session
defaults for that utterance:

```json
{"type": "Generate", "text": "Hola, ¿cómo estás?", "voice": "lola", "language": "spanish"}
```

This produced Spanish audio with Spanish `WordBoundaries` on a mid-connection turn —
the exact mechanism a bilingual product needs. `language` takes English full names
(`english`, `spanish`, …), not ISO codes. Voice ids match the Voice Agent API voices
(`jane` default, `alba`, `lola`, `giovanni`, …).

**Language support observed:** `english` and `spanish` synthesize with full
`WordBoundaries` metadata. `hindi` is accepted without error but produced far
shorter audio than the input warranted (0.8 s for a ~3 s sentence) and emitted no
`WordBoundaries` — treat languages beyond English/Spanish as experimental until
verified.

## Server frames

| Frame | Meaning |
|---|---|
| `{"type": "Audio", "audio": "<base64>"}` | One chunk of synthesized audio. **base64 PCM S16LE mono @ 24 kHz** (per Begin configuration) delivered in TEXT frames — not binary WebSocket frames. |
| `{"type": "FlushDone", "flush_id": N, "audio_duration_ms": M}` | Synthesis of flush N complete. |
| `{"type": "WordBoundaries", "flush_id": N, "audio_start_ms": S, "words": [{"word", "start", "end", "confidence"}]}` | Word-level timing (ms, cumulative session timeline). Perfect for karaoke captions. |
| `{"type": "Termination", "session_duration_seconds", "total_input_char_length", "audio_duration_seconds"}` | Stats on Terminate, then close `1000 "Session ended"`. |
| `{"type": "Error", "error_code": C, "error": "..."}` | Error; the socket then closes with close code = error code. |

Typical frame order per flush: `Audio`×N → `FlushDone` → `WordBoundaries`.

## Errors (observed catalog)

| Code | Seen for |
|---|---|
| `1008` | Missing/invalid auth, or Bearer auth, or token + extra query params (F10 bug) |
| `3006` | `Missing 'type' field`; `Generate.text: Field required`; `VoiceReference.audio: Field required`; `unknown message type '<x>'; expected one of 'Generate', 'Flush', 'Terminate', 'KeepAlive', 'Cancel', 'VoiceReference'` |
| `3009` | Too many concurrent sessions for the account |

**Silent no-op (F11):** an *invalid* `voice` or `language` value in `Generate` produces
**no error frame and no audio** — the turn just yields nothing after `Flush`. Validate
inputs client-side.

## Bandwidth note (F12)

base64-in-JSON audio carries ~33% overhead vs binary frames. For a voice product the
audio is small (24 kHz mono ≈ 48 kB/s), so it's fine — but binary frames would be better.

## Reference client

`babel/tts.py` implements all of the above: persistent connection, per-turn
voice/language, reconnect-once on error, WordBoundaries passthrough, Terminate on close.
