"""Prepare the video's music from a licensed track:  video/sound/.venv/Scripts/python video/sound/prepare.py

Music: "Ethereal" by Amarent, from the album "Free Atmospheric Music", licensed under
Creative Commons Attribution 4.0 International (CC BY 4.0).
Source: https://freemusicarchive.org/music/amarent/free-atmospheric-music/ethereal-2

Download the MP3 from that page into video/sound/source/amarent-ethereal.mp3 (it is not
committed). This script checks it is the exact file that was reviewed (SHA-256), decodes it,
and makes these changes, which the credit in the video and the README declare:
- uses the first 1:41.3 of the track (the length of the video);
- fades it out over the last 4 seconds;
- sets its level to -19 LUFS, a background level, with peaks at or below -1 dBFS.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

SR = 48000
ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(__file__).parent / "source" / "amarent-ethereal.mp3"
SHA256 = "d2142b4b48473b3a9f63c84607e1f6fac76f696cf02c129fa2a23ce859553af3"
TOTAL_FRAMES = 3040  # src/Video.tsx
FPS = 30
LENGTH = TOTAL_FRAMES / FPS
START = 0.0  # the piece's own opening
FADE_OUT = 4.0
TARGET_LUFS = -19.0
CEILING_DB = -1.0


def lufs(x: np.ndarray) -> float:
    """BS.1770-style integrated loudness (K-weighting in the frequency domain, gated)."""
    freqs = np.fft.rfftfreq(x.shape[1], 1 / SR)
    shelf = 1 + (10 ** (4 / 20) - 1) / (1 + (1500 / np.maximum(freqs, 1)) ** 2)
    hp = 1 / np.sqrt(1 + (38 / np.maximum(freqs, 1e-3)) ** 4)
    y = np.array([np.fft.irfft(np.fft.rfft(ch) * shelf * hp, x.shape[1]) for ch in x])
    block, hop = int(0.4 * SR), int(0.1 * SR)
    ms = np.array([np.sum(np.mean(y[:, i:i + block] ** 2, axis=1)) for i in range(0, y.shape[1] - block, hop)])
    gated = ms[-0.691 + 10 * np.log10(np.maximum(ms, 1e-12)) > -70]
    rel = -0.691 + 10 * np.log10(np.mean(gated)) - 10
    final = gated[-0.691 + 10 * np.log10(gated) > rel]
    return float(-0.691 + 10 * np.log10(np.mean(final)))


def decode(path: Path) -> np.ndarray:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "decoded.wav"
        subprocess.run(["npx", "remotion", "ffmpeg", "-loglevel", "error", "-y", "-i", str(path),
                        "-ac", "2", "-ar", str(SR), "-c:a", "pcm_s16le", str(wav)],
                       check=True, cwd=ROOT, shell=sys.platform == "win32")
        with wave.open(str(wav)) as w:
            raw = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float) / 32768
            return raw.reshape(-1, 2).T


def main() -> int:
    if not SOURCE.exists():
        print(f"missing {SOURCE}: download it from the page named in this file's docstring")
        return 1
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if digest != SHA256:
        print(f"{SOURCE.name} is not the reviewed file (sha256 {digest})")
        return 1
    x = decode(SOURCE)
    a, n = int(START * SR), int(LENGTH * SR)
    x = x[:, a:a + n].copy()
    f = int(FADE_OUT * SR)
    x[:, -f:] *= np.cos(np.linspace(0, np.pi / 2, f)) ** 2  # smooth, ends in silence
    x *= 10 ** ((TARGET_LUFS - lufs(x)) / 20)
    peak = np.max(np.abs(x))
    ceiling = 10 ** (CEILING_DB / 20)
    if peak > ceiling:  # keep the level honest rather than squash it: lower the whole track
        x *= ceiling / peak
    out = ROOT / "public" / "score.wav"
    out.parent.mkdir(exist_ok=True)
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2").T.copy()
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"wrote {out}: {n / SR:.3f}s from {START:.1f}s, {lufs(x):.1f} LUFS, "
          f"peak {20 * np.log10(np.max(np.abs(x))):.1f} dBFS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
