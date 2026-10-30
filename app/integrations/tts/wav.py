"""Wrap raw 16-bit mono PCM in a WAV header so browsers can play it."""

import struct


def pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
    return header + fmt + b"data" + struct.pack("<I", len(pcm)) + pcm
