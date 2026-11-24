"""Transcribe audio/video files with word timestamps (mlx-whisper, large-v3-turbo).

Why: every cut, caption and text hit in these reels is timed to spoken words, and the
reference reels are transcribed the same way so their pacing can be compared to our takes.
Source files are only read; results land in work/<label>.json and work/<label>.txt.

Example:
    .venv/bin/python transcribe.py mic "/path/to/Mic Recordings/.../TX01_MIC010_*.wav"
    .venv/bin/python transcribe.py ref ../../../References/2026-11-21/*/*.mp4
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FFMPEG = "/opt/homebrew/bin/ffmpeg"
MODEL = "mlx-community/whisper-large-v3-turbo"


def transcribe(prefix: str, source: Path) -> None:
    """Extract 16 kHz mono audio from one source and write its transcript.

    The file name stem is sanitised into the label so outputs never escape work/.
    """
    import mlx_whisper

    label = prefix + "_" + "".join(c if c.isalnum() or c in "-_" else "_" for c in source.stem)
    out_json = ROOT / "work" / f"{label}.json"
    if out_json.exists():  # resumable: skip finished files
        return
    wav = ROOT / "work" / f"{label}.16k.wav"
    # List-form argv (no shell) so odd file names cannot inject commands.
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(source), "-vn", "-ac", "1",
                    "-ar", "16000", str(wav)], check=True)
    result = mlx_whisper.transcribe(
        str(wav), path_or_hf_repo=MODEL, word_timestamps=True,
        initial_prompt="A verbatim spoken transcript, including um, uh, and repeated words.",
        verbose=False)
    out_json.write_text(json.dumps(result, indent=1))
    lines = [f"[{s['start']:7.2f}-{s['end']:7.2f}] {s['text'].strip()}" for s in result["segments"]]
    (ROOT / "work" / f"{label}.txt").write_text("\n".join(lines) + "\n")
    wav.unlink()  # the 16 kHz copy is only a transcription intermediate
    print(label, "segments", len(result["segments"]), flush=True)


if __name__ == "__main__":
    for arg in sys.argv[2:]:
        transcribe(sys.argv[1], Path(arg))
