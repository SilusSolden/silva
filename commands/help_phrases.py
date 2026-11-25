"""Detect when the user asks what Silva can do — including natural phrasing."""

from __future__ import annotations

import re

HELP_CAPABILITIES_TEXT = (
    "I can help with weather, news, notes, to-dos, math, and lookups."
)

HELP_TRIGGERS: tuple[str, ...] = (
    "what can you do",
    "what do you do",
    "what are you able to do",
    "what are you capable of",
    "what are your capabilities",
    "what can silva do",
    "what does silva do",
    "tell me what you can do",
    "tell me what you do",
    "can you tell me what you can do",
    "can you tell me what you do",
    "how can you help me",
    "how can you help",
    "what help can you give",
    "what help can you provide",
    "list your commands",
    "what commands do you have",
    "what commands can you run",
    "what features do you have",
    "what are you good at",
)

_CAPABILITY_ASK_MARKERS: tuple[str, ...] = (
    "can you",
    "do you",
    "are you able",
    "is there",
    "do you have",
    "is it possible",
    "can silva",
    "does silva",
    "what about",
    "how about",
    "available",
    "an option",
    "one of your",
)

_DETAIL_ASK_MARKERS: tuple[str, ...] = (
    "options",
    "in detail",
    "in details",
    "in depth",
    "details",
    "give me details",
    "give me the details",
    "get me details",
    "details on",
    "details for",
    "details about",
    "details of",
    "what can",
    "what can i do with",
    "what can i do for",
    "what can it do",
    "what can they do",
    "what can the",
    "what can my",
    "what does",
    "what do the",
    "what do they",
    "what do you mean",
    "what happens if",
    "what if i",
    "what if someone",
    "why wont you answer",
    "why are you still not",
    "when i'm cussing at you",
    "when i am cussing at you",
    "work correctly",
    "the way i asked",
    "can you tell me how",
    "correct way to say",
    "if i accidentally",
    "accidentally give",
    "tell me what do you mean",
    "tell me what you mean",
    "mean by",
    "how does",
    "how do they",
    "how do i use",
    "how does that work",
    "how do they work",
    "list the",
    "all the things",
    "everything it can",
    "what all can",
    "available options",
    "tell me more about",
    "tell me in detail",
    "tell me in details",
    "tell me what you",
    "tell me what do you",
    "tell me what does",
    "tell me what can",
    "can you tell me what",
    "could you tell me what",
    "break down",
    "go into detail",
    "explain",
    "describe",
)

_STT_FEATURE_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bmatt\b", re.I), "math"),
    (re.compile(r"\bmat\b", re.I), "math"),
    (re.compile(r"\bmaths\b", re.I), "math"),
    (re.compile(r"\bmaps\b", re.I), "math"),
    (re.compile(r"\blook ups\b"), "lookups"),
    (re.compile(r"\blook up s\b"), "lookups"),
    (re.compile(r"\bto dos\b"), "to dos"),
    (re.compile(r"\b2 dos\b"), "to dos"),
    (re.compile(r"\bwhether\b"), "weather"),
    (re.compile(r"\bforcast\b"), "forecast"),
    (re.compile(r"\bwiki pedia\b"), "wikipedia"),
    (re.compile(r"\b(?:s\s*t\s*t|stt|std|sdt|sct)(?:\s+e)?\s+handlers?\b", re.I), "help handler"),
    (re.compile(r"\b(?:std|sdt|sct|s\s*t\s*t)\s+fillers?\b", re.I), "stt fillers"),
    (re.compile(r"\b(?:std|sdt|sct|s\s*t\s*t)\s+pillows?\b", re.I), "stt fillers"),
    (re.compile(r"\bs\s*t\s*t\b", re.I), "stt"),
    (re.compile(r"\bsct\b", re.I), "stt"),
    (re.compile(r"\bst t\b", re.I), "stt"),
    (re.compile(r"\bpronounciation\b"), "pronunciation"),
    (re.compile(r"\bpronounse\b"), "pronounce"),
)

