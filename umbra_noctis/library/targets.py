"""Target name resolution.

Normalizes whatever the Dwarf 3 (or the user) called an object — "M 31",
"m031", "NGC0224", "Andromeda", "andromeda galaxy" — to one canonical
designation, so multi-night data groups correctly in the library.
"""

from __future__ import annotations

import re

# canonical -> (friendly name, object type)
NOTABLE: dict[str, tuple[str, str]] = {
    "M1": ("Crab Nebula", "supernova remnant"),
    "M8": ("Lagoon Nebula", "emission nebula"),
    "M13": ("Hercules Cluster", "globular cluster"),
    "M16": ("Eagle Nebula", "emission nebula"),
    "M17": ("Omega Nebula", "emission nebula"),
    "M20": ("Trifid Nebula", "emission nebula"),
    "M27": ("Dumbbell Nebula", "planetary nebula"),
    "M31": ("Andromeda Galaxy", "galaxy"),
    "M33": ("Triangulum Galaxy", "galaxy"),
    "M42": ("Orion Nebula", "emission nebula"),
    "M44": ("Beehive Cluster", "open cluster"),
    "M45": ("Pleiades", "open cluster"),
    "M51": ("Whirlpool Galaxy", "galaxy"),
    "M57": ("Ring Nebula", "planetary nebula"),
    "M63": ("Sunflower Galaxy", "galaxy"),
    "M64": ("Black Eye Galaxy", "galaxy"),
    "M65": ("Leo Triplet member", "galaxy"),
    "M78": ("Casper the Ghost Nebula", "reflection nebula"),
    "M81": ("Bode's Galaxy", "galaxy"),
    "M82": ("Cigar Galaxy", "galaxy"),
    "M97": ("Owl Nebula", "planetary nebula"),
    "M101": ("Pinwheel Galaxy", "galaxy"),
    "M104": ("Sombrero Galaxy", "galaxy"),
    "M106": ("M106", "galaxy"),
    "NGC 253": ("Sculptor Galaxy", "galaxy"),
    "NGC 281": ("Pacman Nebula", "emission nebula"),
    "NGC 869": ("Double Cluster (h Persei)", "open cluster"),
    "NGC 884": ("Double Cluster (chi Persei)", "open cluster"),
    "NGC 891": ("Silver Sliver Galaxy", "galaxy"),
    "NGC 2237": ("Rosette Nebula", "emission nebula"),
    "NGC 2244": ("Rosette core cluster", "open cluster"),
    "NGC 6888": ("Crescent Nebula", "emission nebula"),
    "NGC 6960": ("Western Veil Nebula", "supernova remnant"),
    "NGC 6992": ("Eastern Veil Nebula", "supernova remnant"),
    "NGC 7000": ("North America Nebula", "emission nebula"),
    "NGC 7293": ("Helix Nebula", "planetary nebula"),
    "NGC 7635": ("Bubble Nebula", "emission nebula"),
    "IC 434": ("Horsehead Nebula region", "emission nebula"),
    "IC 1396": ("Elephant's Trunk Nebula", "emission nebula"),
    "IC 5070": ("Pelican Nebula", "emission nebula"),
    "IC 5146": ("Cocoon Nebula", "emission nebula"),
}

# common name -> canonical
_ALIASES: dict[str, str] = {
    "andromeda": "M31", "andromeda galaxy": "M31",
    "orion": "M42", "orion nebula": "M42", "great orion nebula": "M42",
    "pleiades": "M45", "seven sisters": "M45", "subaru": "M45",
    "triangulum": "M33", "triangulum galaxy": "M33",
    "whirlpool": "M51", "whirlpool galaxy": "M51",
    "ring nebula": "M57", "dumbbell": "M27", "dumbbell nebula": "M27",
    "crab": "M1", "crab nebula": "M1",
    "lagoon": "M8", "lagoon nebula": "M8",
    "eagle": "M16", "eagle nebula": "M16", "pillars of creation": "M16",
    "omega nebula": "M17", "swan nebula": "M17",
    "trifid": "M20", "trifid nebula": "M20",
    "hercules cluster": "M13", "great hercules cluster": "M13",
    "beehive": "M44", "beehive cluster": "M44",
    "sunflower galaxy": "M63", "black eye galaxy": "M64",
    "bodes galaxy": "M81", "bode's galaxy": "M81",
    "cigar galaxy": "M82", "owl nebula": "M97",
    "pinwheel": "M101", "pinwheel galaxy": "M101",
    "sombrero": "M104", "sombrero galaxy": "M104",
    "sculptor galaxy": "NGC 253", "pacman": "NGC 281", "pacman nebula": "NGC 281",
    "double cluster": "NGC 869",
    "rosette": "NGC 2237", "rosette nebula": "NGC 2237",
    "crescent nebula": "NGC 6888",
    "veil nebula": "NGC 6960", "western veil": "NGC 6960", "eastern veil": "NGC 6992",
    "witch's broom": "NGC 6960",
    "north america nebula": "NGC 7000", "north america": "NGC 7000",
    "helix": "NGC 7293", "helix nebula": "NGC 7293",
    "bubble nebula": "NGC 7635",
    "horsehead": "IC 434", "horsehead nebula": "IC 434",
    "elephants trunk": "IC 1396", "elephant's trunk": "IC 1396",
    "pelican": "IC 5070", "pelican nebula": "IC 5070",
    "cocoon": "IC 5146", "cocoon nebula": "IC 5146",
}

_CATALOG_RE = re.compile(
    r"^(?P<cat>M|MESSIER|NGC|IC|SH2|SH 2|C|CALDWELL)[\s\-_.]*(?P<num>\d+)", re.IGNORECASE
)
_CAT_CANON = {"MESSIER": "M", "M": "M", "NGC": "NGC", "IC": "IC",
              "SH2": "Sh2", "SH 2": "Sh2", "C": "C", "CALDWELL": "C"}


def resolve_target(raw: str) -> dict:
    """Resolve a raw target string.

    Returns ``{"canonical", "display", "kind"}`` — e.g. for input "andromeda":
    ``{"canonical": "M31", "display": "Andromeda Galaxy (M31)", "kind": "galaxy"}``.
    Unknown strings pass through cleaned but unchanged, never rejected.
    """
    cleaned = re.sub(r"\s+", " ", (raw or "").strip())
    if not cleaned:
        return {"canonical": "", "display": "(unknown)", "kind": ""}

    alias_hit = _ALIASES.get(cleaned.lower())
    if alias_hit:
        canonical = alias_hit
    else:
        m = _CATALOG_RE.match(cleaned)
        if m:
            cat = _CAT_CANON[m.group("cat").upper()]
            num = int(m.group("num"))
            canonical = f"{cat}{num}" if cat == "M" else f"{cat} {num}"
        else:
            canonical = cleaned

    name, kind = NOTABLE.get(canonical, ("", ""))
    display = f"{name} ({canonical})" if name else canonical
    return {"canonical": canonical, "display": display, "kind": kind}
