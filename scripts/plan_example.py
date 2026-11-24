"""Example plan (three reels from a real landscaping shoot). Copy to plan.py and rewrite for your footage.

Every time is written as a spoken phrase (at / R look the phrase up in the lav transcript), so the plan reads
like the script. Keys of a reel:
    file      output name in ../finished videos
    palette   colours for key words, used in turn (first one is also the accent for names / CTA)
    audio     voice ranges, in order; "um"/"uh" and pauses longer than `pause` (default 0.24 s) are cut out
    keys      spoken words that become LARGE and sit behind the speaker's head: {word: display text or None}
    fixes     transcript corrections for the captions: {heard: shown}
    broll     B(...) cutaways over the voice
    breaks    words after which a caption stack must end (used for sung lyrics)
    cards     plain-type extras: question, stars, icons, stamp, label, cta (name plates and "free quote" lines removed by the owner)
    music     (NCS track, start second or None = where it kicks in)
"""
from edit import R, at

YELLOW, WHITE, ORANGE, RED, LIME, SKY = (255, 214, 0), (255, 255, 255), (255, 122, 24), (255, 52, 88), (168, 236, 60), (96, 190, 255)
WARM = [YELLOW, WHITE, ORANGE, RED]          # the cowboy-captions palette
FRESH = [LIME, WHITE, YELLOW, ORANGE]
SUN = [ORANGE, WHITE, YELLOW, RED]


def Cd(kind: str, mic: str, phrase: str, dur: float, after: float = 0.0, **extra) -> dict:
    """Card that appears on a spoken phrase and stays `dur` seconds."""
    return dict(kind=kind, mic=mic, at=at(mic, phrase, after), dur=dur, **extra)


def B(mic: str, phrase: str, length: float, clip: str, clip_in: float, after: float = 0.0, shift: float = 0.0, speed: float = 1.0) -> tuple:
    """B-roll cutaway starting on a spoken phrase: `length` seconds of `clip` from `clip_in`."""
    return mic, at(mic, phrase, after), shift, length, clip, clip_in, speed


CTA = dict(kind="cta", at="end", dur=3.0, y=1500)
# A still image used as a cutaway (any absolute path to a .png/.jpg; a 16:9 video path works too).
CRACKED = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "Source" / "generated" / "driveway_before_cracked.png")


def note(mic: str, phrase: str, dur: float, after: float) -> dict:
    """Small corner note, e.g. to mark a recreated "before" picture while it is on screen."""
    return dict(kind="note", mic=mic, at=at(mic, phrase, after), dur=dur, text="before (recreated view)", y=1700)


REELS = {}

# ------------------------------------------------------------------ trencher explainer (Nico, P1244602)
M = "mic020"
REELS["trencher"] = dict(
    file="Why_We_Use_A_Trencher", palette=WARM, music=("Janji-Heroes_Tonight", None),
    audio=[R(M, "Right here is", "great question", 15),
           (M, 25.0, 27.62),                                            # "we use this when we have to dig trenches"
           R(M, "for edgings", "proper depth", 33),
           R(M, "And irrigation", "lines together", 44),
           R(M, "It's much easier", "more efficiently", 56),
           R(M, "it's only 8", "that point", 82),
           R(M, "I would highly", "service company", 98.5)],
    keys={"trencher": None, "why": "why?", "edgings": "edging", "french": None, "irrigation": None, "digging": None,
          "quicker": "faster", "8000": "$8,000", "priceless": None, "recommend": None},
    cards=[CTA],
    broll=[B(M, "concrete footer", 2.3, "P1244604", 3.0, 36.5),
           B(M, "dig a long", 2.4, "P1244598", 0.0, 39.5),
           B(M, "saves a lot", 2.2, "P1244592", 12.8, 57.5),
           B(M, "amount of money", 2.6, "P1244597", 0.5, 84.5)],
)

# ------------------------------------------------------------------ driveway ad (Nico, P1244648)
M = "mic043"
REELS["driveway_ad"] = dict(
    file="Is_Your_Driveway_Sinking_Or_Cracking", palette=SUN, music=("Janji-Heroes_Tonight", 40.0),
    audio=[R(M, "Is your driveway", "apart", 25.5),
           R(M, "Call us at", "for you", 30.9),
           R(M, "Right here, there", "cracking", 35.2),
           R(M, "This driveway was", "six inches", 37.4),
           R(M, "we tore it all", "the right way", 44.8),
           R(M, "Six inches", "of the house", 48.3),
           R(M, "if you have problems", "execute it", 60.3),
           R(M, "Call us", "us", 66.4)],
    keys={"sinking": None, "cracking": None, "apart": None, "mesh": "wire mesh", "tore": None, "six": '6"', "3500": "3,500", "psi": "PSI",
          "rebar": None, "foundation": None, "execute": None, "call": None},
    fixes={"wire": "", "inches": "inches"},
    cards=[note(M, "there was cracking", 2.6, 36.3), CTA],
    broll=[B(M, "there was cracking", 2.6, CRACKED, 0, 36.3),
           B(M, "redid the whole", 2.4, "P1244628", 0.5, 46),
           B(M, "we can come out", 2.6, "P1244626", 14.0, 61.4)],
)

# ------------------------------------------------------------------ "Choosin' Texas" crew lip-sync (music video, P1244601)
S = "song"
REELS["texas"] = dict(
    file="Choosin_Texas_Crew_Music_Video", palette=WARM, song=True, sfx_gain=0.0, fade_out=1.6, punch=False, whip_cuts=True,
    audio=[(S, 12.0, 80.2)],
    # picture: every take sits on the exact song second it was filmed against (measured with the song playing on
    # set, see sync.py); the fifth value crops the shot onto the singers' faces. Offsets: clip = song + N.
    shots=[(S, 12.0, "P1244601", 8.34),               # Nico on the trailer: "...fall in love with Tennessee"   (N = -3.66)
           (S, 23.7, "P1244601", 58.33, 165),         # James by the tree: "I should've known better... Abilene" (N = +34.63)
           (S, 31.0, "P1244601", 99.86),              # Nico + Zay: "I put him right back into her arms..."     (N = +68.86)
           (S, 45.0, "P1244595", 9.0),                # crew laying fabric (nobody was filmed on this line)
           (S, 47.6, "P1244592", 15.2),               # loader working
           (S, 50.2, "P1244601", 176.87),             # Zay: "and judging by the smile..."                      (N = +126.67)
           (S, 59.3, "P1244601", 200.74, 150),        # James + crew by the house: "it doesn't take a crystal ball..." (N = +141.44)
           (S, 75.6, "P1244591", 0.6)],               # the dog
    keys={"tennessee": None, "abilene": None, "arms": None, "spark": None, "texas": None, "stepping": "two-steppin'", "smile": None,
          "nothing": None, "crystal": None, "cowboy": None, "leave": None, "jack": None, "choosing": "choosin'"},
    fixes={"still": "", "drinking": "drinkin'", "round": "'round"},
    # sung lyrics carry no punctuation: these words end a line, so a stack never hangs over into the next line
    breaks={"tennessee", "abilene", "arms", "spark", "tell", "room", "face", "do", "see", "leave", "myself"},
    cards=[dict(kind="label", mic=S, at=12.3, dur=3.6, text="Choosin' Texas", sub="the Canopy Land Solutions crew", y=300, sfx=None),
           dict(kind="label", mic=S, at=76.2, dur=3.8, text="Canopy Land Solutions", sub="canopylandsolutions.com", y=1380, size=100, sfx=None)],
)
