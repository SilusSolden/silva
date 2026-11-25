"""Rule-based small talk data — no external AI model, all local patterns."""

from __future__ import annotations

# Each category: triggers, openers (response, follow_up_key), follow_ups map.

GREETING_TRIGGERS = (
    "hello", "hi", "hey", "hi there", "hello there", "good morning", "good afternoon",
    "good evening", "morning", "evening", "greetings", "howdy", "yo", "hiya", "heya",
    "hello silva", "hi silva", "hey silva", "good day",
)

HOW_ARE_YOU_TRIGGERS = (
    "how are you",
    "how are you doing",
    "how you doing",
    "how are ya",
    "hows it going",
    "how is it going",
    "how have you been",
    "how've you been",
    "you okay",
    "are you okay",
    "you doing okay",
    "you alright",
    "are you alright",
    "how are things",
    "how are things going",
    "hows everything",
    "how is everything",
    "hows your day",
    "how is your day",
    "how was your day",
    "everything good",
    "you good",
    "you doing good",
    "how you been",
    "how have you been doing",
    "how are you doing today",
    "how are you today",
    "how are you doing tonight",
)

CASUAL_CHECKINS = (
    "just checking in",
    "wanted to say hi",
    "thought id say hi",
    "hows life",
    "how is life",
    "whats new with you",
    "nice to talk to you",
    "good to talk to you",
    "good to hear from you",
)

CASUAL_CHECKIN_REPLIES = (
    "Same here - it's always nice to chat. How have you been?",
    "Good to hear from you too. What's been going on?",
    "I'm glad you reached out. How's everything with you?",
    "Likewise. What's new in your world?",
    "Always nice talking with you. How's your day been?",
)

CASUAL_QUESTION_REPLIES = (
    "That's a fair question. I'm doing alright - how about you?",
    "Good question. I'm here and doing fine. What's on your mind?",
    "I'm doing okay. What made you ask?",
    "Not bad at all. How are you feeling about things?",
    "I'm good. Want to tell me what's going on with you?",
)

WHATS_UP_TRIGGERS = (
    "whats up", "what's up", "sup", "what is up", "what are you up to",
    "whats going on", "what is going on", "anything new", "what are you doing",
)

THANKS_TRIGGERS = (
    "thank you", "thanks", "thanks a lot", "thank you so much", "appreciate it",
    "much appreciated", "that helps", "perfect thanks", "thanks silva", "thank you silva",
)

ENCOURAGEMENT = (
    "i'm bored", "im bored", "i am bored", "i'm tired", "im tired", "i am tired",
    "i'm stressed", "im stressed", "i am stressed",
)

MOOD_GOOD = ("good", "great", "fine", "well", "okay", "ok", "alright", "not bad", "pretty good", "doing good", "doing well", "im good", "i'm good", "all good", "cant complain", "can't complain", "solid", "decent")
MOOD_BAD = ("bad", "rough", "tired", "exhausted", "stressed", "awful", "horrible", "not great", "not good", "struggling", "drained", "worn out", "beat", "down", "sad", "upset", "frustrated", "anxious", "worried")
MOOD_NEUTRAL = ("same", "nothing much", "same old", "just chilling", "hanging in there", "surviving", "meh", "so so", "not much", "nothing really", "just here")

FOLLOW_UP_GREETING = {
    MOOD_GOOD: (
        "Glad to hear that. What's been going well for you?",
        "That's good to hear. Anything you're looking forward to?",
        "Nice. Want to chat about your day or need help with something?",
        "Good to know. What would you like to do next?",
        "Happy to hear it. I'm here if you want to keep talking.",
    ),
    MOOD_BAD: (
        "I'm sorry it's been rough. Want to talk about it?",
        "That sounds hard. I'm here to listen if you need to vent.",
        "I hear you. Sometimes a quiet moment helps. Want to take it easy and chat?",
        "Sorry you're feeling that way. Can I help with something small?",
        "That doesn't sound fun. Tell me what's been weighing on you.",
    ),
    MOOD_NEUTRAL: (
        "Fair enough. What's on your mind today?",
        "Got it. Anything you want to get done or talk through?",
        "Alright. I'm here whenever you want to chat more.",
        "Understood. Want to keep talking or try a command?",
        "Okay. What would make today a little better?",
    ),
}

FOLLOW_UP_HOW_ARE_YOU = {
    MOOD_GOOD: (
        "I'm glad you're doing well. What's the best part of your day so far?",
        "That's great. Anything fun planned later?",
        "Good to hear. Want to tell me more about your day?",
        "Happy to hear that. What have you been up to?",
        "Nice. I'm doing well too — thanks for asking.",
    ),
    MOOD_BAD: (
        "I'm sorry to hear that. Want to talk about what's going on?",
        "That sounds tough. I'm here if you need to unload a little.",
        "I hope things ease up soon. Can I help with anything?",
        "I hear you. Sometimes talking helps — I'm listening.",
        "Sorry you're having a hard time. What's been the hardest part?",
    ),
    MOOD_NEUTRAL: (
        "Thanks for asking. Anything interesting happen today?",
        "Fair enough. What's been keeping you busy?",
        "Alright. Want to chat more or need help with something?",
        "Okay. I'm here if you want to keep the conversation going.",
        "Got it. Sometimes a normal day is still a good day.",
    ),
}

