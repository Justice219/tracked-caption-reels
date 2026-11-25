# Style rules (from the owner's feedback, 2026-11-23)

Three reference reels define the look: "cowboy captions" (stacked multi-font, multi-colour words behind the
head, single words on the chest, face-cropped cuts), a realtor edit (one big word behind the head with a small
label, counting numbers) and a car-detailer ad (stacks riding on the chest, glowing key words). The engine
copies them; these rules are the corrections made on the way.

## Type

- **Stacks, not sentences.** 2-4 words per stack (5 if it holds a key word); break at punctuation or a pause
  over 0.45 s; never strand "to"/"the" at the end of a stack. Words pop in at their own spoken moment and the
  stack leaves together.
- **Ordinary stacks ride at the waist**, not the chest (chest height read as "too high up"), about three
  quarters of the way from shoulders to hips.
- **A different colour scheme for every video** in a batch (cool blues, greens, coral and pink, the warm
  yellow set, ...). Reusing one palette made the reels feel the same.
- **Three roles in a stack:** little function words (white, 52-64 px, neighbours share a line), ordinary words
  (white, heavy sans), and one accent word. In a chest stack the accent is the longest content word.
- **Key words** (the plan's `keys`) make a *head* stack: the key word is fitted up to ~230-270 px, alternating
  a heavy sans (Halenoir Black) and a bold italic serif (Apple Garamond Bold Italic), cycling the reel's
  palette (yellow, white, orange, hot pink in the reference palette), with a soft glow in its own colour.
- **Behind the head, never unreadable.** Head stacks are composited under a person matte. The stack is lifted
  in steps until the person covers under 30 % of it; if no position works it is drawn in front. The whole
  stack is clamped on screen.
- **Lower-case** throughout; keep only `?` and `!` on key words. Numbers count up from zero over ~0.5 s
  ("$8,000", "3,500").
- **Nothing else on screen.** The owner removed: rounded/glass boxes, checklists, counters in cards, name
  plates, and "free quote" lines. Allowed extras: a plain website line at the very end, a star row, a row of
  icons, a tilted stamp word, a cut-out sticker for a meme beat, a small corner note.
- Fonts used: Halenoir Black / Bold, Apple Garamond Bold Italic. Never Arial.

## Picture

- **Face crops on jump cuts.** Shots of the same clip step through: full frame, close (head ~205 px wide),
  full, medium (~165 px). The crop follows the face with easing; each cut starts tracking afresh so nothing
  glides in. Two people in frame: crop no tighter than 1.1x.
- **B-roll** enters and leaves with a 0.2 s whip-zoom and a whoosh. Every cutaway must show what is being said
  at that moment. When there is no real footage of something described, a generated "recreated view" can be
  used at the owner's request, marked with a small corner note.
- **3D design renders** or other outside clips can be cutaways (give an absolute path); crop off any caption
  strip that shows a client's address.
- **Grade:** barely-there S-curve. A clip is pulled down only when its mean brightness is clearly high, with a
  gamma no lower than 0.88 and a soft highlight roll-off. "Too intense" was the feedback on anything stronger.

## Sound

- Lav voice, cleaned and levelled to about -15 LUFS. Add the camera's own sound (`cam_mix`) when people without
  a lav speak.
- Cut "um"/"uh", pauses over 0.24 s, and silence at the edges of every range. Comedy skits keep longer pauses
  (`pause=0.6`).
- Music bed about 25 dB under the voice (`MUSIC_LEVEL = 0.011`); the first pass at -15 dB was "way too loud".
- Sound effects from the owner's pack only, spread across the pack, at most three uses of a file per reel:
  a soft tick as each head stack lands, a whoosh on B-roll, a hit on stamps and stickers.

## Publishing notes

- Upload the untouched masters ("max quality"); web copies for a site gallery can be ~2.5 Mbit/s.
- Set a cover frame per reel (a key-word moment with the face visible).
- Two a day reads well: one in the morning, one in the evening.
