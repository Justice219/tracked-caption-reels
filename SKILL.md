---
name: tracked-caption-reels
description: Use when editing talking-head or job-site footage into vertical reels, shorts or TikToks with word-by-word captions that follow the speaker, big key words behind the person's head, face-tracked punch-in crops, B-roll cutaways, or a lip-sync music video; when asked for "the cowboy captions style", "tracked captions", "text behind the person", or "the editing style from the November 23 reels"; or when a reel's captions sit in boxes, the framing jumps at cuts, pauses and "um"s are left in, or lip-sync takes are out of sync with the song.
---

# Tracked caption reels

Vertical reels (1080x1920, 24 fps) where **every spoken line is a stack of 2-4 words in mixed sizes, fonts
and colours that builds word by word and rides on the speaker**. Key words go large *behind* the head
(person matte); the rest rides at the waist. Numbers count up. Framing steps through face crops on jump cuts.
No boxes or panels anywhere.

The engine is bundled: `scripts/edit.py` renders from a `plan.py` you write per shoot.
To see the target look, watch the three source reels in `references/inspiration/` and the nine results in
`examples/` before planning.

## Workflow

1. **Set up** `Edited/<shoot>/{Source/video,Source/mic,Project/work/models}`; copy `scripts/*.py` into
   `Project/`; venv with `mlx-whisper ultralytics opencv-python pillow numpy` (Apple Silicon; ffmpeg with
   libwebp). Never modify camera files: copy them off the card first.
2. **Watch everything** before planning: an 8-frame strip per clip, then `transcribe.py` on every mic file
   and every clip. Say what each clip is; do not guess from file names.
3. **Sync** with `sync.py` (camera audio vs lav by cross-correlation). Put the talking clips and their
   offsets in `work/project.json` (see `references/project_example.json`). B-roll "matches" are noise.
4. **Plan** in `plan.py` (start from `scripts/plan_example.py`): voice ranges written as spoken phrases
   (`R(mic, "first words", "last words", after)`), `keys` (words that go big behind the head), `fixes`
   (transcript corrections), `broll`, `cards`, `music`. Use `words.py` / `retx.py` for exact word times.
5. **Render** `edit.py <reel> --draft` (fast, no matte), then `edit.py <reel>`. Look at
   `work/<reel>_sheet.jpg` every time. Run `gaps.py <reel>`: no silence over 0.3 s should remain.
6. **Deliver** to `finished videos/`. Publishing is a separate request.

## Rules the owner set (read `references/style-rules.md` before planning)

| Rule | Detail |
|---|---|
| No boxes | No glass cards, pills, lower-third name plates or "free quote" call-outs. Type only. |
| Text behind the head, but readable | A stack is lifted until the person hides < 30 % of it. |
| Waist-height captions, new palette per video | Ordinary stacks sit at the waist; every reel in a batch gets its own colour scheme. |
| Tracking | Type follows the head/chest smoothly; crops follow the face. Never re-centre abruptly. |
| Tight cuts | Drop "um"/"uh", pauses > 0.24 s, stumbles and unsure takes. Cut a stumbled line entirely. |
| B-roll must show the thing being said | Check each cutaway frame; filler shots get removed. |
| Light grade | Barely-there contrast; pull down only clearly over-bright clips, part of the way. |
| Quiet music | Bed ~25 dB under the voice. |
| Lip-sync | Each take sits on the exact song second it was filmed against; the singer is on screen for their line. |

## Lip-sync music videos

Put the track in `Source/` and name it in `project.json` (`"song"`). `sync.py` writes `work/song_map.json`:
which song second is audible at each clip second. Find every run with a steady offset (score > 17), then in
the plan use `song=True`, `audio=[("song", start, end)]` and explicit `shots=[("song", song_second, clip,
clip_second, face_level)]` with `clip_second = song_second + offset`. Add `breaks` (line-ending words) so a
lyric stack never hangs into the next line. Lines nobody was filmed singing get B-roll, never an idle face.

## Common mistakes

- Planning from a transcript without watching the clip: a "B-roll" shot turned out to be a singing take.
- Reading `words.py` output as "word then time": the time comes *before* each word.
- Trusting pause-cutting on a second, quieter speaker: set `trim_edges=False, pause=0.38` and re-transcribe
  the finished audio to confirm no word endings were clipped.
- Using a lookalike image for a named person: use a sourced picture of the actual person or none.
- Calling a reel done without opening its contact sheet.