_FEATURE_NAME_ALTS: dict[str, str] = {
    "todo": r"to-?dos?|to do(?:s| list)?|todos?|checklist|reminders?",
    "notes": r"notes?|personal notes?",
    "weather": r"weather|forecast",
    "news": r"news|headlines",
    "math": r"maths?|matt|mat|maps|percent(?:age)?|calculat(?:e|or|ion)s?",
    "lookup": r"lookups?|look ?ups?|wikipedia|look(?:ing)? up",
    "camera": r"cameras?|webcams?|facecams?",
    "profile": r"profiles?|users?",
    "sleep": r"sleep(?: mode)?",
    "background": r"background(?: mode)?",
    "update": r"updates?",
    "appointment": r"appointments?",
    "playback": r"playback|video controls?",
    "audio": r"audio|volume|mute",
    "game": r"game lookups?|game guides?",
    "measure": r"measure(?:ment)?s?",
    "pronunciation": (
        r"pronunciations?|pronounce|custom words?|word recordings?|"
        r"word overrides?|how you say(?: words)?"
    ),
    "planner": r"planners?|floor plans?|3d graphs?|3d planners?|blueprints?",
    "voice_access": r"voice controls?|voice control access|admin voice access",
    "temporary_access": r"temporary access|access minutes|minutes for that access|reduce the minutes|shorten (?:that )?access|time limit for (?:that )?access",
    "system_panel": r"system panels?|developer panels?|dev panels?",
    "reference_images": r"reference images?|image references?|image library",
    "image_generation": r"image (?:generation|generator|studio|maker)|generate images?|make images?|picture maker",
    "attitude": r"attitudes?|personality|mood|sassy|skittish|shy|mean mode|cuss(?:ing)? at me",
    "safety": r"family (?:safe )?mode|safe mode|children are present|speaker mode|speaker safe",
    "future_tasks": r"future (?:updates?|tasks?)|task list",
    "reply_style": r"unfiltered|curse words|swear words|blacklist|blocked words|verify my age",
    "team_updates": r"team updates?|submit update|suggest update|approve update|reject update",
    "learned_phrases": (
        r"learn(?:ed)? (?:that|reply|phrase|phrases)|learned phrases?|"
        r"when i say|forget learned|list learned"
    ),
    "stt_fillers": (
        r"stt fill(?:er|ers)?|sct fill(?:er|ers)?|s t t fill(?:er|ers)?|"
        r"speech to text fill(?:er|ers)?|filler words?|thinking fill(?:er|ers)?"
    ),
    "stt_word_repair": r"auto ?correct(?:s|ed|ing)?|automatic(?:ally)? correct|word repairs?|stt word repairs?",
}

_USAGE_RES: dict[str, re.Pattern[str]] = {
    "weather": re.compile(
        r"\b(?:"
        r"(?:can you |could you |would you |please )?(?:tell me |give me |check |get |what's |whats |what is |how's |hows |how is ).{0,40}weather|"
        r"what(?:s| is) the weather|how(?:s| is) the weather|"
        r"local weather|local forecast|my weather|"
        r"weather (?:today|outside|like|now|right now|forecast)|"
        r"is it raining|will it rain|temperature|"
        r"how (?:hot|cold) is it"
        r")\b",
        re.I,
    ),
    "news": re.compile(r"\b(?:what(?:s| is) (?:my |the )?(?:latest )?news|show (?:me )?the news)\b"),
    "notes": re.compile(r"\b(?:what are my notes|note this|add (?:a )?note)\b"),
    "todo": re.compile(
        r"\b(?:what is my to[ -]?do|whats? on my to[ -]?do(?: list)?|"
        r"what is on my to[ -]?do(?: list)?|add .{0,40}to[ -]?do|open (?:the )?to[ -]?do)\b"
    ),
    "lookup": re.compile(
        r"\b(?:look up |search wikipedia |search for |find me information |find information on )\b"
    ),
    "math": re.compile(r"\b(?:what is \d|solve |percent of |\d+\s*[+\-x*/])\b"),
    "planner": re.compile(
        r"\b(?:open|show|start|launch).{0,28}(?:planner|floor plan|3d graph|3d planner|blueprint)\b",
        re.I,
    ),
    "screen_monitor": re.compile(
        r"\b(?:"
        r"(?:can you |could you |would you |please )?(?:watch|lets watch|let us watch|start watching) (?:this|a|the) video(?: with me)?|"
        r"watch (?:this|a|the) video with me|"
        r"video (?:finished|done|over)|(?:done|finished) watching(?: this| the)? video|"
        r"what am i doing"
        r")\b",
        re.I,
    ),
}

_WHICH_FEATURE = (
    "Which one — weather, news, notes, to-dos, math, lookups, image library, or image studio?"
)

