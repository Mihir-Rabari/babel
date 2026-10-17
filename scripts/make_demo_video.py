#!/usr/bin/env python3
"""Assemble the Babel demo video from committed assets.

Reproducible from the repo: PIL title cards + real UI screenshots (docs/img/)
+ edge-tts narration + per-scene ffmpeg assembly -> out/video/babel-demo.mp4.
Every screenshot is a real frame of the app running against the live
AssemblyAI pipeline; every number on the cards was observed in those runs.
"""
import os
import subprocess

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
IMG = os.path.join(ROOT, "docs", "img")
OUT = os.path.join(ROOT, "out", "video")
CARDS = os.path.join(OUT, "cards")
os.makedirs(CARDS, exist_ok=True)
W, H = 1280, 720
VOICE = "en-US-AndrewMultilingualNeural"

BG = (11, 16, 32)
TEXT = (232, 236, 247)
MUTED = (147, 160, 196)
ACCENT = (126, 226, 184)
BLUE = (91, 156, 255)
GREEN = (52, 211, 153)

FONTDIR = "/usr/share/fonts/truetype/dejavu/"


def font(size, bold=False, mono=False):
    fam = "DejaVuSansMono" if mono else "DejaVuSans"
    name = fam + ("-Bold" if bold else "") + ".ttf"
    return ImageFont.truetype(FONTDIR + name, size)


