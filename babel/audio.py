"""PCM/WAV helpers. Audio flows through Babel as raw S16LE mono 16 kHz PCM."""

import struct


def wav_header(sample_rate: int, channels: int, num_frames: int) -> bytes:
    """Build a 16-bit PCM WAV header for `num_frames` frames (one frame = one sample per channel)."""
    bits = 16
    block_align = channels * bits // 8
    data_size = num_frames * block_align
    return (
        b"RIFF"
        + struct.pack("<I", 36 + data_size)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, sample_rate,
                      sample_rate * block_align, block_align, bits)
        + b"data"
        + struct.pack("<I", data_size)
    )


def pcm16_to_wav(pcm: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
    """Wrap raw S16LE PCM bytes in a WAV container."""
    frames = len(pcm) // (2 * channels)
    return wav_header(sample_rate, channels, frames) + pcm


def float32_to_pcm16(samples) -> bytes:
    """Convert an iterable of float samples in [-1, 1] to packed S16LE bytes."""
    out = bytearray(len(samples) * 2)
    for i, s in enumerate(samples):
        v = int(max(-1.0, min(1.0, s)) * 32767.0)
        out[2 * i] = v & 0xFF
        out[2 * i + 1] = (v >> 8) & 0xFF
    return bytes(out)


def pcm16_to_float32(pcm: bytes):
    """Convert packed S16LE bytes to a list of float samples in [-1, 1]."""
    n = len(pcm) // 2
    words = struct.unpack("<%dh" % n, pcm[: n * 2])
    return [w / 32768.0 for w in words]


# Dictation API supported language codes (docs/dictation/language-selection).
DICTATION_LANGUAGES = [
    ("en", "English"), ("es", "Spanish"), ("de", "German"), ("fr", "French"),
    ("it", "Italian"), ("pt", "Portuguese"), ("tr", "Turkish"), ("nl", "Dutch"),
    ("sv", "Swedish"), ("no", "Norwegian"), ("da", "Danish"), ("fi", "Finnish"),
    ("hi", "Hindi"), ("vi", "Vietnamese"), ("he", "Hebrew"), ("ur", "Urdu"),
    ("ko", "Korean"), ("ca", "Catalan"), ("gl", "Galician"), ("ru", "Russian"),
    ("ro", "Romanian"), ("et", "Estonian"), ("fa", "Persian"), ("yue", "Cantonese"),
    ("af", "Afrikaans"), ("mr", "Marathi"), ("zu", "Zulu"), ("xh", "Xhosa"),
    ("nn", "Nynorsk"), ("ar", "Arabic"), ("ja", "Japanese"), ("zh", "Mandarin"),
]