_MAIN_FEATURE_DETAILS: dict[str, str] = {
    "todo": (
        "To-dos can hold tasks with a number so you can say delete 1, edit 2, or move 3 to 1. "
        "Say add this to the to-do list, open the to-do list, or what is my to-do list. "
        "You can set a daily task at a time, like meds or trash. "
        "Say what's my reminder and I will ask notes or to-do list. "
        "If I hear the wrong words, say that's not what I said, or delete the entire to-do list to start over. "
        "If speaking is hard I will open a box so you can type it."
    ),
    "notes": (
        "Notes store things you want remembered. Say note this, then what to keep, "
        "and later ask what are my notes. "
        "You can still ask for notes while I am in sleep mode. "
        "If I miss it a few times I open a box so you can type with no word limit. "
        "Say what's my reminder and I will ask notes or to-do list."
    ),
    "weather": (
        "Weather can give current conditions, the local forecast, and the next few days including rain chances. "
        "Say what's the weather, what's the forecast, or the next few days. "
        "If a reading is wrong, say that weather is not right or it's storming outside."
    ),
    "news": (
        "News can pull a briefing without opening a browser. "
        "Say what's my latest news or show me the news. "
        "I can also watch for a daily briefing when that is enabled on your profile."
    ),
    "math": (
        "Math can handle everyday numbers and money. "
        "Ask what is 15 percent of 200, solve 2x plus 5 equals 15, "
        "or earnings like how much can I earn at 50 dollars a day for a month."
    ),
    "lookup": (
        "Lookups skim Wikipedia and the public web without opening a browser. "
        "Say look up all building materials, find me information on this, "
        "or how do I beat the first boss in a game, and I will tell you what I find. "
        "I can save results in a topic folder and retrieve them later. "
        "I will not copy all of Wikipedia."
    ),
    "camera": (
        "Camera is available for profile face setup and auto switching, "
        "and for features that need a live picture, like measuring. "
        "Say camera access and a popup will ask Yes or No for that feature, like other Windows programs. "
        "You can set a profile image instead of showing your face. "
        "Say detect my camera or test the camera if you want a test run."
    ),
    "pronunciation": (
        "Yes. You can record any word or phrase more than one way, so live can sound like live or like alive. "
        "Say let me update the audio to the correct wording, record pronunciation, "
        "or change how you say a word or phrase. "
        "A recorder opens and starts immediately. Say it the way you want me to hear it. "
        "I keep the target word, remember how that recording actually sounded, and speak it in my own voice using that sound. "
        "Your recording stays a reference and a preview; I do not play it when I talk. "
        "Each new recording adds another pronunciation instead of replacing the last one, and the newest one is active first. "
        "If a recording sounds like alive or bye, I keep that as the learned sound while the word stays live. "
        "Say open the pronunciation popup to manage every recording, and edit pronunciations to pick, re-record, or remove one. "
        "If you meant words I mishear when you say them, that is learned phrases; say learned phrase and I will learn the right wording."
    ),
    "planner": (
        "The planner is a building whiteboard inside Silva. "
        "Say open the planner. Drag lines on the 2D grid — each one shows feet and inches. "
        "Click a line to change its length or angle. When lines close into a room, I show square footage, "
        "including extra rooms you split off on any floor. "
        "Turn on the site lot for grass, dirt, or slope before you draw. "
        "Say map me a two bedroom house, or open Map a building, and I will lay it out. "
        "You can upgrade walls or furniture by clicking or by telling me."
    ),
}

_MAIN_FEATURE_SHORT: dict[str, str] = {
    "todo": "Yes. Say add this to the to-do list, open the to-do list, or what is my to-do list.",
    "notes": "Yes. Say note this, then what to remember, or ask what are my notes.",
    "weather": "Yes. Ask for the weather, the local forecast, or the next few days.",
    "news": "Yes. Say what's my latest news or show me the news.",
    "math": "Yes. Ask things like what is 15 percent of 200, or solve 2x plus 5 equals 15.",
    "lookup": "Yes. Ask me to look something up and I'll skim Wikipedia and the web without opening a browser.",
    "camera": (
        "Yes. Camera is available from the start for profile setup and auto switching. "
        "Say camera access to allow or deny it for a feature. "
        "You can also pick your own profile image if you do not want your face shown."
    ),
}

