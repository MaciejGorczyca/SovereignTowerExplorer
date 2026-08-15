"""Faithful, minimal compiled-ink containers for Walker tests.

Each fixture is a verbatim copy of a real knot from
`game/InkExtracted/en/master.ink.json` (the compiled ink JSON that
`build_app.py`'s Walker consumes), trimmed to keep the tests small. Keeping
them byte-faithful means a change to the Walker's token output is caught
against the exact shapes the game actually produces.
"""

# test_affinity_angelica: speaker attribution via Locutor, presentation fn,
# a choice with an (end) stub.
SPEAKER_CHOICE = [
    [
        "ev",
        {"VAR?": "Angelica"},
        "str", "^", "/str", "str", "^", "/str",
        {"f()": "Apparition"},
        "pop",
        "/ev",
        "\n",
        "ev",
        {"VAR?": "Angelica"},
        {"f()": "Locutor"},
        "out",
        "/ev",
        "^ Hello Your Grace!",
        "\n",
        "^How are you?",
        "\n",
        "ev", "str", "^Hellooooooooooooooooooooooooooooooo", "/str", "/ev",
        {"*": ".^.c-0", "flg": 4},
        {"c-0": ["\n", "end", {"#f": 5}]},
    ],
    {"#f": 1},
]

# ligia_ending: an `if` branch only (c:true divert to the "b" container).
IF_ONLY = [
    "ev",
    {"VAR?": "Narrator"},
    {"f()": "Locutor"},
    "out",
    "/ev",
    "^Ligia eventually disappeared, and no one ever saw her again.",
    "\n",
    "^It is said, however, that off the shores of Southbay, sailors were saved by a mysterious mermaid princess...",
    "\n",
    [
        "ev",
        {"VAR?": "ligia_romanced"},
        "/ev",
        {"->": ".^.b", "c": True},
        {
            "b": [
                "\n",
                "^... This mermaid may also have been heard at times near the shores of Grest, singing a melancholy lullaby into the night.",
                "\n",
                {"->": ".^.^.^.10"},
                None,
            ]
        },
    ],
    "nop",
    "\n",
    "end",
    {"#f": 1},
]

# kingslayer_cutscene: an `if`/`else` pair (sibling unconditional `-> b` divert).
IF_ELSE = [
    [
        "ev",
        {"VAR?": "ursula_sent_to_kingslayer"},
        "/ev",
        {"->": ".^.b", "c": True},
        {
            "b": [
                "\n",
                "ev", {"VAR?": "Narrator"}, {"f()": "Locutor"}, "out", "/ev",
                "^A dull magical tension grips the air as the Kingslayer stands before your knight, impassive.",
                "\n",
                "ev", {"VAR?": "Narrator"}, {"f()": "Locutor"}, "out", "/ev",
                "^May she emerge from this unscathed...",
                "\n",
                {"->": ".^.^.^.2"},
                None,
            ]
        },
    ],
    [
        {"->": ".^.b"},
        {
            "b": [
                "\n",
                "ev", {"VAR?": "Narrator"}, {"f()": "Locutor"}, "out", "/ev",
                "^A dull magical tension grips the air as the Kingslayer stands before your knights, impassive.",
                "\n",
                "ev", {"VAR?": "Narrator"}, {"f()": "Locutor"}, "out", "/ev",
                "^May they emerge from this unscathed...",
                "\n",
                {"->": ".^.^.^.2"},
                None,
            ]
        },
    ],
    "nop",
    "\n",
    "end",
    {"#f": 1},
]

# UpdateFunds: a game-API function knot (temp param + VAR? read).
FUNCTION_FUNDS = [
    {"temp=": "Amount"},
    "^>>> update_funds : ",
    "ev", {"VAR?": "Amount"}, "out", "/ev",
    "\n",
    {"#f": 1},
]

# InjectMurderedKnight: a small function knot that reads a named var + ret.
FUNCTION_MURDERED = [
    "ev", "str", "^{murdered_knight_name}", "/str", "/ev",
    "~ret",
    {"#f": 1},
]

# tortosa_grievance_emergency: presentation + expression fns, a choice with a
# real destination (accept stitch), an effect (UnlockQuest) and a requirement
# (HintModification) attached to the choice.
CHOICE_EFFECTS = [
    [
        "ev",
        {"VAR?": "Cinderbeard"},
        "str", "^", "/str", "str", "^", "/str",
        {"f()": "Apparition"},
        "pop",
        "/ev",
        "\n",
        "ev",
        {"VAR?": "Cinderbeard"},
        {"VAR?": "Worried"},
        {"f()": "SwapExpression"},
        "pop",
        "/ev",
        "\n",
        "ev",
        {"VAR?": "Cinderbeard"},
        {"f()": "Locutor"},
        "out",
        "/ev",
        "^Ahoy!(BREAK_3) Uh... we've got ourselves a bit of a pirate problem out on the islands.",
        "\n",
        "^And dragons, too.(BREAK_3) Pirate-ridin' dragons, to be precise.(BREAK_3).(BREAK_3). they're firing off cannonballs and breathin' fire all at once.",
        "\n",
        "ev",
        "str",
        "ev",
        {"VAR?": "QUEST"},
        {"VAR?": "quest_tortosa_emergency"},
        "str", "^", "/str",
        {"f()": "HintModification"},
        "out",
        "/ev",
        "^A squad arrives to the rescue.",
        "/str",
        "/ev",
        {"*": ".^.c-0", "flg": 4},
        {
            "c-0": [
                "\n",
                "ev",
                {"VAR?": "quest_tortosa_emergency"},
                "str", "^", "/str",
                {"f()": "UnlockQuest"},
                "pop",
                "/ev",
                "\n",
                {"->": ".^.^.^.accept"},
                {"#f": 5},
            ]
        },
    ],
    {
        "accept": [
            "ev",
            {"VAR?": "Cinderbeard"},
            {"VAR?": "Smiling"},
            {"f()": "SwapExpression"},
            "pop",
            "/ev",
            "\n",
            "ev",
            {"VAR?": "Cinderbeard"},
            {"f()": "Locutor"},
            "out",
            "/ev",
            "^Nice.(BREAK_3) I'll tell the pirates to mind their manners while we wait.",
            "\n",
            "end",
            {"#f": 1},
        ],
        "#f": 1,
    },
]
