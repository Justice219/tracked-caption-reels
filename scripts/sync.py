"""Place every camera clip on its lavalier recording, and find where the played-back song sits in each clip.

Why: the reels use the lavalier sound, so each clip needs the mic file and the second in it where the clip starts
(cross-correlation of the camera's own audio with every mic file). For the lip-sync music video the song was played
on set from a phone, so the same correlation, run in short windows against the song file, tells which part of the
song is audible at each moment of a clip.

Example: .venv/bin/python sync.py        -> work/sync.json  {"P1244594": {"mic": "mic017", "offset": 196.9, "score": 31.0}}
                                           work/song_map.json {"P1244601": [[clip_second, song_second, score], ...]}
"""
import json
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "Source"
FFMPEG = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
RATE = 4000


def load(path: Path) -> np.ndarray:
    """Decode audio to mono float at RATE, high-passed by differencing and normalised."""
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    audio = np.diff(np.frombuffer(raw, np.float32), prepend=0.0)
    return audio / (np.abs(audio).std() + 1e-9)


def best_offset(clip: np.ndarray, mic: np.ndarray) -> tuple[float, float]:
    """Return (mic second where the clip starts, peak-to-noise score) from an FFT cross-correlation."""
    size = 1 << int(np.ceil(np.log2(len(clip) + len(mic))))
    corr = np.fft.irfft(np.fft.rfft(mic, size) * np.conj(np.fft.rfft(clip, size)), size)
    corr = np.concatenate([corr[-len(clip):], corr[:len(mic)]])          # lags -len(clip) .. len(mic)
    peak = int(np.argmax(corr))
    score = float(corr[peak] / (np.abs(corr).std() + 1e-9))
    return (peak - len(clip)) / RATE, score


if __name__ == "__main__":
    mics = {f"mic{p.name[8:11]}": load(p) for p in sorted((SOURCE / "mic").glob("*.wav"))}
    project = ROOT / "work" / "project.json"
    song_path = json.loads(project.read_text()).get("song") if project.exists() else None
    song = load(SOURCE / song_path) if song_path else None          # only lip-sync shoots have a song
    result, song_map = {}, {}
    for clip in sorted((SOURCE / "video").glob("*.MP4")):
        audio = load(clip)
        scores = {name: best_offset(audio, mic) for name, mic in mics.items()}
        name = max(scores, key=lambda k: scores[k][1])
        result[clip.stem] = {"mic": name, "offset": round(scores[name][0], 3), "score": round(scores[name][1], 1),
                             "duration": round(len(audio) / RATE, 2)}
        print(clip.stem, result[clip.stem], flush=True)
        hits, window = [], 6 * RATE                      # 6 s windows, 2 s apart, against the whole song
        for start in (range(0, max(len(audio) - window, 1), 2 * RATE) if song is not None else []):
            piece = audio[start:start + window]
            offset, score = best_offset(piece, song)
            if score > 17:               # below ~17 the match is noise; real takes score 20-70
                hits.append([round(start / RATE, 2), round(offset, 3), round(score, 1)])
        if hits:
            song_map[clip.stem] = hits
            print("   song:", hits, flush=True)
    (ROOT / "work" / "sync.json").write_text(json.dumps(result, indent=1))
    (ROOT / "work" / "song_map.json").write_text(json.dumps(song_map, indent=1))