def draw_centered(draw, y, text, fnt, fill):
    bbox = draw.textbbox((0, 0), text, font=fnt)
    draw.text(((W - (bbox[2] - bbox[0])) // 2, y), text, font=fnt, fill=fill)
    return bbox[3] - bbox[1]


def make_card(path, rows):
    """rows: list of (text, size, bold, mono, color) — stacked, vertically centered."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    heights = []
    for text, size, bold, mono, _ in rows:
        fnt = font(size, bold, mono)
        bbox = d.textbbox((0, 0), text, font=fnt)
        heights.append(bbox[3] - bbox[1] + 26)
    total = sum(heights)
    y = (H - total) // 2
    for (text, size, bold, mono, color), h in zip(rows, heights):
        fnt = font(size, bold, mono)
        draw_centered(d, y, text, fnt, color)
        y += h
    img.save(path)


def build_cards():
    make_card(os.path.join(CARDS, "card_title.png"), [
        ("BABEL", 150, True, False, TEXT),
        ("two people · two languages · one conversation", 34, False, False, ACCENT),
        ("Dictation → LLM Gateway → Streaming TTS", 30, False, True, MUTED),
        ("AssemblyAI Voice Hackathon Week 2026", 26, False, False, MUTED),
    ])
    make_card(os.path.join(CARDS, "card_pipeline.png"), [
        ("the pipeline", 44, True, False, TEXT),
        ("mic ──16 kHz PCM, streamed while speaking──▶  DICTATION  (verbatim + cleaned)", 22, False, True, TEXT),
        ("DICTATION ──cleaned transcript──▶  LLM GATEWAY  (faithful interpretation)", 22, False, True, TEXT),
        ("GATEWAY ──translation──▶  STREAMING TTS  (spoken in the other language)", 22, False, True, TEXT),
        ("STREAMING TTS ──WordBoundaries──▶  karaoke captions in the UI", 22, False, True, TEXT),
        ("keyterms_prompt pins names & jargon · 100% AssemblyAI stack", 24, False, False, ACCENT),
    ])
    make_card(os.path.join(CARDS, "card_protocol.png"), [
        ("the streaming TTS API shipped with ZERO public docs", 36, True, False, TEXT),
        ("we reverse-engineered it, live", 30, False, False, ACCENT),
        ("Generate · Flush · Terminate · KeepAlive · Cancel · VoiceReference", 22, False, True, TEXT),
        ("persistent sessions · per-utterance voice + language overrides", 22, False, True, TEXT),
        ("base64 PCM 24 kHz frames · WordBoundaries word timing", 22, False, True, TEXT),
        ("full spec: docs/tts-protocol.md in the repo", 24, False, False, MUTED),
    ])
    make_card(os.path.join(CARDS, "card_verified.png"), [
        ("verified, not claimed", 48, True, False, TEXT),
        ("6/6 live E2E smoke · 10/10 unit tests · planted-truth fixtures", 26, False, True, TEXT),
        ("stop→spoken: 1.45–2.4 s   (live runs)", 28, False, True, ACCENT),
        ("dictation < 500 ms · translation < 900 ms · first audio ~1 s", 24, False, True, TEXT),
        ("16 API feedback + security findings → submitted separately", 24, False, False, MUTED),
    ])
    make_card(os.path.join(CARDS, "card_closing.png"), [
        ("BABEL", 120, True, False, TEXT),
        ("github.com/Mihir-Rabari/babel", 32, False, True, ACCENT),
        ("16 API findings · protocol spec · reproducible tests", 24, False, False, MUTED),
        ("thank you", 30, False, False, TEXT),
    ])


SCENES = [
    ("card_title.png",
     "Babel. Two people, two languages, one conversation. A live bilingual "
     "voice interpreter, built end to end on AssemblyAI's voice stack."),
    ("scene_ready.png",
     "Speaker A talks in English. Speaker B replies in Spanish. Babel "
     "live-dictates every word, cleans up the disfluencies, translates, and "
     "speaks the translation in the other person's language."),
    ("scene_full_convo.png",
     "The verbatim transcript is always kept. The cleaned version — fillers "
     "stripped, self-corrections resolved — is what gets translated. The "
     "other person hears it roughly one and a half to two and a half seconds "
     "after you stop speaking. Every number on screen is from these live runs."),
    ("card_pipeline.png",
     "The entire stack is AssemblyAI. The Dictation API for live "
     "transcription, streaming the upload while you speak. The LLM Gateway "
     "for faithful interpretation. And the brand new streaming text to "
     "speech WebSocket for the voice — with per speaker custom vocabulary "
     "through keyterms."),
    ("card_protocol.png",
     "That TTS API shipped with zero public documentation. So we reverse "
     "engineered it, live: the full message protocol, persistent sessions, "
     "per utterance voice and language overrides, and word level timing "
     "metadata. The complete protocol spec is in the repository."),
    ("card_verified.png",
     "Everything you just saw is verified, not claimed. Six end to end smoke "
     "tests against the real APIs. Ten unit tests. And our probe findings — "
     "sixteen API feedback and security observations — are being submitted "
     "separately."),
    ("card_closing.png",
     "Babel. Two people, two languages, one conversation. Open source, one "
     "hundred percent AssemblyAI. Thank you."),
]


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise SystemExit(f"FAILED: {' '.join(cmd[:4])}...\n{r.stderr[-1200:]}")
    return r


def duration_of(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path])
    return float(r.stdout.strip())


def main():
    build_cards()
    print("cards built")
    clips = []
    for i, (image, narration) in enumerate(SCENES):
        img_path = os.path.join(CARDS, image) if image.startswith("card_") \
            else os.path.join(IMG, image)
        mp3 = os.path.join(OUT, f"narr_{i}.mp3")
        run([os.path.join(ROOT, ".venv", "bin", "edge-tts"),
             "--voice", VOICE, "--text", narration, "--write-media", mp3])
        dur = duration_of(mp3)
        clip = os.path.join(OUT, f"clip_{i}.mp4")
        run(["ffmpeg", "-y", "-loop", "1", "-i", img_path, "-i", mp3,
             "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,"
                    "pad=1280:720:(ow-iw)/2:(oh-ih)/2",
             "-af", "aformat=sample_rates=44100:channel_layouts=stereo,apad",
             "-t", f"{dur + 0.4:.2f}",
             "-c:v", "libx264", "-tune", "stillimage", "-crf", "28",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", clip])
        clips.append(clip)
        print(f"scene {i}: {dur + 0.4:.1f}s  ({image})")
    listing = os.path.join(OUT, "clips.txt")
    with open(listing, "w") as f:
        for c in clips:
            f.write(f"file '{c}'\n")
    final = os.path.join(OUT, "babel-demo.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listing,
         "-c", "copy", final])
    total = duration_of(final)
    size = os.path.getsize(final) / 1024 / 1024
    print(f"\nDONE: {final}")
    print(f"duration: {total:.1f}s   size: {size:.1f} MB")


if __name__ == "__main__":
    main()
