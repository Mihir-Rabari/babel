# Babel — Voice Hackathon Week submission copy

Form: https://forms.gle/NtYDsi3bgqMDK29j9 (created inside AssemblyAI; Oct 17–24, 2026)
Repo: https://github.com/Mihir-Rabari/babel
Demo video: https://github.com/Mihir-Rabari/babel/releases/download/v0.1.0/babel-demo.mp4

---

**What are you submitting?** *(select all that apply)*
☑ A project I built  ☑ API feedback  ☑ Security issue report
*(one response covers all three — the feedback + security material is FINDINGS.md in the repo,
16 first-hand observations, all with reproducible probe scripts)*

**Team or submitter name:** Babel — Mihir Rabari

**Team members' names and emails (if a team):**
Mihir Rabari, mihirrabari2604@gmail.com, Discord: [ASK]

**Twitter or LinkedIn or both:** [ASK]

**Primary contact email:** mihirrabari2604@gmail.com

**Discord username:** [ASK]

**Project name:** Babel

**One-line project tagline:** Two people. Two languages. One conversation.

**Project description** *(what it does, problem it solves, how it uses the Dictation API)*:

Babel is a live bilingual voice interpreter: Speaker A talks in their language, Babel
live-dictates what they said (verbatim AND cleaned), translates it, and speaks the
translation to Speaker B in B's own language — and vice versa, with karaoke word
highlighting on the spoken translation. In live runs, the other person hears you
1.45–2.4 s after you stop speaking.

Voice agents today mostly talk *at* you, in one language. Real conversations across a
language gap still need a human interpreter. Babel is that interpreter — and every piece
of AI in the loop is AssemblyAI: Dictation (STT) → LLM Gateway (translation) → the new
streaming TTS WebSocket (voice). No third-party AI services.

How it uses the AssemblyAI Dictation API:
- **Real-time dictation:** audio streams to `/v1/transcribe/live` *while the user is
  still speaking* (uploading-while-recording; config part first, PCM chunks as
  captured), plus `GET /warm` TLS pre-warming on mic press.
- **Multi-language:** per-speaker `language_codes` (32 supported); demo pairs
  EN↔ES (fully verified incl. karaoke word boundaries) and EN↔HI (Hindi dictation
  verified; Hindi TTS observed but quality unverified — FINDINGS F15).
- **Filler-word removal:** we translate the *cleaned* `llm_response` (fillers
  stripped, self-corrections resolved) and display the verbatim beside it, so the
  quality gain is visible on screen.
- **Custom vocabulary:** per-speaker `keyterms_prompt` — planted keyterms "Zylkon
  Nimbus" and "Praxel" survive verbatim into the Spanish translation in our
  fixture tests.

The hackathon's streaming TTS API (`wss://streaming-tts.assemblyai.com/v1/ws`) shipped
with zero public docs — we reverse-engineered the complete protocol live
(`docs/tts-protocol.md`: message types, persistent sessions, per-utterance
voice/language overrides, base64 PCM 24 kHz frames, WordBoundaries timing, session
lifecycle) and Babel's entire spoken output runs through it.

Verification: 6/6 live end-to-end smoke tests against the real APIs (planted-truth
fixtures), 10 unit tests, all latencies in the UI read from live runs.

**Bugs / Feedback:**
FINDINGS.md in the repo — 16 observations from live probing, e.g.: the headline TTS API
is undocumented (0 mentions in the 3.66 MB docs dump; the FAQ even says standalone TTS
doesn't exist); WS upgrades are accepted before auth (server banner leak); flaky token
auth when extra query params are present; invalid voice/language silently produce no
audio; voice-cloning `VoiceReference` requires only an audio field with no visible
consent gating; session caps undocumented; WordBoundaries metadata excellent but
undocumented.

**Which Dictation API capabilities does your project use?** *(select all that apply)*
☑ Real-time dictation / live transcription
☑ Multi-language support (18 languages)
☑ Filler-word removal / clean output
☑ Custom vocabulary / other integration

**Tech stack / frameworks used:**
Python 3.13, FastAPI, uvicorn, httpx, websockets; vanilla-JS browser client
(AudioWorklet mic capture, scheduled AudioBuffer playback); AssemblyAI Dictation API +
LLM Gateway (qwen3.5-4b-32k-fast) + streaming TTS WebSocket; edge-tts + ffmpeg +
PIL for the reproducible fixture/video pipeline; Docker/Dokploy deploy.

**Demo video link:**
https://github.com/Mihir-Rabari/babel/releases/download/v0.1.0/babel-demo.mp4
(1:46; every number shown was measured in live runs; reproducible via
`scripts/make_demo_video.py`)

**Live demo or hosted app link (if available):**
[TODO — deployed URL lands when the Dokploy deploy completes; mic-free "Auto demo"
button replays a bundled EN↔ES conversation through the identical pipeline]

**Source code repository link:**
https://github.com/Mihir-Rabari/babel

**Screenshots or a recording (optional):**
docs/img/ in the repo (real UI frames from live runs); release asset above is the recording.
