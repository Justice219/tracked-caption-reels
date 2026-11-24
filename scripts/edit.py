"""Build tracked-caption reels from plan.py: lav sound, synced picture, B-roll, kinetic type and cards.

Style copies the three reference reels in References/2026-11-23 (cowboy captions, the realtor edit, the car
detailer): every spoken line is a stack of 2-4 words in mixed sizes, fonts and colours that builds word by word
and rides on the speaker (pose tracking). Key words go large BEHIND the head (person matte); the rest sits on
the chest. Numbers count up. No boxes or panels anywhere (owner's feedback), steady framing, whip-zoom into B-roll.

Flow per reel
    voice ranges (mic seconds) -> tighten() drops pauses -> Timeline maps mic seconds to output seconds
    picture(): each range decoded from its synced clip, graded, punched in; B-roll replaces the picture
               where planned; word clusters ride on the tracked speaker; plain-type cards on top
    sound():   joined lav voice (optionally + camera sound), cleaned and levelled, SFX, quiet music bed
    -> ../finished videos/<file>.mp4  (1080x1920, 24 fps, H.264 + AAC)

Usage
    .venv/bin/python edit.py trencher            build one reel
    .venv/bin/python edit.py all                 build every reel in plan.REELS
    .venv/bin/python edit.py trencher --draft    half-rate preview without the person matte (fast layout check)
"""
import json
import math
import subprocess
import sys
import wave
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work"
SOURCE = ROOT.parent / "Source"
OUT = ROOT.parent / "finished videos"
FFMPEG = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
FONTS = Path.home() / "Library" / "Fonts"
W, H, FPS, RATE = 1080, 1920, 24, 48000
CAPTION_Y = 1235                     # word captions sit on the chest, as in the references
SFX_BOOST = 1.4                      # owner asked for effects ~3 dB louder (2026-11-12)
MAX_SFX_USES = 3                     # owner: spread effects over the pack, never one sound over and over
# daylight job-site footage: gentle S-curve, no saturation boost (2026-10-18 note: avoid neon greens / machines)
# face crops: on each jump cut the picture is cropped until the head is about this many px wide (None = full frame)
FACE_LEVELS = [None, 205, None, 165]
MUSIC_LEVEL = 0.011                  # bed sits ~25 dB under the voice (owner: the first pass was "way too loud")
GRADE = "curves=all='0/0 0.25/0.238 0.75/0.762 1/1'"       # barely-there contrast; owner found stronger grades "too intense"
WHITE, INK = (255, 255, 255), (10, 14, 22)

# Per-shoot facts live in work/project.json so this file never needs editing for a new shoot:
#   "aroll": {"mic017": [["P1244593", 3.949], ...]}   talking clip(s) per lav recording and the mic second at which
#                                                      each clip's first frame happens (copy from sync.py's output;
#                                                      list only the talking clips, B-roll matches there are noise)
#   "turn":  {"P1244646": 1, "P1244627": "land"}      how to stand a clip upright: ffmpeg transpose 1 or 2
#                                                      (default 2), or "land" for a horizontal clip (centre-cropped)
#   "song":  "music/track.wav"                        optional, under Source/: the track for a lip-sync video
_PROJECT = json.loads((WORK / "project.json").read_text()) if (WORK / "project.json").exists() else {}
AROLL = {mic: [tuple(item) for item in clips] for mic, clips in _PROJECT.get("aroll", {}).items()}
TURN = _PROJECT.get("turn", {})
#   "sfx_dir":   folder of sound effects (.wav / .mp3); Picker.POOLS names the files it draws from
#   "music_dir": folder of music beds (.m4a) for a reel's `music` key
#                (default: the 23 effects bundled with the skill in its sfx/ folder)
SFX_DIR = Path(_PROJECT.get("sfx_dir", str(Path.home() / ".claude/skills/tracked-caption-reels/sfx"))).expanduser()
MUSIC_DIR = Path(_PROJECT.get("music_dir", str(ROOT.parents[2] / "Music" / "NCS"))).expanduser()
CLIP_LEN = {k: v["duration"] for k, v in json.loads((WORK / "sync.json").read_text()).items()} if (WORK / "sync.json").exists() else {}


# ---------------------------------------------------------------- words and plan helpers

def norm(text: str) -> str:
    """Lower-case letters and digits only, so "Solutions." matches "solutions"."""
    return "".join(c for c in text.lower() if c.isalnum())


@lru_cache(maxsize=None)
def mic_words(mic: str) -> tuple:
    """Word timestamps of one recording ("mic017", or "song"), with re-transcribed windows (retx.py) patched in."""
    if mic == "song":
        data = json.loads((WORK / "song.json").read_text())
    else:
        data = json.loads(next(WORK.glob(f"mic_*MIC{mic[3:]}_*.json")).read_text())
    words = [dict(start=w["start"], end=w["end"], word=w["word"].strip()) for s in data["segments"] for w in s.get("words", [])]
    for patch in sorted(WORK.glob(f"retx_{mic[3:]}_*.json")):
        a, b = (float(x) for x in patch.stem.split("_")[2:4])
        fixed = [dict(start=w["start"], end=w["end"], word=w["word"].strip()) for w in json.loads(patch.read_text())]
        words = [w for w in words if not a <= w["start"] < b] + fixed
    return tuple(sorted(words, key=lambda w: w["start"]))


def at(mic: str, phrase: str, after: float = 0.0, end: bool = False) -> float:
    """Second at which a spoken phrase starts (or ends) in a recording, searching from `after`.

    Example: at("mic020", "only 8,000 dollars", after=80) -> 82.31
    """
    words, tokens = mic_words(mic), [norm(x) for x in phrase.split()]
    for i, word in enumerate(words):
        if word["start"] < after - 0.8:               # `after` is a rough pointer: allow it to be a little late
            continue
        if all(i + k < len(words) and norm(words[i + k]["word"]) == tokens[k] for k in range(len(tokens))):
            return words[i + len(tokens) - 1]["end"] if end else word["start"]
    raise KeyError(f"{mic}: '{phrase}' not found after {after}")


def R(mic: str, first: str, last: str, after: float = 0.0, lead: float = 0.07, tail: float = 0.16) -> tuple:
    """A voice range from the start of one phrase to the end of another: (mic, start, end)."""
    a = at(mic, first, after)
    return mic, round(a - lead, 3), round(at(mic, last, a, end=True) + tail, 3)


# ---------------------------------------------------------------- timeline