_OPTIONAL_FEATURE_SHORT: dict[str, str] = {
    "profile": "Yes. Say user profile, my profile, or who am I.",
    "sleep": "Yes. Say sleep mode, then wake up Silva when you want me back.",
    "background": (
        "Yes. I keep listening in the background so you don't have to click the command window. "
        "Press the Stream Deck button or say show the console to bring the window up. "
        "Say hide the console to tuck it away."
    ),
    "update": "Yes. Ask what's the new update, or say update Silva to load it while I keep running.",
    "appointment": "Yes. Say schedule appointment, or list my appointments.",
    "playback": "Yes. Say pause the video, play the video, or resume.",
    "audio": "Yes. You can mute or unmute a specific app, like mute chrome.",
    "game": "Yes. Ask how to do something in a game and I'll skim the web for it.",
    "measure": "Yes. Say look at this in my hand and measure it, or measure what's on my screen.",
    "pronunciation": (
        "Yes. Say let me update the audio to the correct wording, or record pronunciation, then say only the word."
    ),
    "planner": (
        "Yes. Say open the planner. Drag lines in 2D, close a room for square footage, or say map me a house."
    ),
    "voice_access": (
        "After voice enrollment, everyone can talk to Silva normally and use voice for images, visual "
        "guides, math, weather and news, notes, appointments, audio, and playback. Major system controls "
        "stay locked until a tier 4 admin requests them and the owner approves."
    ),
    "temporary_access": (
        "You can set the time limit when you approve temporary access in the Security Panel. It has to be "
        "between 1 and 240 minutes, and it expires on its own. If you want fewer minutes on a session that "
        "is already running, use Kick & Block in the Security Panel, then approve the person again with the "
        "shorter time limit. There is no voice command to change an active grant's minutes."
    ),
    "system_panel": (
        "The owner or a tier 4 admin can say open the system panel. You can also say open voice access, "
        "open update queue, open requests, or open code lab to go straight to that tab."
    ),
    "reference_images": (
        "Downloads are scanned only when the owner says scan downloads for images. "
        "The owner can then open reference images to view, delete, or block them from returning. "
        "You cannot really give the owner image library to someone else. I refuse to save library access for anyone but the owner, and both the voice command and the on-screen viewer check owner status again before opening it, so a stray grant would not work. "
        "A temporary Security Panel grant can let someone switch into a protected profile for 1 to 240 minutes, but it expires on its own, drops them back to guest, and can be ended right away with Kick & Block. "
        "No images are copied or sent out by that grant; the library stays local."
    ),
    "image_generation": (
        "Anyone can say open image studio or ask me to generate an image. "
        "You can add details, describe the image for copyable text, and save it to the owner-only image library."
    ),
    "attitude": (
        "Anyone can say act shy, be skittish, be sassy, be mean, or act normal. "
        "If you curse while joking, I stay calm; a mild vent or a normal curse gets sass; "
        "loud, direct abuse gets mean. I match the wording, the joking cues, and how loud "
        "you said it instead of treating every curse word the same."
    ),
    "safety": (
        "Say children are present, family mode on, or speaker mode on to limit reactions and image prompts. "
        "Speaker mode also ignores Silva's own voice echo unless you tell it to answer."
    ),
    "room_audio": (
        "If I hear another voice while you are talking, I hold my reply until the room is clear instead of answering over you. "
        "With owner or tier 4 room audio permission I can listen for overlapping voices and ask people to speak one at a time. "
        "For a crowd, I ask whether kids are there and wait for the voices to answer before I get firmer. "
        "If kids are present, or speaker mode is on, I stay polite. I do not cuss at a crowd."
    ),
    "future_tasks": (
        "The owner can say add future update ..., list future updates, delete future update ..., "
        "or assign future update ... to an admin. Future Tasks is also editable in the System Panel."
    ),
    "reply_style": (
        "Owner and admins can allow or turn off unfiltered replies per user. Other users must verify "
        "face and age first by saying my age is ..., with several tries. Clear blocked words removes "
        "the old don't-say blacklist."
    ),
    "team_updates": (
        "Anyone can say submit update ... . The owner or admins can list, approve, or reject team "
        "updates. Rejected updates show a popup and can be emailed back with a reply."
    ),
    "learned_phrases": (
        "The correct way to say certain things is learn that ... means ..., when I say ... say ..., "
        "or when I say ... run ... . "
        "If I answer wrong, say no, I meant ... and I will learn the right reply for that phrase."
    ),
    "crosschat_memory": (
        "CrossChat remembers custom instructions, speech patterns, and ratings across voice and text. "
        "Say remember that ..., rate this reply four out of five, talk more casually, or list instructions."
    ),
    "stt_fillers": (
        "STT fillers are thinking sounds like uhm, um, uh, and hmm. Silva recognizes them so moving the mic "
        "or talking from farther away does not turn a filler into a command. If your voice clearly fades at "
        "the end, Silva treats it as thinking and ignores it, then lowers the mic threshold for the next listen."
    ),
    "stt_word_repair": (
        "I clean up common speech-to-text mistakes before I run a command. For example, I turn when I is into "
        "when I ask, some money answers into somebody else access, help braces into help phrases, and break "
        "yourself up into a wake hint. If I still get your words wrong, say no, I meant ..., and I will learn "
        "the right wording for next time."
    ),
    "code_assist": (
        "Owner and admins can say help me code, then describe the feature, or say open the text box to type it. "
        "Silva skims its own codebase and writes exact placement notes to a .txt file in ~/.silva/code_assist without editing the source. "
        "The owner can turn it off in the terminal with codeassist off."
    ),
    "screen_monitor": (
        "With owner approval, say what am I doing to use the latest screen summary, or watch a video with "
        "me and say video finished to save what I saw and heard in its own category, including informative, "
        "survival, electrical grid, inventions, random, core, manhwa, and manga. You can ask me about those "
        "videos later. I only download when you say so clearly and then confirm yes download this video. "
        "Silva never opens a video by itself."
    ),
    "stream_deck": (
        "Say stream deck page one slot five run weather to bind a command, stream deck page one slot five "
        "bind weather for a self-updating tile, or stream deck list. Typed input opens a text box when needed."
    ),
}

