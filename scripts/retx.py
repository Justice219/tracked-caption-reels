"""Re-transcribe one window of a mic recording alone (whisper mis-times words inside long pauses or cross-talk).

Example: .venv/bin/python retx.py 017 8 18    -> word list with times in the recording's own seconds;
         also saved as work/retx_017_8_18.json so plan.py can use the corrected words.
"""
import json
import subprocess
import sys
from pathlib import Path

import mlx_whisper

ROOT = Path(__file__).resolve().parent


def main(mic: str, a: float, b: float) -> None:
    wav = next((ROOT.parent / "Source" / "mic").glob(f"*MIC{mic}_*.wav"))
    tmp = ROOT / "work" / "retx.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(a), "-t", str(b - a), "-i", str(wav), "-ac", "1", "-ar", "16000", str(tmp)], check=True)
    result = mlx_whisper.transcribe(str(tmp), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", word_timestamps=True,
                                    language="en", condition_on_previous_text=False, verbose=False)
    words = [{"start": round(w["start"] + a, 2), "end": round(w["end"] + a, 2), "word": w["word"]}
             for s in result["segments"] for w in s.get("words", [])]
    (ROOT / "work" / f"retx_{mic}_{int(a)}_{int(b)}.json").write_text(json.dumps(words))
    print("  ".join(f"{w['start']:.2f} {w['word'].strip()}" for w in words))


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]), float(sys.argv[3]))