def load_audio(path: Path, start: float | None = None, length: float | None = None, channels: int = 1) -> np.ndarray:
    """Decode audio to float32 at 48 kHz (mono vector, or frames x 2 for stereo)."""
    command = [FFMPEG, "-v", "error"]
    if start is not None:
        command += ["-ss", f"{max(start, 0):.3f}", "-t", f"{length:.3f}"]
    command += ["-i", str(path), "-vn", "-ac", str(channels), "-ar", str(RATE), "-f", "f32le", "-"]
    audio = np.frombuffer(subprocess.run(command, capture_output=True, check=True).stdout, np.float32).copy()
    return audio.reshape(-1, 2) if channels == 2 else audio


def mic_file(mic: str) -> Path:
    """Path of a lav recording ("mic017") or of the song ("song")."""
    if mic == "song":
        return SOURCE / _PROJECT["song"]
    return next((SOURCE / "mic").glob(f"*MIC{mic[3:]}_*.wav"))


def tighten(ranges: list, pause: float, edges: bool = True) -> list:
    """Split each (mic, start, end) range at silences longer than `pause` s and drop them (0.09 s kept each side).

    edges=True also trims silence before the first and after the last word of a range. Switch it off (reel key
    `trim_edges`) when a quiet second speaker is on the recording: his soft word endings read as silence.
    """
    result = []
    for mic, a, b in ranges:
        audio = load_audio(mic_file(mic), a, b - a)[::3]                     # 16 kHz is plenty for a level curve
        blocks = audio[:len(audio) // 160 * 160].reshape(-1, 160)
        level = 20 * np.log10(np.sqrt((blocks ** 2).mean(axis=1)) + 1e-7)
        quiet = level < np.percentile(level, 92) - 15
        cursor, start, stop = a, None, b
        for i, flag in enumerate(np.append(quiet, False)):
            if flag and start is None:
                start = i
            elif not flag and start is not None:
                if edges and start == 0 and i / 100 > 0.10:                   # silence before the first word of the range
                    cursor = a + i / 100 - 0.07
                elif edges and i >= len(quiet) and (i - start) / 100 > 0.14:  # silence after its last word
                    stop = a + start / 100 + 0.11
                elif (i - start) / 100 >= pause and 0 < start and i < len(quiet):
                    result.append((mic, cursor, a + start / 100 + 0.09))
                    cursor = a + i / 100 - 0.09
                start = None
        result.append((mic, cursor, stop))
    return [(m, x, y) for m, x, y in result if y - x > 0.15]


FILLERS = {"um", "uh", "umm", "uhh", "er", "erm"}


def drop_fillers(ranges: list) -> list:
    """Cut "um" / "uh" out of the voice ranges using the word timestamps."""
    result = []
    for mic, a, b in ranges:
        cursor = a
        for word in mic_words(mic):
            if norm(word["word"]) in FILLERS and a < word["start"] and word["end"] < b and word["end"] - word["start"] < 1.2:
                result.append((mic, cursor, word["start"] - 0.03))
                cursor = word["end"] + 0.03
        result.append((mic, cursor, b))
    return [(m, x, y) for m, x, y in result if y - x > 0.15]


class Timeline:
    """Maps a second in a recording to the reel's output second through the reel's voice ranges."""

    def __init__(self, ranges: list):
        self.ranges = ranges
        self.starts = np.cumsum([0.0] + [b - a for _, a, b in ranges])
        self.duration = float(self.starts[-1])

    def out(self, mic: str, second: float) -> float:
        """Output second for a recording second; a second inside a removed pause maps to the next kept range."""
        for (name, a, b), start in zip(self.ranges, self.starts):
            if name == mic and a - 0.01 <= second <= b + 0.01:
                return float(start + min(max(second, a), b) - a)
        later = [(a, float(start)) for (name, a, b), start in zip(self.ranges, self.starts) if name == mic and second < a]
        if later:
            return min(later)[1]
        raise ValueError(f"{mic} {second} is outside the reel")


# ---------------------------------------------------------------- sprites

@lru_cache(maxsize=64)
def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Load an installed font by file stem ("Halenoir-Black", "Heavitas", "Aston Script")."""
    path = next(p for p in FONTS.iterdir() if p.stem == name)
    return ImageFont.truetype(str(path), size)


@lru_cache(maxsize=4096)
def text_sprite(text: str, face: str, size: int, fill: tuple, glow: tuple | None = None, shadow: int = 10, shadow_alpha: int = 170) -> np.ndarray:
    """RGBA text, tightly cropped: solid letters over a soft dark shadow, plus an optional coloured glow behind them."""
    f = font(face, size)
    left, top, right, bottom = f.getbbox(text)
    pad = shadow * 3 + 8
    size_px = (right - left + 2 * pad, bottom - top + 2 * pad)
    dark = Image.new("L", size_px, 0)
    ImageDraw.Draw(dark).text((pad - left, pad - top + shadow // 3), text, font=f, fill=shadow_alpha, stroke_width=2, stroke_fill=shadow_alpha)
    base = Image.new("RGBA", size_px, (0, 0, 0, 0))
    base.putalpha(dark.filter(ImageFilter.GaussianBlur(shadow)))
    if glow:
        halo = Image.new("L", size_px, 0)
        ImageDraw.Draw(halo).text((pad - left, pad - top), text, font=f, fill=200, stroke_width=3, stroke_fill=200)
        tint = Image.new("RGBA", size_px, (*glow, 0))
        tint.putalpha(halo.filter(ImageFilter.GaussianBlur(shadow * 1.3)).point(lambda v: int(v * 0.75)))
        base.alpha_composite(tint)
    ImageDraw.Draw(base).text((pad - left, pad - top), text, font=f, fill=(*fill, 255))
    return np.asarray(base).copy()


def fit_size(text: str, face: str, width: int, max_size: int) -> int:
    """Largest font size (up to max_size) at which the text is no wider than `width` px."""
    size = max_size
    while size > 40 and font(face, size).getlength(text) > width:
        size -= 4
    return size


def blit(frame: np.ndarray, sprite: np.ndarray, cx: float, cy: float, opacity: float = 1.0, scale: float = 1.0) -> None:
    """Alpha-composite an RGBA sprite centred on (cx, cy), optionally scaled."""
    if opacity <= 0.003:
        return
    if abs(scale - 1.0) > 0.004:
        sprite = cv2.resize(sprite, (max(int(sprite.shape[1] * scale), 1), max(int(sprite.shape[0] * scale), 1)),
                            interpolation=cv2.INTER_LINEAR if scale > 1 else cv2.INTER_AREA)
    h, w = sprite.shape[:2]
    x, y = int(round(cx - w / 2)), int(round(cy - h / 2))
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x1 <= x0 or y1 <= y0:
        return
    part = sprite[y0 - y:y1 - y, x0 - x:x1 - x]
    alpha = (part[..., 3:4].astype(np.uint16) * int(min(opacity, 1.0) * 256)) >> 8
    region = frame[y0:y1, x0:x1].astype(np.uint16)
    frame[y0:y1, x0:x1] = ((region * (255 - alpha) + part[..., :3].astype(np.uint16) * alpha) // 255).astype(np.uint8)


def ease_out(p: float) -> float:
    """Cubic ease-out, 0..1."""
    p = min(max(p, 0.0), 1.0)
    return 1 - (1 - p) ** 3


def back_out(p: float, overshoot: float = 1.9) -> float:
    """Ease-out with a small overshoot ("pop"), 0..1."""
    p = min(max(p, 0.0), 1.0) - 1
    return 1 + (overshoot + 1) * p ** 3 + overshoot * p ** 2


# ---------------------------------------------------------------- tracking the speaker

class Track:
    """Follows the speaker so type can ride on them, as in the reference reels.

    update(frame) -> smoothed head centre, head size and chest point of the people in frame (YOLO11-pose);
    mask(frame)   -> person matte (YOLO11-seg) for words that sit behind the head.
    Positions are eased (EMA) so the type glides with the person instead of jittering.
    """
    pose_model = seg_model = None

    def __init__(self):
        self.head = self.chest = None
        self.size, self.people = 120.0, 1

    def update(self, frame: np.ndarray) -> None:
        if Track.pose_model is None:
            from ultralytics import YOLO
            Track.pose_model = YOLO(str(WORK / "models" / "yolo11m-pose.pt"))
        result = Track.pose_model.predict(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), imgsz=640, conf=0.3, device="mps", verbose=False)[0]
        if result.keypoints is None or len(result.boxes) == 0:
            return
        boxes = result.boxes.xyxy.cpu().numpy()
        points = result.keypoints.data.cpu().numpy()
        areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
        heads, chests, sizes = [], [], []
        for i in np.where(areas > areas.max() * 0.45)[0]:           # the speaker(s); small background people are ignored
            k, box = points[i], boxes[i]
            face = k[:5][k[:5, 2] > 0.4]
            width = box[2] - box[0]
            hx, hy = face[:, :2].mean(axis=0) if len(face) else ((box[0] + box[2]) / 2, box[1] + width * 0.3)
            shoulders = k[5:7]
            if (shoulders[:, 2] > 0.35).all():
                span = float(abs(shoulders[0, 0] - shoulders[1, 0]))
                size = max(span * 0.48, width * 0.2)
                chests.append((shoulders[:, 0].mean(), shoulders[:, 1].mean() + max(span, size * 1.6) * 0.42))
            else:
                size = width * 0.3
                chests.append((hx, hy + size * 2.3))
            heads.append((hx, hy))
            sizes.append(size)
        self.people = len(heads)
        target_head, target_chest = np.mean(heads, axis=0), np.mean(chests, axis=0)
        if self.head is None:
            self.head, self.chest, self.size = target_head, target_chest, float(np.mean(sizes))
        else:
            self.head = self.head + (target_head - self.head) * 0.22
            self.chest = self.chest + (target_chest - self.chest) * 0.22
            self.size += (float(np.mean(sizes)) - self.size) * 0.15

    @staticmethod
    def mask(frame: np.ndarray) -> np.ndarray:
        if Track.seg_model is None:
            from ultralytics import YOLO
            Track.seg_model = YOLO(str(WORK / "models" / "yolo11l-seg.pt"))
        result = Track.seg_model.predict(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), imgsz=960, classes=[0], conf=0.35, retina_masks=True,
                                         device="mps", verbose=False)[0]
        if result.masks is None:
            return np.zeros((H, W), np.float32)
        data = result.masks.data.float().cpu().numpy()
        areas = data.reshape(len(data), -1).sum(axis=1)
        return cv2.GaussianBlur(data[areas > areas.max() * 0.12].max(axis=0), (0, 0), 1.6)


# ---------------------------------------------------------------- word clusters (the captions)

SANS, SERIF, SMALL = "Halenoir-Black", "AppleGaramond-BoldItalic", "Halenoir-Bold"
FUNCTION_WORDS = set("""a an the to of in on at for with and or but so is are was were be been it its it's this that these those we you i
he she they our your my me us them do does did have has had will would can could if as by from just very really when what where which who
there here then than up out all any some also too about into over like i'm we're you're that's there's they're he's she's going gonna
be am got get gets right now well yeah know mean kind sort""".split())
FIXES = {"campy": "canopy", "camping": "canopy", "campyland": "canopy land", "caterpillar": "canopy", "insolutions": "solutions",
         "helodes": "helotes", "sel": "scl", "mossad": "sod", "chalk": "chop", "vending": "bender", "boards": "board", "handy": "hand digging",
         "nikolo": "nicolo"}


def clusters(reel: dict, timeline: Timeline) -> list[dict]:
    """Turn the spoken words into reference-style clusters: 2-4 words stacked in mixed sizes that build with the voice.

    A cluster holding one of the reel's `keys` is a "head" cluster (large, behind the speaker's head, key word in an
    accent colour); every other one is a "chest" cluster (smaller, on the chest). Words keep their own spoken time.
    """
    if reel.get("captions") is False:
        return []
    fixes, keys = dict(FIXES, **reel.get("fixes", {})), reel.get("keys", {})
    words, seen = [], set()
    for mic, a, b in timeline.ranges:
        for word in mic_words(mic):
            if not (word["end"] > a + 0.04 and word["start"] < b - 0.04):
                continue
            raw = word["word"]
            if (mic, word["start"]) in seen:                        # a word straddling a removed pause belongs to one side only
                continue
            seen.add((mic, word["start"]))
            if raw.startswith((",", "-")) and words:                # whisper splits "8" + ",000" and "two" + "-car"
                last = words[-1]
                last["text"] += raw.strip(". ?!")
                last["token"] = norm(last["text"]) if raw.startswith(",") else last["token"] + raw.strip(". ?!,").lower()
                last["key"] = last["token"] in keys
                last["stop"] = raw[-1] in ".?!"
                continue
            token = norm(raw)
            text = fixes.get(token, raw).lower()
            text = "".join(c for c in text if c.isalnum() or c in "'$%-,?! ").strip(" ,-")
            if not text:
                continue
            words.append(dict(t=timeline.out(mic, max(word["start"], a)), end=timeline.out(mic, min(word["end"], b)), text=text.rstrip("?!") if token not in keys else text,
                              token=token, stop=raw.rstrip()[-1:] in ".?!" or token in reel.get("breaks", ()), soft=raw.rstrip()[-1:] == ",", key=token in keys))
    words.sort(key=lambda w: w["t"])
    groups, current = [], []
    for i, word in enumerate(words):
        gap = word["t"] - current[-1]["end"] if current else 0.0
        limit = 5 if any(w["key"] for w in current) else 4
        if current and (gap > 0.45 or len(current) >= limit or current[-1]["stop"] or (current[-1]["soft"] and len(current) >= 2)
                        or (word["key"] and any(w["key"] for w in current))):
            carry = []
            if len(current) >= 3 and current[-1]["token"] in FUNCTION_WORDS and not current[-1]["stop"] and not current[-1]["soft"] and gap <= 0.45:
                carry = [current.pop()]                             # do not strand "to" / "the" at the end of a stack
            groups.append(current)
            current = carry
        current.append(word)
    if current:
        groups.append(current)
    palette = reel["palette"]
    result, turn = [], 0
    for n, group in enumerate(groups):
        head = any(w["key"] for w in group)
        if not head:                                                # chest cluster: its longest content word gets the accent
            content = [w for w in group if w["token"] not in FUNCTION_WORDS and len(w["token"]) >= 4]
            star = max(content, key=lambda w: len(w["token"])) if content and len(group) > 1 else None
        lines = []
        for word in group:
            small = word["token"] in FUNCTION_WORDS and not word["key"]
            if word["key"]:
                text = keys[word["token"]] or word["text"]
                serif = turn % 2 == 1
                color = palette[turn % len(palette)]
                turn += 1
                face = SERIF if serif else SANS
                size = fit_size(text, face, 840, 270 if serif else 232)
                item = dict(word, text=text, face=face, size=size, color=color, glow=color)
            elif small:
                item = dict(word, face=SMALL, size=64 if head else 52, color=WHITE, glow=None)
            elif head:
                item = dict(word, face=SANS, size=fit_size(word["text"], SANS, 760, 112), color=WHITE, glow=None)
            elif word is star:
                item = dict(word, face=SANS, size=fit_size(word["text"], SANS, 700, 120), color=palette[0], glow=palette[0])
            else:
                item = dict(word, face=SANS, size=fit_size(word["text"], SANS, 700, 84), color=WHITE, glow=None)
            if small and lines and lines[-1][0]["face"] == SMALL and len(lines[-1]) < 3:
                lines[-1].append(item)                              # neighbouring little words share a line
            else:
                lines.append([item])
        stop = groups[n + 1][0]["t"] if n + 1 < len(groups) else group[-1]["end"] + 0.5
        width = max(sum(font(w["face"], w["size"]).getlength(w["text"]) for w in line) + 16 * (len(line) - 1) for line in lines)
        result.append(dict(start=group[0]["t"], end=min(stop, group[-1]["end"] + 0.7), lines=lines, head=head, width=width + 90))
    return result


def number_text(text: str, progress: float) -> str:
    """Count a number inside a word up from zero ("$8,000" at 0.5 -> "$4,000"); other text is returned unchanged."""
    digits = "".join(c for c in text if c.isdigit())
    if progress >= 1 or len(digits) < 2 or not text.replace(",", "").replace("$", "").replace("%", "").strip().isdigit():
        return text
    value = f"{int(int(digits) * progress):,}" if "," in text else str(int(int(digits) * progress))
    start = next(i for i, c in enumerate(text) if c.isdigit())
    end = len(text) - next(i for i, c in enumerate(reversed(text)) if c.isdigit())
    return text[:start] + value + text[end:]


def draw_cluster(canvas: np.ndarray, cluster: dict, t: float, cx: float, cy: float, scale: float = 1.0) -> None:
    """Draw a cluster centred on (cx, cy): each word pops in at its spoken moment; the stack leaves together."""
    heights = [max(w["size"] for w in line) * (0.80 if line[0]["face"] == SERIF else 0.88 if line[0]["face"] == SANS else 1.0) * scale
               for line in cluster["lines"]]
    leave = min(max((cluster["end"] - t) / 0.10, 0.0), 1.0)
    y = cy - sum(heights) / 2
    sway = (-34, 40, -18, 26, -30) if cluster["head"] else (0, 0, 0, 0, 0)
    for i, (line, height) in enumerate(zip(cluster["lines"], heights)):
        widths = [font(w["face"], int(w["size"] * scale)).getlength(w["text"]) for w in line]
        x = cx + sway[i % 5] * scale - (sum(widths) + 16 * scale * (len(line) - 1)) / 2
        for word, width in zip(line, widths):
            age = t - word["t"] + 0.04
            if age > 0:
                p = age / 0.15
                text = number_text(word["text"], age / 0.55)
                sprite = text_sprite(text, word["face"], int(word["size"] * scale), word["color"], word["glow"], max(int(word["size"] * scale) // 12, 7))
                blit(canvas, sprite, x + width / 2, y + height / 2, min(p * 2, 1.0) * leave, 0.62 + 0.38 * back_out(p))
            x += width + 16 * scale
        y += height


# ---------------------------------------------------------------- cards (plain type, no boxes)

def draw_card(frame: np.ndarray, card: dict, t: float, accent: tuple) -> None:
    """Extra type that is not speech. Kinds: lower (name), question, stars, icons, cta, stamp, label."""
    kind, age = card["kind"], t - card["start"]
    p_in = ease_out(age / 0.22)
    opacity = p_in * min(max((card["end"] - t) / 0.16, 0.0), 1.0)
    cy = card.get("y", 1500)
    if kind == "lower":                                     # name and role, sliding in from the left
        name = text_sprite(card["name"], SANS, 66, WHITE)
        role = text_sprite(card["role"].lower(), SMALL, 38, accent, accent, 6)
        x = 84 - (1 - p_in) * 120
        blit(frame, name, x + name.shape[1] / 2 - 30, cy, opacity)
        blit(frame, role, x + role.shape[1] / 2 - 22, cy + 62, opacity)
    elif kind == "question":                                # interviewer's question, top of frame
        blit(frame, text_sprite("they asked", SMALL, 40, accent, accent, 6), W / 2, cy - 62 + (1 - p_in) * 30, opacity)
        for i, line in enumerate(card["lines"]):
            blit(frame, text_sprite(line, SANS, 62, WHITE), W / 2, cy + i * 70 + (1 - p_in) * 30, opacity)
    elif kind == "stars":
        for i in range(5):
            if age > i * 0.09:
                blit(frame, star_sprite(), W / 2 + (i - 2) * 130, cy, opacity, max(back_out((age - i * 0.09) / 0.2), 0.05))
    elif kind == "icons":                                   # n crew pictograms lighting up one by one
        n = card["n"]
        for i in range(n):
            lit = age > 0.15 + i * 0.13
            blit(frame, person_sprite(accent if lit else (150, 158, 170)), W / 2 + (i - (n - 1) / 2) * 140, cy, opacity,
                 1.0 + (0.25 * max(0.0, 1 - (age - 0.15 - i * 0.13) / 0.15) if lit else 0.0))
    elif kind == "cta":                                     # website line only (owner removed the "free quote" call-outs)
        blit(frame, text_sprite("canopylandsolutions.com", SANS, 70, WHITE), W / 2, cy + 14 + (1 - p_in) * 40, opacity)
        width = int(860 * ease_out((age - 0.25) / 0.45))
        if width > 4:
            blit(frame, np.full((8, width, 4), (*accent, 255), np.uint8), W / 2 - 430 + width / 2, cy + 70, opacity)
    elif kind == "stamp":                                   # slammed-on tilted word
        p = min(age / 0.12, 1.0)
        blit(frame, stamp_sprite(card["text"], card.get("color", accent)), card.get("x", W / 2), cy, opacity * min(p * 1.5, 1), 2.4 - 1.4 * ease_out(p))
    elif kind == "sticker":                                 # cut-out picture slammed on with a wobble (meme beat)
        sprite = sticker_sprite(card["image"], card.get("width", 640), card.get("stretch", 1.0))
        p = min(age / 0.12, 1.0)
        wobble = 1 + 0.04 * math.sin(age * 34) * max(0.0, 1 - age / 0.7)
        blit(frame, sprite, card.get("x", W / 2) + 14 * math.sin(age * 47) * max(0.0, 1 - age / 0.5), cy, min(p * 1.6, 1) * min(max((card["end"] - t) / 0.1, 0), 1),
             (1.9 - 0.9 * ease_out(p)) * wobble)
    elif kind == "note":                                    # small corner note
        sprite = text_sprite(card["text"], SMALL, 34, WHITE, None, 6)
        blit(frame, sprite, 60 + sprite.shape[1] / 2 - 26, cy, opacity * 0.9)
    elif kind == "label":                                   # title over B-roll or at the top and tail of the music video
        size = fit_size(card["text"], SANS, 900, card.get("size", 150))
        blit(frame, text_sprite(card["text"], SANS, size, card.get("color", WHITE), None, 12), W / 2, cy, opacity, 0.7 + 0.3 * back_out(age / 0.2))
        if card.get("sub"):
            blit(frame, text_sprite(card["sub"], SERIF, 66, accent, accent, 7), W / 2, cy + size * 0.5 + 56, opacity)


@lru_cache(maxsize=8)
def person_sprite(color: tuple, size: int = 120) -> np.ndarray:
    """Simple crew-member pictogram (head + shoulders) with a soft shadow."""
    s = size * 4
    image = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((s * 0.34, s * 0.06, s * 0.66, s * 0.38), fill=(*color, 255))
    draw.rounded_rectangle((s * 0.18, s * 0.44, s * 0.82, s * 1.2), int(s * 0.26), fill=(*color, 255))
    small = image.resize((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (size + 40, size + 40), (0, 0, 0, 0))
    shadow = Image.new("L", out.size, 0)
    shadow.paste(small.getchannel("A"), (20, 26))
    out.putalpha(shadow.filter(ImageFilter.GaussianBlur(9)).point(lambda v: int(v * 0.6)))
    out.alpha_composite(small, (20, 20))
    return np.asarray(out).copy()


@lru_cache(maxsize=2)
def star_sprite(size: int = 120) -> np.ndarray:
    """Five-pointed gold star with a soft shadow."""
    s = size * 4
    points = []
    for i in range(10):
        r = s * (0.47 if i % 2 == 0 else 0.20)
        a = -math.pi / 2 + i * math.pi / 5
        points.append((s / 2 + r * math.cos(a), s / 2 + r * math.sin(a)))
    image = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(image).polygon(points, fill=(255, 205, 40, 255))
    small = image.resize((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (size + 40, size + 40), (0, 0, 0, 0))
    shadow = Image.new("L", out.size, 0)
    shadow.paste(small.getchannel("A"), (20, 26))
    out.putalpha(shadow.filter(ImageFilter.GaussianBlur(9)).point(lambda v: int(v * 0.6)))
    out.alpha_composite(small, (20, 20))
    return np.asarray(out).copy()


@lru_cache(maxsize=8)
def sticker_sprite(path: str, width: int, stretch: float) -> np.ndarray:
    """A transparent PNG scaled to `width` (optionally stretched sideways for a "cursed" look) with a white cut-out edge."""
    image = Image.open(path).convert("RGBA")
    box = image.getchannel("A").getbbox()
    image = image.crop(box)
    image = image.resize((int(width * stretch), int(width * image.height / image.width)), Image.LANCZOS)
    pad = 24
    out = Image.new("RGBA", (image.width + 2 * pad, image.height + 2 * pad), (0, 0, 0, 0))
    edge = Image.new("L", out.size, 0)
    edge.paste(image.getchannel("A"), (pad, pad))
    edge = edge.filter(ImageFilter.MaxFilter(15))                    # sticker outline
    out.paste(Image.new("RGBA", out.size, (255, 255, 255, 255)), (0, 0), edge)
    out.alpha_composite(image, (pad, pad))
    return np.asarray(out).copy()


@lru_cache(maxsize=16)
def stamp_sprite(text: str, color: tuple) -> np.ndarray:
    """Heavy word tilted a few degrees (no border)."""
    sprite = Image.fromarray(text_sprite(text, SANS, 150, color, color, 12))
    return np.asarray(sprite.rotate(8, expand=True, resample=Image.BICUBIC)).copy()


# ---------------------------------------------------------------- picture

@lru_cache(maxsize=None)
def exposure(clip: str) -> str:
    """ffmpeg filters that bring an over-bright clip down to a normal daylight exposure ("" when it is fine).

    Six frames across the clip are measured: the mean brightness is nudged toward ~0.48 with a mild gamma (never below 0.88), and when the
    brightest areas are near clipping the top of the curve is rolled off so skies, concrete and shirts keep detail.
    """
    turn = TURN.get(clip, 2)
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(SOURCE / "video" / f"{clip}.MP4"), "-vf",
                          f"fps=6/{max(CLIP_LEN.get(clip, 6), 1):.2f},scale=96:54", "-frames:v", "6", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    luma = np.frombuffer(raw, np.uint8).astype(np.float32) / 255
    mean, top = float(luma.mean()), float(np.percentile(luma, 97))
    chain = []
    if mean > 0.52:                                         # only clearly over-bright clips, and only part of the way
        chain.append(f"eq=gamma={min(max(math.log(mean) / math.log(0.48), 0.88), 1.0):.3f}")
    if top > 0.93:
        chain.append("curves=all='0/0 0.6/0.6 0.86/0.83 1/0.96'")
    return ",".join(chain)


EXTRA_GRADE = {}        # clip -> extra ffmpeg filters, filled from a reel's `grade` key while that reel is built


def reader(clip: str, start: float, count: int, speed: float = 1.0) -> subprocess.Popen:
    """ffmpeg process that yields `count` upright, graded 1080x1920 RGB frames of a clip from `start` seconds."""
    if clip.startswith("/"):                                # outside material, used as it is (no grade)
        if clip.lower().endswith((".png", ".jpg", ".jpeg")):    # a still: held for the length of the cutaway
            return subprocess.Popen([FFMPEG, "-v", "error", "-loop", "1", "-i", clip, "-frames:v", str(count), "-vf",
                                     f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps={FPS}",
                                     "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
        # a 16:9 design-showcase video: its caption strip (bottom 17 %, carries the client's address) is cropped off
        return subprocess.Popen([FFMPEG, "-v", "error", "-ss", f"{max(start, 0):.3f}", "-i", clip, "-frames:v", str(count), "-vf",
                                 f"crop=iw:ih*0.83:0:0,scale=-2:1920,crop=1080:1920,fps={FPS}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                stdout=subprocess.PIPE)
    turn = TURN.get(clip, 2)
    chain = "scale=-2:1920,crop=1080:1920" if turn == "land" else f"transpose={turn}"
    if speed != 1.0:
        chain += f",setpts=PTS/{speed}"
    return subprocess.Popen([FFMPEG, "-v", "error", "-ss", f"{max(start, 0):.3f}", "-i", str(SOURCE / "video" / f"{clip}.MP4"), "-frames:v", str(count),
                             "-vf", f"{chain},fps={FPS},{(exposure(clip) + ',') if exposure(clip) else ''}{(EXTRA_GRADE[clip] + ',') if clip in EXTRA_GRADE else ''}{GRADE}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)


def crop_centre(scale: float, cx: float, cy: float) -> tuple[float, float]:
    """The nearest point to (cx, cy) a crop of this scale can be centred on without leaving the picture."""
    half_w, half_h = W / 2 / scale, H / 2 / scale
    return min(max(cx, half_w), W - half_w), min(max(cy, half_h), H - half_h)


def zoomed(frame: np.ndarray, scale: float, cx: float, cy: float, angle: float = 0.0) -> np.ndarray:
    """Scale (and slightly rotate) the picture around a point, keeping the frame filled."""
    px, py = crop_centre(scale, cx, cy)
    matrix = cv2.getRotationMatrix2D((px, py), angle, scale)
    matrix[0, 2] += W / 2 - px
    matrix[1, 2] += H / 2 - py
    return cv2.warpAffine(frame, matrix, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def whip(frame: np.ndarray, age: float) -> np.ndarray:
    """Whip-zoom landing for the first ~0.2 s of a B-roll cut: overshoot zoom and sideways blur that settle."""
    p = min(age / 0.2, 1.0)
    if p >= 1.0:
        return frame
    k = (1 - p) ** 2
    frame = zoomed(frame, 1 + 0.20 * k, W / 2, H / 2)
    width = int(60 * k) | 1
    return cv2.blur(frame, (width, 1)) if width > 2 else frame


def resolve(reel: dict, timeline: Timeline) -> dict:
    """Turn the plan into output seconds: shots, B-roll, word clusters and cards."""
    shots = []
    if "shots" in reel:                                     # explicit picture list (music video): (mic, second, clip, clip_in)
        for mic, second, clip, clip_in, *level in reel["shots"]:    # optional 5th value: face-crop level for that shot
            shots.append(dict(start=timeline.out(mic, second), clip=clip, clip_in=clip_in, level=level[0] if level else None, cut=True))
    else:                                                   # picture follows the voice: one shot per kept range
        previous, turn = None, 0
        for (mic, a, b), start in zip(timeline.ranges, timeline.starts):
            clip, offset = max((c for c in AROLL[mic] if c[1] <= a + 0.5), key=lambda c: c[1])
            # jump cuts step through face crops (cowgirl reference): full frame, close on the face, full, medium
            turn = turn + 1 if clip == previous else 0
            shots.append(dict(start=float(start), clip=clip, clip_in=a - offset, level=FACE_LEVELS[turn % len(FACE_LEVELS)], cut=clip != previous))
            previous = clip
    for shot, following in zip(shots, shots[1:] + [None]):
        shot["end"] = following["start"] if following else timeline.duration
    broll = [dict(start=timeline.out(m, s) + shift, end=timeline.out(m, s) + shift + length, clip=clip, clip_in=clip_in, speed=speed)
             for m, s, shift, length, clip, clip_in, speed in reel.get("broll", [])]
    cards = []
    for card in reel.get("cards", []):
        start = timeline.duration - card["dur"] if card.get("at") == "end" else timeline.out(card["mic"], card["at"]) + card.get("shift", 0.0)
        cards.append(dict(card, start=start, end=min(start + card["dur"], timeline.duration + 1)))
    return dict(shots=shots, broll=broll, cards=cards, clusters=clusters(reel, timeline))


def picture(name: str, reel: dict, timeline: Timeline, plan: dict, out_path: Path, draft: bool) -> None:
    """Render the reel's picture to a silent H.264 file (and a contact sheet in work/<name>_sheet.jpg)."""
    accent = reel["palette"][0]
    total = int(round(timeline.duration * FPS))
    step = 2 if draft else 1
    encoder = subprocess.Popen([FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS / step),
                                "-i", "-", "-c:v", "libx264", "-preset", "veryfast" if draft else "medium", "-crf", "24" if draft else "19",
                                "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", str(out_path)],
                               stdin=subprocess.PIPE)
    samples, b_reader, b_active, b_last = [], None, None, None
    track, cam = Track(), np.array([W / 2, H * 0.42])
    for shot in plan["shots"]:
        first, last = int(round(shot["start"] * FPS)), min(int(round(shot["end"] * FPS)), total)
        count = last - first
        if count <= 0:
            continue
        source = reader(shot["clip"], shot["clip_in"], count)
        previous, fresh = None, True
        for k in range(count):
            raw = source.stdout.read(W * H * 3)
            base = np.frombuffer(raw, np.uint8).reshape(H, W, 3) if len(raw) == W * H * 3 else previous
            previous = base
            index = first + k
            if index % step:
                continue
            t, age = index / FPS, k / FPS
            b = next((x for x in plan["broll"] if x["start"] <= t < x["end"]), None)
            if b is not b_active:                           # entering or leaving B-roll: (re)open its reader
                if b_reader:
                    b_reader.kill()
                b_reader = reader(b["clip"], b["clip_in"], int((b["end"] - b["start"]) * FPS) + 2, b["speed"]) if b else None
                b_active, b_last = b, None
            if b:
                if step == 2:
                    b_reader.stdout.read(W * H * 3)
                raw = b_reader.stdout.read(W * H * 3)
                b_last = np.frombuffer(raw, np.uint8).reshape(H, W, 3) if len(raw) == W * H * 3 else b_last
                frame = zoomed(b_last if b_last is not None else base, 1.03 + 0.02 * (t - b["start"]), W / 2, H / 2)
                frame = whip(frame, t - b["start"])
            else:
                if fresh:                                   # every cut starts tracking afresh so nothing glides in
                    track = Track()
                track.update(base)
                seen = track.head is not None
                if fresh:                                   # choose this shot's crop from how big the face is
                    fresh = False
                    level = shot["level"]
                    crop = 1.0 if (level is None or not seen) else min(max(level / track.size, 1.12), 1.6)
                    shot["crop"] = min(crop, 1.1) if (track.people > 1 and crop > 1.0) else crop
                    cam = np.array([track.head[0], track.head[1] + track.size * 1.2]) if seen else np.array([W / 2, H * 0.42])
                elif seen:                                  # the crop follows the face smoothly
                    cam = cam + (np.array([track.head[0], track.head[1] + track.size * 1.2]) - cam) * 0.10
                punch = 0.03 * math.exp(-age / 0.08) if (k < 8 and reel.get("punch", True)) else 0.0
                scale = shot["crop"] * (1 + punch + 0.003 * age)
                centre = crop_centre(scale, *cam) if shot["crop"] > 1.0 else crop_centre(scale, W / 2, H * 0.42)
                frame = zoomed(base, scale, *centre)
                came_back = [x for x in plan["broll"] if 0 <= t - x["end"] < 0.2]
                if came_back:
                    frame = whip(frame, t - came_back[0]["end"])
                elif shot["cut"] and shot["start"] > 0.05 and reel.get("whip_cuts", False):
                    frame = whip(frame, age)
                if seen:                                    # tracked points in the cropped picture's coordinates
                    head = ((track.head[0] - centre[0]) * scale + W / 2, (track.head[1] - centre[1]) * scale + H / 2)
                    chest = ((track.chest[0] - centre[0]) * scale + W / 2, (track.chest[1] - centre[1]) * scale + H / 2)
                    head_size = track.size * scale
            cluster = next((x for x in plan["clusters"] if x["start"] <= t < x["end"]), None)
            if cluster is not None:
                on_person = b is None and track.head is not None
                half = min(cluster["width"] / 2, W / 2 - 4)             # the whole stack stays on screen
                block = sum(max(w["size"] for w in line) * 0.86 for line in cluster["lines"])
                if cluster["head"] and on_person:           # glued behind the head, like the cowboy reference
                    cx = min(max(head[0], half), W - half)
                    base_y = head[1] - head_size * 0.8
                    m = None if draft else Track.mask(frame)
                    if "lift" not in cluster:               # once per stack: raise it until the person hides < 30 % of it
                        cluster["lift"], cluster["front"] = 0.0, False
                        if m is not None:
                            options = []
                            for lift in (0.0, 0.45, 0.8, 1.15):
                                y = min(max(base_y - lift * block, 250 + block / 2), 1150)
                                covered = float(m[int(y - block / 2):int(y + block / 2), int(cx - half):int(cx + half)].mean())
                                options.append((covered, lift))
                            good = [o for o in options if o[0] < 0.30]
                            cluster["lift"] = (good[0] if good else min(options))[1]
                            cluster["front"] = not good and min(options)[0] > 0.45      # no clear spot: keep it readable in front
                    cy = min(max(base_y - cluster["lift"] * block, 250 + block / 2), 1150)
                    canvas = frame.copy()
                    draw_cluster(canvas, cluster, t, cx, cy)
                    frame = canvas if (m is None or cluster["front"]) else (canvas * (1 - m[..., None]) + frame * m[..., None]).astype(np.uint8)
                elif cluster["head"]:
                    draw_cluster(frame, cluster, t, W / 2, 640)
                elif on_person:                             # riding on the chest
                    draw_cluster(frame, cluster, t, min(max(chest[0], half), W - half), min(max(chest[1], 700), 1330))
                else:
                    draw_cluster(frame, cluster, t, W / 2, 1180)
            for card in plan["cards"]:
                if card["start"] <= t < card["end"]:
                    draw_card(frame, card, t, accent)
            if t < 0.12:                                    # 3-frame fade from black
                frame = (frame * (t / 0.12)).astype(np.uint8)
            if timeline.duration - t < reel.get("fade_out", 0.0):
                frame = (frame * max((timeline.duration - t) / reel["fade_out"], 0.0)).astype(np.uint8)
            encoder.stdin.write(frame.tobytes())
            if index % 12 == 0:
                samples.append(cv2.resize(frame, (180, 320), interpolation=cv2.INTER_AREA))
        source.kill()
    encoder.stdin.close()
    encoder.wait()
    columns = 16
    rows = [np.hstack(samples[i:i + columns] + [np.zeros_like(samples[0])] * (columns - len(samples[i:i + columns])))
            for i in range(0, len(samples), columns)]
    cv2.imwrite(str(WORK / f"{name}_sheet.jpg"), cv2.cvtColor(np.vstack(rows), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 82])