_FEATURE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("todo", ("to do", "todo", "to-do", "checklist", "reminders")),
    ("notes", ("notes", "note this", "personal note")),
    ("weather", ("forecast", "weather")),
    ("news", ("news", "headlines")),
    ("math", ("math", "matt", "mat", "maps", "percent", "calculate")),
    ("lookup", ("wikipedia", "look up", "lookup", "look something up", "find information", "lookups")),
    ("camera", ("camera", "webcam", "facecam")),
    ("profile", ("profile", "users", "who am i")),
    ("sleep", ("sleep", "wake")),
    ("background", ("background", "in a game", "without clicking")),
    ("update", ("update", "new features", "what's new", "whats new")),
    ("appointment", ("appointment", "schedule")),
    (
        "screen_monitor",
        (
            "watch this video",
            "video with me",
            "watch videos",
            "video learning",
            "video notes",
            "video finished",
            "download this video",
            "manga videos",
            "manhwa videos",
        ),
    ),
    ("playback", ("pause", "playback", "video", "resume")),
    ("audio", ("mute", "unmute", "volume", "audio")),
    ("game", ("game", "elden")),
    ("measure", ("measure", "measurement")),
    (
        "pronunciation",
        ("pronunciation", "pronounce", "custom word", "word recording", "word override", "how you say"),
    ),
    ("planner", ("planner", "floor plan", "3d graph", "3d planner", "blueprint")),
    ("voice_access", ("voice control", "voice controls", "voice control access", "admin voice")),
    ("temporary_access", ("temporary access", "access minutes", "minutes for that access", "reduce the minutes", "shorten that access", "time limit for that access")),
    ("system_panel", ("system panel", "developer panel", "dev panel")),
    ("reference_images", ("reference image", "image reference", "image library")),
    ("image_generation", ("image generation", "image generator", "image studio", "picture maker")),
    (
        "attitude",
        (
            "attitude",
            "personality",
            "mood",
            "sassy",
            "skittish",
            "shy",
            "mean mode",
            "cussing at me",
            "cuss at me",
        ),
    ),
    ("safety", ("family mode", "safe mode", "children are present", "speaker mode", "speaker safe")),
    (
        "room_audio",
        (
            "other people are in the room",
            "another person in the room",
            "more than one person",
            "someone else talking",
            "other people talking",
            "they started talking",
            "crowd of people",
            "crowd speech policy",
            "cross speech policy",
            "multiple voices",
            "room speech",
        ),
    ),
    ("future_tasks", ("future update", "future task", "task list")),
    ("reply_style", ("unfiltered", "curse words", "verify my age", "blocked words")),
    ("team_updates", ("team update", "submit update", "approve update", "reject update")),
    (
        "learned_phrases",
        (
            "learn that",
            "learned phrase",
            "learned phrases",
            "when i say",
            "work correctly",
            "the way i asked",
            "learned replies",
        ),
    ),
    ("stt_fillers", ("stt filler", "stt fillers", "sct fillers", "s t t fillers", "speech to text filler", "filler words", "thinking fillers", "std pillows", "sdt pillows")),
    ("stt_word_repair", ("autocorrect", "auto correct", "autocorrects", "autocorrect stuff", "automatic correct", "word repair", "stt word repair")),
    ("crosschat_memory", ("cross chat", "crosschat", "custom instruction", "rate this reply", "talk more casually")),
    ("code_assist", ("help me code", "help me add", "code this feature", "placement notes")),
    ("screen_monitor", ("what am i doing", "screen monitoring", "watch this video", "video finished")),
    ("stream_deck", ("stream deck", "deck button", "deck tile")),
)


