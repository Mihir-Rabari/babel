#!/usr/bin/env python3
"""Generate planted-truth bilingual test fixtures with edge-tts + ffmpeg.

Each clip ships with expected truths (verbatim gist, cleaned gist, keyterm
spellings) so tests assert what was planted — and nothing else (honesty layer).
"""
import asyncio
import json
import os
import subprocess

import edge_tts

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "..", "fixtures")
os.makedirs(FIXTURES, exist_ok=True)

VOICES = {
    "en": "en-US-AndrewMultilingualNeural",
    "es": "es-ES-AlvaroNeural",
    "hi": "hi-IN-MadhurNeural",
}

CLIPS = [
    {
        "name": "en_fillers",
        "voice": "en",
        "text": ("So, umm, I was thinking, like, maybe we could, you know, push the "
                 "release to Friday? Honestly, I think that is, like, the safest option."),
        "planted": {
            "verbatim_markers": ["um", "you know"],
            "clean_absent_markers": ["um", " you know,", "like, maybe"],
            "clean_gist": ["release", "Friday"],
        },
    },
    {
        "name": "en_keyterms",
        "voice": "en",
        "text": ("Please make sure the Zylkon Nimbus server is restarted before "
                 "you deploy Praxel version two."),
        "keyterms": ["Zylkon Nimbus", "Praxel"],
        "planted": {
            "verbatim_markers": ["Zylkon Nimbus"],
        },
    },
    {
        "name": "es_greeting",
        "voice": "es",
        "text": "Hola, ¿podemos empezar la reunión ahora mismo?",
        "planted": {
            "verbatim_markers": ["reunión"],
            "translation_en_gist": ["meeting", "start"],
        },
    },
    {
        "name": "hi_intro",
        "voice": "hi",
        "text": "नमस्ते, क्या मैं आपसे प्रोजेक्ट की समय सीमा के बारे में बात कर सकता हूँ?",
        "planted": {
            "verbatim_markers": ["समय"],
            "translation_en_gist": ["project", "timeline"],
        },
    },
    {
        "name": "conv_a_en",
        "voice": "en",
        "text": ("Hey! Before we ship, can we go through the migration plan together? "
                 "I want to make sure the database switch happens on Thursday."),
        "planted": {"verbatim_markers": ["migration"]},
    },
    {
        "name": "conv_b_es",
        "voice": "es",
        "text": "¡Claro que sí! Pero primero, ¿podemos revisar el presupuesto del proyecto?",
        "planted": {"verbatim_markers": ["presupuesto"]},
    },
]


async def synth(clip: dict) -> None:
    mp3_path = os.path.join(FIXTURES, clip["name"] + ".mp3")
    wav_path = os.path.join(FIXTURES, clip["name"] + ".wav")
    communicate = edge_tts.Communicate(clip["text"], VOICES[clip["voice"]])
    await communicate.save(mp3_path)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3_path,
                    "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav_path],
                   check=True)
    os.remove(mp3_path)
    print(f"  {clip['name']}.wav: {os.path.getsize(wav_path)} bytes")


async def main() -> None:
    print("synthesizing fixtures with edge-tts ...")
    for clip in CLIPS:
        await synth(clip)
    manifest_path = os.path.join(FIXTURES, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump({"clips": CLIPS}, f, indent=2, ensure_ascii=False)
    print(f"manifest: {manifest_path}")
    # bundle the clips for the mic-free demo-replay mode (committed to the repo)
    import shutil
    samples_dir = os.path.join(HERE, "..", "static", "samples")
    os.makedirs(samples_dir, exist_ok=True)
    for clip in CLIPS:
        shutil.copy(os.path.join(FIXTURES, clip["name"] + ".wav"),
                    os.path.join(samples_dir, clip["name"] + ".wav"))
    print(f"bundled samples -> {samples_dir}")


if __name__ == "__main__":
    asyncio.run(main())
