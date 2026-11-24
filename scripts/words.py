"""Print the words of a mic transcript between two seconds, each with its start time and level, on few lines.

Why: cut points are chosen from word times, and the level tells the lav wearer (loud) from someone off-camera (quiet).
Example: .venv/bin/python words.py 017 0 20   ->  0.42 But(-31) 0.80 like(-30) ...
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent


def main(mic: str, a: float, b: float) -> None:
    """mic = three-digit recorder number; a, b = seconds in that recording."""
    wav = next((ROOT.parent / "Source" / "mic").glob(f"*MIC{mic}_*.wav"))
    data = json.loads(next((ROOT / "work").glob(f"mic_*MIC{mic}_*.json")).read_text())
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(a), "-t", str(b - a), "-i", str(wav), "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, np.float32)
    out = []
    for seg in data["segments"]:
        for w in seg.get("words", []):
            if a <= w["start"] < b:
                piece = audio[int((w["start"] - a) * 16000):int((w["end"] - a) * 16000) + 1]
                level = 20 * np.log10(np.sqrt((piece ** 2).mean()) + 1e-6) if len(piece) else -99
                out.append(f"{w['start']:.2f} {w['word'].strip()}({level:.0f})")
    print("  ".join(out))


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]), float(sys.argv[3]))