def normalize_help_text(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\bin details\b", "in detail", text)
    text = re.sub(r"^(?:all right|alright|okay|ok|so|well|hey|um|uh)\b[\s,]*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    for pattern, replacement in _STT_FEATURE_ALIASES:
        text = pattern.sub(replacement, text)
    return re.sub(r"\s+", " ", text).strip()


_DETAIL_TOPIC_RES: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^(?:can you |could you |would you |please )?tell me (?:in detail |in details )?"
        r"(?:about |on |what (?:is|are) |what )?(.+)$",
        re.I,
    ),
    re.compile(r"^give me (?:the )?details (?:on|for|about|of) (.+)$", re.I),
    re.compile(r"^details (?:on|for|about|of) (.+)$", re.I),
    re.compile(
        r"^(?:can you |could you |would you |please )?(?:describe|explain) in detail "
        r"(?:what (?:the )?)?(.+?)(?:\s+does|\s+do)?$",
        re.I,
    ),
    re.compile(r"^(?:explain|describe|break down) (.+)$", re.I),
    re.compile(r"^go into detail (?:on|about|for) (.+)$", re.I),
    re.compile(r"^what (?:is|are) (.+)$", re.I),
)

_DETAIL_TOPIC_REJECT = {
    "",
    "available options",
    "details",
    "it",
    "that",
    "this",
    "you",
    "yourself",
    "silva",
    "the options",
    "more",
    "by the way",
    "whatever",
    "something",
    "anything",
    "the way",
}


def detail_topic(text: str) -> str:
    normalized = normalize_help_text(text)
    if not normalized or match_feature_id(normalized):
        return ""
    for pattern in _DETAIL_TOPIC_RES:
        match = pattern.match(normalized)
        if not match:
            continue
        topic = re.sub(r"\b(?:are|is|mean|means|do|does)\b$", "", match.group(1)).strip()
        topic = re.sub(r"\s+what\s+(?:does|do|is|are)\b.*$", "", topic).strip()
        topic = re.sub(r"^(?:does|do|is|are)\s+", "", topic).strip()
        topic = re.sub(r"^(?:the|a|an|your|my)\s+", "", topic).strip()
        topic = re.sub(r"\s+", " ", topic)
        if topic.lower() in _DETAIL_TOPIC_REJECT:
            return ""
        if len(topic) < 4 or len(topic) > 160:
            return ""
        return topic
    return ""


_PLAIN_REQUEST_RE = re.compile(
    r"\b(?:i (?:do not|don't) (?:even )?(?:understand|know what you (?:just )?said|follow that)|"
    r"what did (?:that|you) mean|what does that mean|say that (?:again )?in plain (?:english|words)|"
    r"in simpler words|use simpler words|explain that simpler)\b",
    re.I,
)


def is_plain_english_request(text: str) -> bool:
    return bool(_PLAIN_REQUEST_RE.search(str(text or "")))


def is_help_request(text: str) -> bool:
    if is_plain_english_request(text):
        return True
    normalized = normalize_help_text(text)
    if not normalized:
        return False
    if normalized in {"help", "commands"}:
        return True
    if not any(phrase in normalized for phrase in HELP_TRIGGERS):
        return False
    # Naming a tool means they want that tool's description, not the whole list.
    if match_feature_id(normalized):
        return False
    return True


def match_feature_id(text: str) -> str | None:
    normalized = normalize_help_text(text)
    if not normalized:
        return None
    if _STT_COMPLAINT_RE.search(normalized):
        return "stt_word_repair"
    if _PRONUNCIATION_TRAINING_ASK_RE.search(normalized) or _PRONUNCIATION_COMPLAINT_RE.search(normalized):
        return "pronunciation"
    for feature_id, keywords in _FEATURE_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return feature_id
    return None


def _looks_like_capability_ask(normalized: str) -> bool:
    return any(marker in normalized for marker in _CAPABILITY_ASK_MARKERS)


def _looks_like_detail_ask(normalized: str) -> bool:
    return any(marker in normalized for marker in _DETAIL_ASK_MARKERS)


def _is_feature_usage(normalized: str, feature_id: str) -> bool:
    usage = _USAGE_RES.get(feature_id)
    if usage is None or not usage.search(normalized):
        return False
    if _is_meta_about_feature(normalized, feature_id):
        return False
    return True