# ---------------------------------------------------------------- sound

class Picker:
    """Hands out sound effects from pools: least-used file first, never the same twice running, capped per reel."""
    POOLS = {
        "whoosh": ["Slide Woosh", "Airy slice", "Slice Woosh", "Gone Fast", "Snapshot woosh", "Metal slice", "Peww", "Pewww"],
        "pop": ["Click", "Click 02", "Tick", "Radio Beep", "Gear cycle", "Camera Flash", "Typing"],
        "hit": ["Punch", "Suspense Strike", "Dark gravel hit", "Shocking wave 03", "Sudden suspense ", "Camera charge", "Multiple shuttle"],
        "cash": ["Payment"],
    }
    LEVEL = {"whoosh": 0.13, "pop": 0.10, "hit": 0.19, "cash": 0.2}

    def __init__(self):
        self.uses, self.last = {}, None

    def pick(self, kind: str) -> str | None:
        pool = [s for s in self.POOLS.get(kind, [kind]) if self.uses.get(s, 0) < MAX_SFX_USES and s != self.last]
        if not pool:
            return None
        choice = min(pool, key=lambda s: self.uses.get(s, 0))
        self.uses[choice] = self.uses.get(choice, 0) + 1
        self.last = choice
        return choice


def add(mix: np.ndarray, clip: np.ndarray, second: float) -> None:
    """Add a mono clip into the stereo mix at a second (clipped to the mix length)."""
    start = max(int(second * RATE), 0)
    end = min(start + len(clip), len(mix))
    if end > start:
        mix[start:end] += clip[:end - start, None]


