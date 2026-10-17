# FINDINGS — AssemblyAI Voice Hackathon Week recon

Live probing of AssemblyAI's APIs on 2026-10-17 with our own API key, for the
API-feedback and security-issue submissions. Every item below was observed
first-hand; probe scripts are in `scripts/probe_tts.py` (round 1) and
`scripts/probe_tts2.py` (round 2) so anything here is reproducible.

## Streaming TTS API — `wss://streaming-tts.assemblyai.com/v1/ws` (undocumented)

- **F1 — Zero public docs for a headline API.** 0 mentions of `streaming-tts`
  in the entire 3.66 MB `/docs/llms-full.txt` dump; the public FAQ
  (`docs/faq/do-you-offer-voice-to-voice-or-text-to-speech-tts`) even states
  "AssemblyAI does not offer standalone text-to-speech as a separate service."
  Suggestion: publish a docs page before judging starts — half the field is
  locked out of the API the hackathon is themed on. (We reverse-engineered it;
  protocol notes in `docs/tts-protocol.md`.)
- **F2 — Unauthenticated WebSocket upgrades are accepted.** The server returns
  `101 Switching Protocols` (and its banner, F3) *before* any auth check, then
  rejects with a JSON error frame `{"type":"Error","error_code":1008,...}`.
  Unauthenticated clients should be rejected at the handshake.
- **F3 — Server stack leak.** Handshake response advertises
  `Server: Python/3.13 websockets/15.0.1` to unauthenticated clients.
- **F4 — Error messages enumerate the message protocol.** A frame without a
  recognized `type` returns the full valid set:
  `'Generate', 'Flush', 'Terminate', 'KeepAlive', 'Cancel', 'VoiceReference'`.
  Convenient for us — but it is free protocol recon for any unauthenticated-ish
  probing, and there are no docs to accompany it.
- **F5 — Concurrent-session cap with lingering sessions.** Error 3009
  "Too many concurrent sessions for this account" triggers after a handful of
  rapid connections. Sessions advertise `inactivity_timeout: null`, and
  sessions appear to linger after abrupt client disconnects. The cap value and
  session lifetime are undocumented; suggest documenting limits + a
  session-count/dashboard or headers like `X-Concurrent-Sessions-Limit`.
- **F6 — Voice-cloning surface (`VoiceReference`, `voice_clone` flags).** The
  default session `Begin` configuration carries `voice_clone` /
  `voice_clone_preprocess` flags, and `VoiceReference` is a first-class message
  type. Question for the security review: what consent/verification gates exist
  around cloning a reference voice through this API? (We did not attempt an
  actual clone — see T4 probe output for the observed request shape.)

## Dictation API (`dictation.assemblyai.com`)

- **F7 — Good observability, worth advertising.** Responses carry
  `request_time_ms`, `sync_time_ms`, `auth_time_ms`, `confidence`,
  `audio_duration_ms`, `session_id`. A 0.5 s silence clip returned in ~222 ms
  total. Suggestion: document these fields — they make latency work (like
  ours) much easier.
- **F8 — `llm_response` is `null` (not empty string) on no speech** while
  `text` is `""` — a small type inconsistency clients must handle both ways.

## LLM Gateway (`llm-gateway.assemblyai.com`)

- **F9 — Works as documented** (OpenAI-shaped, raw-key auth, `request_id`
  echoed). No findings; fast.

## Round 2+3 — protocol findings while wiring the real client

- **F10 — Flaky auth parsing with token + query params.** Round 2: `?token=<key>&voice=alba`
  and `?token=<key>&language=hindi` both returned `1008 Unauthorized: Invalid API key`
  (2/2). Round 3 retest: the identical `?token=<key>&voice=alba` URL connected successfully
  and applied the voice. Non-deterministic; worth a look. Under raw-key header auth,
  `?voice=alba` works consistently (see F16).
- **F11 — Silent no-op on invalid voice/language.** `Generate` with
  `voice: "not-a-voice"` or `language: "klingon"` produces NO error frame and NO audio —
  the turn just yields nothing after `Flush`. Invalid *fields* get loud errors; invalid
  *values* get silence. Clients can't tell "unsupported voice" from "nothing to say".
- **F12 — Audio rides base64 inside JSON TEXT frames** (`{"type":"Audio","audio":...}`),
  ~33% bandwidth overhead vs binary WebSocket frames. Fine at 24 kHz mono; worth
  documenting the frame type explicitly since "websocket audio" implies binary frames
  to most implementers.
- **F13 — Voice-cloning request shape.** `VoiceReference` requires a single `audio` field
  (the validation error names it). Combined with `voice_clone` flags in the session
  config, this exposes reference-audio voice cloning with no visible consent or
  verification gating at the protocol level. We did not exercise cloning — flagging the
  surface for the security review.
- **F14 — WordBoundaries metadata is excellent and undocumented** (word, start, end,
  confidence, per flush, cumulative session timeline). Perfect for karaoke captions.
- **F15 — Hindi synthesis accepted but degraded.** `language: "hindi"` synthesizes
  without error but produced 0.8 s of audio for a ~3-4 s sentence and emitted zero
  `WordBoundaries` events (English and Spanish both emit them). Worth verifying before
  marketing broad language coverage.
- **F16 — Undocumented session config via URL query params.** With header auth,
  `?voice=alba` sets the session voice (the `Begin` configuration reflects it). No docs
  mention this mechanism.

## Round-1 raw evidence (abbreviated)

```
HTTP/1.1 101 Switching Protocols
Server: Python/3.13 websockets/15.0.1
{"type":"Error","error_code":1008,"error":"Unauthorized: missing Authorization header or token query param"}
{"type":"Error","error_code":3006,"error":"Missing 'type' field"}
{"type":"Error","error_code":3006,"error":"Invalid message: unknown message type 'speak'; expected one of 'Generate', 'Flush', 'Terminate', 'KeepAlive', 'Cancel', 'VoiceReference'"}
{"type":"Begin","id":"…","expires_at":…,"configuration":{"voice":"jane","language":"english","sample_rate":24000,"encoding":"pcm_s16le","inactivity_timeout":null,"word_boundaries":true,"voice_clone":false,"voice_clone_preprocess":false}}
{"type":"Error","error_code":3009,"error":"Too many concurrent sessions for this account; try again later"}
```