FOLLOW_UP_WHATS_UP = {
    MOOD_GOOD: (
        "Not much here — just ready to help. What's new with you?",
        "Same as always, listening and waiting. What's going on with you?",
        "Just hanging out in the background. Tell me what's up on your end.",
        "Nothing wild on my side. What's been keeping you busy?",
        "All quiet here. What's on your mind?",
    ),
    MOOD_BAD: (
        "Not much here. Sounds like you might have a lot going on though — want to talk?",
        "Just here as usual. You sound like you could use a listener.",
        "Same old on my end. What's been stressing you out?",
        "Quiet here. If something's bothering you, I'm here.",
        "Not much happening here. How are you really doing?",
    ),
    MOOD_NEUTRAL: (
        "Not much — just here to help. What about you?",
        "Same as always. What's going on in your world?",
        "Just waiting for your next command or chat. What's up with you?",
        "Nothing new here. Tell me what's on your mind.",
        "All good here. What would you like to talk about?",
    ),
}

FOLLOW_UP_PLANS = {
    ("yes", "yeah", "yep", "sure", "maybe", "probably", "i think so", "might"): (
        "Sounds good. Tell me more about it.",
        "Nice. What are you most excited about?",
        "Cool. I'd like to hear the details.",
        "Alright. Walk me through what you're thinking.",
        "Okay. What's the plan?",
    ),
    ("no", "nah", "not really", "dont think so", "don't think so", "not sure"): (
        "No worries. We can just chat then.",
        "That's fine. Anything else on your mind?",
        "Alright. I'm still here if you want to talk.",
        "Got it. Want to try something else?",
        "Okay. What would you rather do?",
    ),
}

FOLLOW_UP_TALK = {
    MOOD_GOOD: (
        "I'm glad we can talk. What's been the highlight of your week?",
        "Me too. What kind of things do you like to chat about?",
        "Same here. Tell me something good that happened recently.",
        "I enjoy talking with you too. What's on your mind?",
        "That's nice to hear. What should we talk about next?",
    ),
    MOOD_BAD: (
        "I'm here for you. What's been the hardest part lately?",
        "You don't have to go through it alone. Want to tell me more?",
        "I'll listen. Take your time — what's been going on?",
        "That sounds heavy. I'm here if you want to keep talking.",
        "Sometimes it helps to say it out loud. I'm listening.",
    ),
    MOOD_NEUTRAL: (
        "Sure. What's been on your mind lately?",
        "Okay. Where should we start?",
        "I'm listening. What's been going on?",
        "Alright. Tell me what's been happening.",
        "Go ahead. I'm here.",
    ),
}

JOKE_RESPONSES = (
    "Why did the computer go to therapy? It had too many bytes of emotional baggage.",
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "I told my router a joke. It didn't get the connection.",
    "Why was the JavaScript developer sad? Because they didn't Node how to Express themselves.",
    "What do you call a computer that sings? A Dell.",
    "Why did the scarecrow win an award? He was outstanding in his field.",
    "What do you call fake spaghetti? An impasta.",
    "Why don't scientists trust atoms? Because they make up everything.",
    "What did the ocean say to the beach? Nothing, it just waved.",
    "Why did the bicycle fall over? It was two tired.",
)

COMPLIMENT_REPLIES = (
    "Thank you. That means a lot.",
    "You're kind. I'm glad I could help.",
    "Thanks! I try my best for you.",
    "That made my day. I appreciate it.",
    "You're too kind. I'm happy to be here for you.",
)

BORED_REPLIES = (
    "I'm here if you want to keep talking.",
    "We can chat more if you'd like.",
    "I'm listening whenever you're ready.",
    "Want to hear a joke, check the weather, or look something up?",
    "Boredom happens. Want to start a small conversation or try a command?",
)

STRESSED_REPLIES = (
    "I'm sorry you're feeling that way. Take a breath. I'm here if you want to talk.",
    "That sounds tough. Want to talk about it, or should I help with something simple?",
    "I hear you. Sometimes a short break helps. I'm here whenever you need me.",
    "Stress is rough. Tell me what's going on if you want to vent.",
    "You don't have to handle everything alone. I'm here to listen.",
)

SMALL_TALK_WEATHER = (
    "Sounds like a nice day out there.",
    "I hope the weather treats you well today.",
    "Weather can really set the mood. How's it feeling for you?",
    "Days like that are good for a break.",
    "Enjoy it while you can.",
)