def write_wav(path: Path, audio: np.ndarray) -> None:
    """Write float audio (mono vector or frames x 2) as 16-bit PCM."""
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1 if audio.ndim == 1 else 2)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


def sound(name: str, reel: dict, timeline: Timeline, plan: dict, out_path: Path) -> None:
    """Voice (or the song), effects on every graphic and transition, and a quiet music bed."""
    length = int(round(timeline.duration * RATE))
    if reel.get("song"):                                    # music video: the track itself, no voice processing
        mic, a, b = timeline.ranges[0]
        mix = load_audio(mic_file(mic), a, b - a, channels=2)[:length]
        mix = np.pad(mix, ((0, length - len(mix)), (0, 0))) * 0.80
        ramp = int(0.4 * RATE)
        mix[:ramp] *= np.linspace(0, 1, ramp, dtype=np.float32)[:, None]
        tail = int(reel.get("fade_out", 1.5) * RATE)
        mix[-tail:] *= np.linspace(1, 0, tail, dtype=np.float32)[:, None]
    else:
        fade = int(0.006 * RATE)
        ramp, parts = np.linspace(0, 1, fade, dtype=np.float32), []
        for (mic, a, b), shot in zip(timeline.ranges, plan["shots"]):
            n = int(round((b - a) * RATE))
            chunk = load_audio(mic_file(mic), a, b - a)[:n]
            chunk = np.pad(chunk, (0, n - len(chunk)))
            if reel.get("cam_mix"):                         # people without a lav: blend in the camera's own sound
                cam = load_audio(SOURCE / "video" / f"{shot['clip']}.MP4", shot["clip_in"], b - a)[:n]
                chunk[:len(cam)] += cam * reel["cam_mix"]
            chunk[:fade] *= ramp
            chunk[-fade:] *= ramp[::-1]
            parts.append(chunk)
        raw, clean = WORK / f"{name}_voice_raw.wav", WORK / f"{name}_voice.wav"
        write_wav(raw, np.concatenate(parts))
        subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(raw), "-af",
                        "highpass=f=85,afftdn=nr=8:nf=-45,acompressor=threshold=-20dB:ratio=3:attack=6:release=140:makeup=2,"
                        "loudnorm=I=-15:TP=-1.5:LRA=9", "-ar", str(RATE), str(clean)], check=True)
        voice = load_audio(clean)[:length]
        mix = np.repeat(np.pad(voice, (0, length - len(voice)))[:, None], 2, axis=1)
    cues = [(b["start"] - 0.05, "whoosh") for b in plan["broll"]]
    cues += [(s["start"] - 0.05, "whoosh") for s in plan["shots"][1:] if s["cut"] and reel.get("whip_cuts", False)]
    cues += [(c["start"], "pop") for c in plan["clusters"] if c["head"]]          # one soft tick as each big word lands
    for card in plan["cards"]:
        default = {"stamp": "hit", "cta": "pop", "lower": "whoosh", "stars": "pop", "icons": "hit", "question": "pop", "label": "pop", "note": None, "sticker": "hit"}[card["kind"]]
        if card.get("sfx", default):
            cues.append((card["start"], card.get("sfx", default)))
    cues += [(timeline.out(m, s) + shift, stem) for m, s, shift, stem in reel.get("sfx", [])]
    picker, used = Picker(), []
    gain = reel.get("sfx_gain", 1.0)
    for when, kind in sorted(cues):
        stem = picker.pick(kind)
        if stem is None or when < 0:
            continue
        clip = load_audio(next(p for p in SFX_DIR.iterdir() if p.stem == stem))[:int(1.6 * RATE)]
        tail = min(len(clip), int(0.25 * RATE))
        clip[-tail:] *= np.linspace(1, 0, tail, dtype=np.float32)
        clip = clip / (float(np.abs(clip).max()) or 1.0) * Picker.LEVEL.get(kind, 0.2) * SFX_BOOST * gain
        add(mix, clip, when)
        used.append((round(when, 2), stem))
    if reel.get("music"):                                   # quiet bed, starting where the track gets going
        stem, start = reel["music"]
        track = load_audio(MUSIC_DIR / f"{stem}.m4a", channels=2)
        mono = track.mean(axis=1)
        if start is None:
            per_second = np.sqrt((mono[:len(mono) // RATE * RATE].reshape(-1, RATE) ** 2).mean(axis=1))
            smooth = np.convolve(per_second, np.ones(4) / 4, mode="valid")
            start = float(np.argmax(smooth >= smooth.max() * 0.85))
        bed = track[int(start * RATE):int(start * RATE) + length].copy()
        bed *= reel.get("music_level", MUSIC_LEVEL) / (float(np.sqrt((bed ** 2).mean())) or 1.0)       # ~15 dB under the voice
        ramp_n = int(0.6 * RATE)
        bed[:ramp_n] *= np.linspace(0, 1, ramp_n, dtype=np.float32)[:, None]
        bed[-ramp_n:] *= np.linspace(1, 0, ramp_n, dtype=np.float32)[:, None]
        mix[:len(bed)] += bed
        used.append((round(start, 1), f"music {stem}"))
    (WORK / f"{name}_sfx.json").write_text(json.dumps(used))
    write_wav(out_path, np.tanh(mix) * reel.get("gain", 1.0))


def build(name: str, draft: bool) -> None:
    """Build one reel end to end and print its length."""
    from plan import REELS
    reel = REELS[name]
    EXTRA_GRADE.clear()
    EXTRA_GRADE.update(reel.get("grade", {}))
    ranges = reel["audio"] if reel.get("song") else tighten(drop_fillers(reel["audio"]), reel.get("pause", 0.24), reel.get("trim_edges", True))
    timeline = Timeline(ranges)
    plan = resolve(reel, timeline)
    OUT.mkdir(exist_ok=True)
    silent, mix = WORK / f"{name}_silent.mp4", WORK / f"{name}_mix.wav"
    final = (WORK / f"{name}_draft.mp4") if draft else OUT / f"{reel['file']}.mp4"
    picture(name, reel, timeline, plan, silent, draft)
    sound(name, reel, timeline, plan, mix)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(silent), "-i", str(mix), "-c:v", "copy", "-c:a", "aac", "-b:a", "256k",
                    "-shortest", "-movflags", "+faststart", str(final)], check=True)
    silent.unlink()
    print(f"{name}: {timeline.duration:.1f} s, {len(plan['shots'])} shots, {len(plan['broll'])} b-roll, {len(plan['clusters'])} clusters -> {final.name}", flush=True)


if __name__ == "__main__":
    from plan import REELS
    for reel_name in (list(REELS) if sys.argv[1] == "all" else sys.argv[1].split(",")):
        build(reel_name, "--draft" in sys.argv)