def _is_meta_about_feature(normalized: str, feature_id: str) -> bool:
    alt = _FEATURE_NAME_ALTS.get(feature_id)
    if not alt:
        return False
    name = rf"(?:the |a |your |my )?({alt})"
    patterns = [
        rf"\bwhat do you mean by {name}\b",
        rf"\bwhat does {name} (?:do|mean)\b",
        rf"\bwhat do {name} do\b",
        rf"\btell me (?:in detail )?(?:what you mean by |what do you mean by |what you mean by |what (?:does|do) ){name}\b",
        rf"\btell me (?:in detail )?what {name} (?:are|is|mean|means|do|does)\b",
        rf"\btell me what do you mean by {name}\b",
        rf"\btell me in details?.{{0,80}}(?:what (?:do you|you) (?:do|mean) )?(?:by |about |on |for )?{name}\b",
        rf"\btell me in detail.{{0,80}}{name}\b",
        rf"\bwhat do you do (?:by|of|for|with|about|on) {name}\b",
        rf"\b(?:give me |get me |i want |i need )?(?:the )?details (?:on|for|about|of) {name}\b",
        rf"\bexplain {name}\b",
        rf"\bdescribe {name}\b",
        rf"\bbreak down {name}\b",
        rf"\bgo into detail (?:on|about|for) {name}\b",
        rf"\bhow (?:does|do) {name} work\b",
        rf"\bhow (?:would|could|can|will|might) you {name}\b",
        rf"\bhow you (?:would|could|can|will|might) {name}\b",
        rf"\btell me how (?:you|i) (?:would|could|can|should) {name}\b",
        rf"\bwhat can (?:i do with |i do for |you do (?:with |for |of |about |on )?)?{name}\b",
        rf"\bwhat do you do (?:of|for|with|about|on) {name}\b",
        rf"\bwhat can you do (?:of|for|with|about|on) {name}\b",
        rf"\b{name} (?:options|details|feature)\b",
        rf"\bmean by {name}\b",
    ]
    # These tools are not "current data" requests, so "what is lookups" is an explanation.
    if feature_id in {"lookup", "math", "camera", "stt_fillers"}:
        patterns.extend(
            (
                rf"\bwhat (?:is|are) {name}\b",
                rf"\btell me about {name}\b",
            )
        )
    return any(re.search(pattern, normalized) for pattern in patterns)


_GENERIC_DETAIL_RE = re.compile(
    r"\b("
    r"give me (?:the )?details(?:\s+(?:on|for|about|of))|"
    r"details (?:on|for|about|of)|"
    r"what do you mean by|"
    r"tell me what (?:do you|you) mean by|"
    r"tell me in detail|"
    r"tell me what \w+(?: \w+){0,8} (?:does|do|is|are|mean|means)|"
    r"what \w+(?: \w+){0,8} (?:does|do|is|are|mean|means)|"
    r"go into detail|"
    r"break down"
    r")\b"
)

_EXPLICIT_DETAIL_RE = re.compile(
    r"\b(?:in detail|in details|in depth|describe in detail|explain in detail|details on|details for|details about|details of)\b",
    re.I,
)


def _is_pointing_at_screen(normalized: str) -> bool:
    if not re.search(r"\b(this|that|it)\b", normalized):
        return False
    if re.search(r"\b(lookups?|weather|news|notes?|to-?dos?|math|camera)\b", normalized):
        return False
    return not detail_topic(normalized)


_PRONUNCIATION_TRAINING_ASK_RE = re.compile(
    r"\bif i (?:train|teach|program|record)\b.{0,80}\b(?:will|can|would|do) you\b.{0,40}\b(?:say|speak|use|pronounce)\b|"
    r"\b(?:will|can|would|do) you (?:say|speak|use|pronounce)\b.{0,60}\b(?:if|when|after|the way|like) (?:i|we)\b.{0,30}\b(?:train|teach|record)\b|"
    r"\b(?:will|can|would|do) you (?:say|speak|use|pronounce)\b.{0,40}\b(?:them|those words?|certain words?|my words?|the words?)\b|"
    r"\b(?:can|will|would) you learn (?:to|how to) (?:say|speak|pronounce)\b"
)

_PRONUNCIATION_RUN_RE = re.compile(
    r"\b(change|record|train|override|edit|fix|teach|replace|update)\b.+"
    r"\b(how you say|how you pronounce|how the ai says|pronunciation|custom word|audio|wording)\b|"
    r"\b(record|train|override) (?:a |the )?(pronunciation|custom word)\b|"
    r"\b(update the audio|correct wording)\b"
)

_PRONUNCIATION_COMPLAINT_RE = re.compile(
    r"\bif i train you\b|"
    r"\b(?:one of the words|that word|it)\b.{0,50}\b(?:different ways|sound like|supposed to sound)\b|"
    r"\bsometimes you say\b.{0,60}\b(?:supposed to|should|sound like|alive|live)\b|"
    r"\bwhen i said\b.{0,60}\b(?:i said|not pay by|sound like)\b|"
    r"\bstill not (?:saying|speaking|autocorrecting)\b.{0,80}\b(?:microphone|what i am saying|what i said|word)\b"
)

_PRONUNCIATION_ASK_SHAPE_RE = re.compile(
    r"\bhow (?:do you|should you|would you|do i) (?:say|pronounce)(?: the word)?\b|"
    r"\btell me how (?:you|silva|the ai) (?:say|pronounce|speak)(?:s)?(?: the word)?\b|"
    r"\bwhat (?:is|s) (?:the )?(?:pronunciation of|how you say)\b|"
    r"\bhow is (?:the word )?\w+ pronounced\b"
)

