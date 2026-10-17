# Babel

**Two people. Two languages. One conversation.**

A live bilingual voice interpreter: Speaker A talks in their language, Babel
live-dictates what they said (verbatim **and** cleaned), translates it, and
speaks the translation to Speaker B *in B's language* — and vice versa, in one
browser tab.

Built end-to-end on **AssemblyAI's voice stack**: Dictation API (STT) →
LLM Gateway (translation) → the brand-new **streaming TTS WebSocket**
(the API this hackathon is themed on).

> Voice agents today mostly talk *at* you, in one language, with no memory of
> how the other person actually talks. Real conversations across a language gap
> still need a human interpreter. Babel is that interpreter — sub-second after
> you stop speaking, the other person hears you in their own language.

## Why it's different

- **The new streaming TTS API is load-bearing, not bolted on.** It shipped with
  *zero public docs* — we reverse-engineered the whole WebSocket protocol
  (persistent sessions, `Generate`/`Flush` streaming, per-utterance voice +
  language overrides, base64 PCM 24 kHz frames, `WordBoundaries` timing
  metadata, clean `Terminate`): **[docs/tts-protocol.md](docs/tts-protocol.md)**.
  Babel's spoken output is 100% that API.
- **Translation quality leverages Dictation's cleanup.** We translate the
  *cleaned* transcript (`llm_response`: fillers stripped, self-corrections
  resolved) — and show the verbatim next to it, so the quality gain is visible.
- **Karaoke captions for free.** The TTS API's `WordBoundaries` metadata
  highlights each word of the spoken translation as it plays.
- **100% AssemblyAI stack** — Dictation (STT) + LLM Gateway (translation) +
  streaming TTS (voice). No third-party AI services.

## How it uses the AssemblyAI Dictation API

| Form capability | Where in Babel |
|---|---|
| **Real-time dictation / live transcription** | Audio streams to `POST /v1/transcribe/live` *while the user is still speaking* (uploading-while-recording; config part first, PCM chunks as captured), plus `GET /warm` pre-warming on mic press. |
| **Multi-language support** | Per-speaker `language_codes` (32 supported codes). Primary demo pair **EN↔ES** — fully verified end-to-end including karaoke word boundaries. **EN↔HI** available: Hindi dictation verified; Hindi TTS output observed but quality unverified (see FINDINGS F15). |
| **Filler-word removal / clean output** | Cleanup runs by default; we display verbatim *and* cleaned, and translate the cleaned `llm_response`. |
| **Custom vocabulary** | Per-speaker `keyterms_prompt` (names, jargon, product terms) — the demo pins invented keyterms "Zylkon Nimbus" and "Praxel" (fixtures prove the exact spellings survive). |

## Architecture

```
            browser (mic via AudioWorklet, 16 kHz PCM)
                 │  binary WS frames
                 ▼
   ┌─────────────────────────────────────────────────┐
   │  Babel server (FastAPI, one WS session)         │
   │                                                 │
   │  turn = Dictation ──► LLM Gateway ──► streaming │
   │        /v1/transcribe    /v1/chat/      TTS WS   │
   │        (verbatim +      completions   (Generate │
   │         cleaned)        (translate)    + Flush) │
   └─────────────────────────────────────────────────┘
                 │  captions + base64-decoded PCM audio
                 ▼
            browser (24 kHz playback queue, karaoke)
```

Every turn is instrumented: `stop→dictation`, `translation`, `first-audio`, and
`stop→spoken` latencies render as chips in the UI.

## Setup

```bash
uv sync                     # or: pip install fastapi uvicorn[standard] httpx websockets
cp .env.example .env        # add your AssemblyAI API key
uvicorn server:app --reload  # http://127.0.0.1:8000
```

`BABEL_ENGINE=mock` (automatic when no key is set) runs the whole pipeline
offline with a tone-synthesizing mock TTS — useful for UI development.

## Testing

```bash
python -m pytest -q                 # offline units: protocol shapes, event ordering, history
python scripts/gen_fixtures.py       # planted-truth bilingual fixtures (edge-tts + ffmpeg)
python scripts/smoke.py              # LIVE end-to-end: fixtures -> dictation -> translate -> TTS
```

Planted-truth fixtures (`fixtures/manifest.json`) assert exact behaviors:
fillers present in verbatim but absent from the cleaned text, keyterm
spellings survive, translations carry the planted gist words.

## Hackathon recon as bonus submissions

While building Babel we probed the streaming TTS API before it had any docs —
**[FINDINGS.md](FINDINGS.md)** collects every API-feedback and security
observation (undocumented-but-headline API, unauthenticated WS upgrades,
server banner leak, token-query-param parsing bug, silent no-ops on invalid
voice/language, session-cap behavior, voice-cloning surface), all with
reproducible probe scripts (`scripts/probe_tts*.py`).

## Verified claims (honesty layer)

Everything above marked as working was exercised live against the production
APIs during the build; `scripts/smoke.py` re-verifies it in one command. The
in-repo protocol document quotes only frames we actually received.

## Stack

Python 3.11+ (FastAPI, uvicorn, httpx, websockets) · vanilla JS browser client
(AudioWorklet capture, scheduled AudioBuffer playback) · AssemblyAI: Dictation,
LLM Gateway, streaming TTS. License: MIT.