SMALL_TALK_COLD = (
    "Sounds chilly. Stay warm out there.",
    "Cold days are good for staying in and relaxing.",
    "Bundle up if you're heading out.",
    "I hope you have something warm to drink.",
    "Cold weather can be cozy if you're comfortable inside.",
)

SMALL_TALK_HOT = (
    "Sounds warm. Stay hydrated.",
    "Hot days can be draining. Take it easy if you can.",
    "Hope you have a way to cool off.",
    "Summer heat hits different. How are you holding up?",
    "Stay cool out there.",
)

LOVE_LIKE_REPLIES = (
    "That's sweet. I'm glad we're getting to talk.",
    "I appreciate that. I'm here for you.",
    "That's kind of you to say.",
    "I'm happy we can chat like this.",
    "Thanks. I enjoy talking with you too.",
)

CONFUSED_REPLIES = (
    "Sorry, I didn't catch that. Could you repeat that?",
    "I'm sorry, could you say that again?",
    "Sorry, what was that?",
    "I didn't catch all of that. Could you repeat it?",
)

THANKS_REPLIES = (
    "You're welcome. I'm happy to help.",
    "Any time. Glad I could help.",
    "No problem at all.",
    "You got it. Let me know if you need anything else.",
    "Happy to help anytime.",
)

NAME_ASK_REPLY = "I'm Silva, your local AI assistant. I'm here to help and chat with you."

GENERIC_QUESTION_REPLIES = (
    "That's a good question. I'm still learning, but I'm happy to talk it through with you.",
    "I'm not sure yet, but we can figure it out together.",
    "Interesting question. Tell me more about what you're thinking.",
    "I don't have a perfect answer, but I'm listening.",
    "Let's think through that together. What do you believe?",
)

CONTINUE_PHRASES = (
    "tell me more", "go on", "continue", "keep going", "and then", "what else",
    "say more", "more please", "keep talking", "i'm listening",
)

ANOTHER_JOKE = ("another joke", "one more joke", "tell me another joke", "another one", "more jokes")

def _build_greeting_openers(name_suffix: str) -> tuple[tuple[str, str], ...]:
    return (
        (f"Hey{name_suffix}! Good to hear from you. How are you doing?", "how_are_you"),
        (f"Hi{name_suffix}! Nice to talk with you. How's your day going?", "how_are_you"),
        (f"Hello{name_suffix}! How have you been?", "how_are_you"),
        (f"Hey there{name_suffix}! What's up?", "whats_up"),
        (f"Hi{name_suffix}! Always good to chat. How are things?", "how_are_you"),
        (f"Hello{name_suffix}! How's it going today?", "how_are_you"),
        (f"Hey{name_suffix}! I'm here. What's on your mind?", "whats_up"),
        (f"Hi{name_suffix}! Good to see you. How are you holding up?", "how_are_you"),
        ("Hey! Good to hear from you. How are you doing?", "how_are_you"),
        ("Hi there! How's your day been?", "how_are_you"),
        ("Hello! Nice to chat with you. What's going on?", "whats_up"),
        ("Hey! How have you been?", "how_are_you"),
    )


def _build_how_are_you_openers(name_suffix: str) -> tuple[tuple[str, str], ...]:
    return (
        (f"I'm doing pretty well, thanks for asking. How about you{name_suffix}?", "how_are_you"),
        ("I'm good! How's your day going?", "how_are_you"),
        ("Doing alright on my end. How are you doing?", "how_are_you"),
        ("I'm okay - thanks for checking in. How about you?", "how_are_you"),
        ("Not bad at all. How have you been?", "how_are_you"),
        ("I'm doing fine. How are things with you?", "how_are_you"),
        ("Pretty good, actually. How are you holding up?", "how_are_you"),
        ("I'm alright. What's been going on with you?", "how_are_you"),
        ("Doing well, thanks. How's everything on your side?", "how_are_you"),
        ("I'm good. How about you - having a decent day?", "how_are_you"),
        ("Can't complain over here. How are you feeling today?", "how_are_you"),
        ("All good on my end. How's your day treating you?", "how_are_you"),
    )


def _build_whats_up_openers(name_suffix: str) -> tuple[tuple[str, str], ...]:
    return (
        ("Not much - just here if you need me. What's up with you?", "whats_up"),
        ("Same as always. What's going on with you?", "whats_up"),
        ("Just hanging out in the background. What about you?", "whats_up"),
        ("Nothing too exciting here. What's new with you?", "whats_up"),
        (f"Hey{name_suffix} - quiet on my end. What's on your mind?", "whats_up"),
        ("All good here. What have you been up to?", "whats_up"),
        ("Not a whole lot. Tell me what's happening on your end.", "whats_up"),
        ("Just waiting to help out. What's going on today?", "whats_up"),
    )
