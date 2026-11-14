"""Check the video's soundtrack: length, level, fade, gaps, balance, and pictures.

    video/sound/.venv/Scripts/python video/sound/analyze.py [score.wav] [out-dir]

Prints PASS/FAIL checks and writes a log-frequency spectrogram and a loudness envelope
(PNG, numpy + zlib only) with the video's chapter boundaries marked.
"""

from __future__ import annotations

import struct
import sys
import wave
import zlib
from pathlib import Path

import numpy as np

SR = 48000
FPS = 30
ROOT = Path(__file__).resolve().parents[1]
DUR = [150, 240, 300, 210, 300, 420, 270, 330, 540, 240, 180]  # src/Video.tsx
FADE = 14
START = [sum(DUR[:i]) - FADE * i for i in range(len(DUR))]
TOTAL = sum(DUR) - FADE * (len(DUR) - 1)
LENGTH = TOTAL / FPS


def load(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        raw = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float) / 32768
        return raw.reshape(-1, w.getnchannels()).T


def lufs(x: np.ndarray) -> float:
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


def rms_db(x: np.ndarray, t0: float, t1: float) -> float:
    seg = x[:, int(t0 * SR):int(t1 * SR)]
    return float(20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9))


def per_octave(x: np.ndarray, f0: float, f1: float) -> float:
    s = np.abs(np.fft.rfft(x.mean(axis=0) * np.hanning(x.shape[1]))) ** 2
    f = np.fft.rfftfreq(x.shape[1], 1 / SR)
    return float(10 * np.log10(s[(f >= f0) & (f < f1)].sum() / np.log2(f1 / f0)))


def png(path: Path, rgb: np.ndarray) -> None:
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[r].astype(np.uint8).tobytes() for r in range(h))
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def pictures(x: np.ndarray, out: Path, marks: bool = True) -> None:
    mono = x.mean(axis=0)
    W, H, win = 1800, 520, 4096
    hop = len(mono) // W
    freqs = np.fft.rfftfreq(win, 1 / SR)
    idx = np.clip(np.searchsorted(freqs, np.geomspace(50, 9000, H)[::-1]), 0, len(freqs) - 1)
    img = np.zeros((H, W))
    for c in range(W):
        seg = mono[c * hop:c * hop + win]
        seg = np.pad(seg, (0, win - len(seg))) if len(seg) < win else seg
        img[:, c] = 20 * np.log10(np.abs(np.fft.rfft(seg * np.hanning(win)))[idx] + 1e-6)
    img = np.clip((img - (img.max() - 80)) / 80, 0, 1)[..., None]
    ground, mid, hi = np.array([10, 15, 21]), np.array([134, 168, 255]), np.array([255, 236, 200])
    rgb = np.where(img < 0.6, ground + (mid - ground) * (img / 0.6), mid + (hi - mid) * ((img - 0.6) / 0.4))
    cols = [int(s / TOTAL * W) for s in START] if marks else []
    for col in cols:
        rgb[:, max(0, col - 1):col + 1] = [232, 170, 77]
    png(out / "spectrogram.png", rgb)
    env = np.array([np.sqrt(np.mean(mono[i:i + hop] ** 2)) for i in range(0, hop * W, hop)])
    db = np.clip((20 * np.log10(env + 1e-6) + 60) / 60, 0, 1)
    E = 260
    canvas = np.zeros((E, W, 3)) + np.array([10, 15, 21])
    for c, v in enumerate(db):
        canvas[E - int(v * (E - 10)):, c] = [134, 168, 255]
    for col in cols:
        canvas[:, max(0, col - 1):col + 1] = [232, 170, 77]
    png(out / "envelope.png", canvas)


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "public" / "score.wav"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "out" / "audio"
    out.mkdir(parents=True, exist_ok=True)
    x = load(path)
    ok = True

    def check(name: str, cond: bool, detail: str) -> None:
        nonlocal ok
        ok &= cond
        print(f"{'PASS' if cond else 'FAIL'}  {name}: {detail}")

    dur = x.shape[1] / SR
    check("length matches the picture", abs(dur - LENGTH) < 0.01, f"{dur:.3f}s for {TOTAL} frames")
    peak = 20 * np.log10(np.max(np.abs(x)))
    check("no clipping", peak <= -0.9, f"peak {peak:.2f} dBFS")
    loud = lufs(x)
    check("background level, not invasive", -21 <= loud <= -17, f"{loud:.1f} LUFS (approx. BS.1770)")
    windows = [rms_db(x, t, t + 1.0) for t in np.arange(1.0, LENGTH - 5.0, 0.5)]
    check("no holes under the picture", min(windows) > -45, f"quietest 1 s window {min(windows):.1f} dBFS")
    tail = rms_db(x, LENGTH - 0.3, LENGTH)
    check("fades out to the end", tail < -50, f"last 0.3 s at {tail:.1f} dBFS")
    bands = [(40, 120), (120, 300), (300, 800), (800, 2000), (2000, 6000)]
    v = [per_octave(x[:, int(5 * SR):int((LENGTH - 5) * SR)], *b) for b in bands]
    low, high = v[0] - v[2], v[4] - v[2]
    check("not boomy or harsh", low < 3 and high > -30, "dB/oct rel. 300-800: " +
          "  ".join(f"{a}-{b}: {vv - v[2]:+.1f}" for (a, b), vv in zip(bands, v)))
    pictures(x, out)
    print(f"wrote {out / 'spectrogram.png'} and {out / 'envelope.png'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
