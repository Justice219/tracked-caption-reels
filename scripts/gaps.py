"""List the silences left in a built reel's voice track (work/<reel>_voice_raw.wav), to check the pause cutting.

Example: .venv/bin/python gaps.py trencher   ->  seconds where the voice is quiet for longer than 0.3 s
"""
import sys
from pathlib import Path

import numpy as np

from edit import load_audio

for name in sys.argv[1:]:
    audio = load_audio(Path(__file__).parent / "work" / f"{name}_voice_raw.wav")[::3]
    blocks = audio[:len(audio) // 160 * 160].reshape(-1, 160)
    level = 20 * np.log10(np.sqrt((blocks ** 2).mean(axis=1)) + 1e-7)
    quiet = np.append(level < np.percentile(level, 92) - 15, False)
    found, start = [], None
    for i, flag in enumerate(quiet):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if (i - start) / 100 > 0.3:
                found.append(f"{start / 100:.1f}s ({(i - start) / 100:.2f})")
            start = None
    print(name, f"{len(audio) / 16000:.1f}s", "gaps > 0.3 s:", found or "none")
