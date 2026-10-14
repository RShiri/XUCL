"""
Champions League — primary/secondary colours per club, for the PNG renderer.
Sourced from each club's official kit/crest palette. ``get_team_colors`` matches by
exact name, then case-insensitively, then accent-folded, then falls back to a neutral grey.

``WC2026_TEAM_COLORS`` is kept as an alias so the ported ``renderer.py`` imports unchanged.

Every club that has ever been in a scraped season stays here, even after relegation
(Burnley/West Ham United/Wolverhampton Wanderers went down at the end of 2025/26) — the
2022-23..2025-26 seasons' standings/PNGs still need their colours.
"""

import unicodedata

UCL_TEAM_COLORS: dict[str, dict[str, str]] = {
    "Arsenal":                {"primary": "#EF0107", "secondary": "#FFFFFF"},
    "Aston Villa":            {"primary": "#95BFE5", "secondary": "#670E36"},
    "AFC Bournemouth":        {"primary": "#DA291C", "secondary": "#000000"},
    "Brentford":              {"primary": "#E30613", "secondary": "#FBB800"},
    "Brighton & Hove Albion": {"primary": "#0057B8", "secondary": "#FFCD00"},
    "Burnley":                {"primary": "#6C1D45", "secondary": "#99D6EA"},
    "Chelsea":                {"primary": "#034694", "secondary": "#FFFFFF"},
    "Crystal Palace":         {"primary": "#1B458F", "secondary": "#C4122E"},
    "Everton":                {"primary": "#003399", "secondary": "#FFFFFF"},
    "Fulham":                 {"primary": "#000000", "secondary": "#FFFFFF"},
    "Leeds United":           {"primary": "#FFCD00", "secondary": "#1D428A"},
    "Liverpool":              {"primary": "#C8102E", "secondary": "#00B2A9"},
    "Manchester City":        {"primary": "#6CABDD", "secondary": "#1C2C5B"},
    "Manchester United":      {"primary": "#DA291C", "secondary": "#FBE122"},
    "Newcastle United":       {"primary": "#241F20", "secondary": "#FFFFFF"},
    "Nottingham Forest":      {"primary": "#DD0000", "secondary": "#FFFFFF"},
    "Sunderland":             {"primary": "#EB172B", "secondary": "#FFFFFF"},
    "Tottenham Hotspur":      {"primary": "#132257", "secondary": "#FFFFFF"},
    "West Ham United":        {"primary": "#7A263A", "secondary": "#1BB1E7"},
    "Wolverhampton Wanderers": {"primary": "#FDB913", "secondary": "#231F20"},
    # promoted for 2026/27 (replacing Burnley, West Ham United, Wolverhampton Wanderers)
    "Coventry City":          {"primary": "#059DD9", "secondary": "#FFFFFF"},
    "Hull City":              {"primary": "#F18A01", "secondary": "#000000"},
    "Ipswich Town":           {"primary": "#3A64A3", "secondary": "#FFFFFF"},
    # Champions League clubs (2022/23 onward), FotMob spellings
    "AC Milan":               {"primary": "#FB090B", "secondary": "#000000"},
    "AEK Athens":             {"primary": "#FFD400", "secondary": "#000000"},
    "Ajax":                   {"primary": "#D2122E", "secondary": "#FFFFFF"},
    "Antwerp":                {"primary": "#D50000", "secondary": "#FFFFFF"},
    "Atalanta":               {"primary": "#1E71B8", "secondary": "#000000"},
    "Athletic Club":          {"primary": "#EE2523", "secondary": "#FFFFFF"},
    "Atlético Madrid":        {"primary": "#CB3524", "secondary": "#272E61"},
    "Barcelona":              {"primary": "#A50044", "secondary": "#004D98"},
    "Bayer Leverkusen":       {"primary": "#E32221", "secondary": "#000000"},
    "Bayern München":         {"primary": "#DC052D", "secondary": "#0066B2"},
    "Benfica":                {"primary": "#E20E0E", "secondary": "#FFFFFF"},
    "Bodø/Glimt":             {"primary": "#FFD700", "secondary": "#000000"},
    "Bologna":                {"primary": "#1A2F48", "secondary": "#A21C26"},
    "Borussia Dortmund":      {"primary": "#FDE100", "secondary": "#000000"},
    "Braga":                  {"primary": "#E30613", "secondary": "#FFFFFF"},
    "Brest":                  {"primary": "#E30613", "secondary": "#FFFFFF"},
    "Celtic":                 {"primary": "#018749", "secondary": "#FFFFFF"},
    "Club Brugge":            {"primary": "#0062B1", "secondary": "#000000"},
    "Como":                   {"primary": "#1C3F94", "secondary": "#FFFFFF"},
    "Crvena Zvezda":          {"primary": "#E2001A", "secondary": "#FFFFFF"},
    "Dinamo Zagreb":          {"primary": "#0033A0", "secondary": "#FFFFFF"},
    "Eintracht Frankfurt":    {"primary": "#E1000F", "secondary": "#000000"},
    "FC Copenhagen":          {"primary": "#FFFFFF", "secondary": "#1A3B8A"},
    "FC Porto":               {"primary": "#00428C", "secondary": "#FFFFFF"},
    "Fenerbahçe":             {"primary": "#163962", "secondary": "#FFED00"},
    "Feyenoord":              {"primary": "#E1000F", "secondary": "#FFFFFF"},
    "Galatasaray":            {"primary": "#A90432", "secondary": "#FDB912"},
    "Girona":                 {"primary": "#E20E1F", "secondary": "#FFFFFF"},
    "Inter":                  {"primary": "#0068A8", "secondary": "#000000"},
    "Juventus":               {"primary": "#000000", "secondary": "#FFFFFF"},
    "Kairat Almaty":          {"primary": "#FFD200", "secondary": "#000000"},
    "LASK":                   {"primary": "#000000", "secondary": "#FFFFFF"},
    "Lazio":                  {"primary": "#87D8F7", "secondary": "#FFFFFF"},
    "Lens":                   {"primary": "#FFE500", "secondary": "#E30613"},
    "Lille":                  {"primary": "#E01E13", "secondary": "#24216A"},
    "Maccabi Haifa":          {"primary": "#00843D", "secondary": "#FFFFFF"},
    "Marseille":              {"primary": "#2FAEE0", "secondary": "#FFFFFF"},
    "Monaco":                 {"primary": "#E2001A", "secondary": "#FFFFFF"},
    "Napoli":                 {"primary": "#12A0D7", "secondary": "#FFFFFF"},
    "Olympiacos":             {"primary": "#E2001A", "secondary": "#FFFFFF"},
    "PSV Eindhoven":          {"primary": "#ED1C24", "secondary": "#FFFFFF"},
    "Pafos FC":               {"primary": "#00539F", "secondary": "#FFFFFF"},
    "Paris Saint-Germain":    {"primary": "#004170", "secondary": "#DA291C"},
    "Qarabag FK":             {"primary": "#000000", "secondary": "#FFFFFF"},
    "RB Leipzig":             {"primary": "#DD0741", "secondary": "#FFFFFF"},
    "RB Salzburg":            {"primary": "#D50032", "secondary": "#FFFFFF"},
    "Rangers":                {"primary": "#1B458F", "secondary": "#FFFFFF"},
    "Real Betis":             {"primary": "#00954C", "secondary": "#FFFFFF"},
    "Real Madrid":            {"primary": "#FEBE10", "secondary": "#00529F"},
    "Real Sociedad":          {"primary": "#0067B1", "secondary": "#FFFFFF"},
    "Roma":                   {"primary": "#8E1F2F", "secondary": "#F0BC42"},
    "Sabah FK":               {"primary": "#E2001A", "secondary": "#FFFFFF"},
    "Sevilla":                {"primary": "#D71920", "secondary": "#FFFFFF"},
    "Shakhtar Donetsk":       {"primary": "#F37021", "secondary": "#000000"},
    "Slavia Prague":          {"primary": "#E2001A", "secondary": "#FFFFFF"},
    "Slovan Bratislava":      {"primary": "#0091D5", "secondary": "#FFFFFF"},
    "Sparta Prague":          {"primary": "#A6192E", "secondary": "#FFFFFF"},
    "Sporting CP":            {"primary": "#008057", "secondary": "#FFFFFF"},
    "Sturm Graz":             {"primary": "#000000", "secondary": "#FFFFFF"},
    "Union Berlin":           {"primary": "#EB1923", "secondary": "#FFFFFF"},
    "Union Saint-Gilloise":   {"primary": "#FFD100", "secondary": "#003A8C"},
    "VfB Stuttgart":          {"primary": "#E32219", "secondary": "#FFFFFF"},
    "Viking":                 {"primary": "#00529B", "secondary": "#FFFFFF"},
    "Viktoria Plzen":         {"primary": "#E2001A", "secondary": "#00519E"},
    "Villarreal":             {"primary": "#FFE667", "secondary": "#005187"},
    "Young Boys":             {"primary": "#FFD200", "secondary": "#000000"},
    "PSV":                    {"primary": "#ED1C24", "secondary": "#FFFFFF"},
    "Porto":                  {"primary": "#00428C", "secondary": "#FFFFFF"},
    # common alias spellings from FotMob / WhoScored / Understat
    "Bournemouth":            {"primary": "#DA291C", "secondary": "#000000"},
    "Brighton":               {"primary": "#0057B8", "secondary": "#FFCD00"},
    "Man City":               {"primary": "#6CABDD", "secondary": "#1C2C5B"},
    "Man Utd":                {"primary": "#DA291C", "secondary": "#FBE122"},
    "Manchester Utd":         {"primary": "#DA291C", "secondary": "#FBE122"},
    "Newcastle":              {"primary": "#241F20", "secondary": "#FFFFFF"},
    "Nott'm Forest":          {"primary": "#DD0000", "secondary": "#FFFFFF"},
    "Spurs":                  {"primary": "#132257", "secondary": "#FFFFFF"},
    "Tottenham":              {"primary": "#132257", "secondary": "#FFFFFF"},
    "West Ham":               {"primary": "#7A263A", "secondary": "#1BB1E7"},
    "Wolves":                 {"primary": "#FDB913", "secondary": "#231F20"},
    "Leeds":                  {"primary": "#FFCD00", "secondary": "#1D428A"},
    "Ipswich":                {"primary": "#3A64A3", "secondary": "#FFFFFF"},
}