_ROOM_DETAIL_RE = re.compile(
    r"\b(?:what about if|how would you respond|if other people|if another person|"
    r"if someone else|they started talking|other people are in the room|"
    r"tell me about|what room speech|room speech|crowd speech policy|"
    r"cross speech policy)\b",
    re.I,
)

_STT_COMPLAINT_RE = re.compile(
    r"\bstill not autocorrecting\b|"
    r"\bnot autocorrecting to what i am saying\b"
)


def is_feature_detail_ask(text: str) -> bool:
    if is_help_request(text):
        return False
    try:
        from silva.commands.update_phrases import is_whats_new_update_phrase

        if is_whats_new_update_phrase(text):
            return False
    except Exception:
        pass
    normalized = normalize_help_text(text)
    if not normalized:
        return False
    if _STT_COMPLAINT_RE.search(normalized):
        return True
    if _PRONUNCIATION_COMPLAINT_RE.search(normalized):
        return True
    feature_id = match_feature_id(normalized)
    if feature_id == "room_audio" and _ROOM_DETAIL_RE.search(normalized):
        return True
    if feature_id is None:
        if _PRONUNCIATION_ASK_SHAPE_RE.search(normalized):
            return False
        if _is_pointing_at_screen(normalized):
            return False
        if _GENERIC_DETAIL_RE.search(normalized) or _EXPLICIT_DETAIL_RE.search(normalized):
            return True
        return _looks_like_detail_ask(normalized) and (
            "available options" in normalized
            or normalized in {"options", "details", "in detail"}
        )
    if feature_id not in _MAIN_FEATURE_DETAILS and feature_id not in _OPTIONAL_FEATURE_SHORT:
        return False
    if feature_id == "pronunciation" and _PRONUNCIATION_TRAINING_ASK_RE.search(normalized):
        return True
    if feature_id == "pronunciation" and _PRONUNCIATION_RUN_RE.search(normalized):
        return False
    if _is_feature_usage(normalized, feature_id):
        return False
    if _is_meta_about_feature(normalized, feature_id):
        return True
    if any(phrase in normalized for phrase in HELP_TRIGGERS):
        return True
    if not _looks_like_detail_ask(normalized):
        return False
    return True


def should_yield_to_feature_help(text: str) -> bool:
    """True when this utterance is asking about a feature, not asking to run it."""
    if not text or not str(text).strip():
        return False
    return is_feature_detail_ask(text) or is_capability_ask(text)


def is_capability_ask(text: str) -> bool:
    if is_help_request(text) or is_feature_detail_ask(text):
        return False
    try:
        from silva.commands.update_phrases import is_whats_new_update_phrase

        if is_whats_new_update_phrase(text):
            return False
    except Exception:
        pass
    normalized = normalize_help_text(text)
    if not normalized or not _looks_like_capability_ask(normalized):
        return False
    if _PRONUNCIATION_RUN_RE.search(normalized):
        return False
    feature_id = match_feature_id(normalized)
    if feature_id is None:
        return False
    if _is_feature_usage(normalized, feature_id):
        return False
    return True


def feature_detail_reply_for_user(text: str, user: dict) -> str | None:
    if not is_feature_detail_ask(text):
        return None
    from silva.users.manager import is_owner
    from silva.users.tiers import normalize_tier

    tier = normalize_tier(user.get("tier", 1))
    if not (tier >= 3 or is_owner(user)):
        return "You can talk with me. Higher tier users can run more commands."
    feature_id = match_feature_id(text)
    if feature_id is None:
        return _WHICH_FEATURE
    return _MAIN_FEATURE_DETAILS.get(feature_id) or _OPTIONAL_FEATURE_SHORT.get(feature_id)


def capability_reply_for_user(text: str, user: dict) -> str | None:
    if not is_capability_ask(text):
        return None
    from silva.users.manager import is_owner
    from silva.users.tiers import normalize_tier

    tier = normalize_tier(user.get("tier", 1))
    if not (tier >= 3 or is_owner(user)):
        return "You can talk with me. Higher tier users can run more commands."
    feature_id = match_feature_id(text)
    if feature_id is None:
        return None
    if feature_id in _MAIN_FEATURE_SHORT:
        return _MAIN_FEATURE_SHORT[feature_id]
    return _OPTIONAL_FEATURE_SHORT.get(feature_id)


def help_reply_for_user(user: dict) -> str:
    from silva.users.manager import is_owner
    from silva.users.tiers import normalize_tier

    tier = normalize_tier(user.get("tier", 1))
    if tier >= 3 or is_owner(user):
        return HELP_CAPABILITIES_TEXT
    return "You can talk with me. Higher tier users can run more commands."