# Drop-in alias so the ported renderer.py (which imports WC2026_TEAM_COLORS) works unchanged.
WC2026_TEAM_COLORS = UCL_TEAM_COLORS


def _fold(name: str) -> str:
    """Case- and accent-insensitive lookup key: e.g. 'Nott'm Forest' variants fold together."""
    stripped = unicodedata.normalize("NFKD", (name or "").strip())
    return "".join(c for c in stripped if not unicodedata.combining(c)).casefold()


def get_team_colors(team_name: str, fallback_home: bool = True) -> dict[str, str]:
    """Return {'primary': hex, 'secondary': hex} for a team."""
    name_clean = (team_name or "").strip()
    if name_clean in UCL_TEAM_COLORS:
        return UCL_TEAM_COLORS[name_clean]
    lower = name_clean.lower()
    for k, v in UCL_TEAM_COLORS.items():
        if k.lower() == lower:
            return v
    # Accent-fold before giving up: a feed occasionally sends a diacritic variant of an
    # otherwise-known name, and a miss here silently renders the club grey in the PNGs.
    folded = _fold(name_clean)
    for k, v in UCL_TEAM_COLORS.items():
        if _fold(k) == folded:
            return v
    return {"primary": "#6b7a99" if fallback_home else "#4a5870", "secondary": "#FFFFFF"}
