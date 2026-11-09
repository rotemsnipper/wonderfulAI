"""Resolve an airport code, name or city to airport code(s) without guessing.

Order: exact code, then name and city words. Abbreviations and nicknames are not expanded here: a
not_found result tells the model to retry with the full name. When several
airports match, nothing is picked: the user is asked to choose from the largest MAX_CHOICES matches, listed
by 12-month passengers, largest first. Only covered airports are offered when any covered airport matches.
"""
import re

from backend.tools.store import Store

NOISE_WORDS = {"airport", "airports", "international", "intl", "intl.", "the", "regional", "municipal", "of", "in", "at"}
MAX_CHOICES = 3
# A query this short is an abbreviation, not a code (codes have three letters); matching it against name
# words gives confident wrong answers ("LA" matched Durango-La Plata).
MIN_WORD_QUERY = 3
RETRY_HINT = ("If the query was an abbreviation or nickname, call resolve_airport again with the full city or "
              "airport name; ask the user only if that also finds nothing.")


def _words(text: str) -> list[str]:
    return [w for w in re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split() if w not in NOISE_WORDS]


class Resolver:
    """Uses the store's own settings unless others are passed (tests)."""

    def __init__(self, store: Store, settings: dict | None = None):
        settings = store.settings if settings is None else settings
        self.threshold = int(settings["universe_min_passengers_12m"])
        self.volume = store.months("current").groupby("code")["passengers"].sum().to_dict()
        self.airports = store.airports.set_index("code")
        self.codes = set(self.airports.index)
        self.vocab: dict[str, set[str]] = {}
        for code, row in self.airports.iterrows():
            for w in _words(f"{row['name']} {row['city']}"):
                self.vocab.setdefault(w, set()).add(code)

    def _candidate(self, code: str) -> dict:
        row = self.airports.loc[code]
        return {
            "code": code, "name": row["name"], "city": row["city"], "state": row["state"],
            "passengers_12m": float(self.volume.get(code, 0)), "in_universe": bool(row["in_universe"]),
        }

    def _by_volume(self, codes) -> list[str]:
        return sorted(codes, key=lambda c: (-self.volume.get(c, 0), c))

    def _result(self, query: str, status: str, codes: list[str], **extra) -> dict:
        out = {
            "query": query, "status": status, "code": None, "candidates": [self._candidate(c) for c in codes],
            "ask": None, "message": None,
        }
        out.update(extra)
        return out

    def _resolved(self, query: str, code: str) -> dict:
        extra = {"code": code}
        if not self.airports.loc[code, "in_universe"]:
            extra["status_detail"] = "not_covered"
            extra["message"] = (f"{code} is below the covered set (airports with at least {self.threshold:,} "
                                "passengers in the last 12 months); it has no score.")
        return self._result(query, "resolved", [code], **extra)

    def _choose(self, query: str, codes) -> dict:
        codes = [c for c in dict.fromkeys(codes) if c in self.codes]
        if not codes:
            return self._not_found(query)
        covered = [c for c in codes if self.airports.loc[c, "in_universe"]]
        codes = covered or codes  # small uncovered fields are only offered when nothing covered matches
        if len(codes) == 1:
            return self._resolved(query, codes[0])
        ordered = self._by_volume(codes)
        shown = ordered[:MAX_CHOICES]
        names = "; ".join(f"{c} ({self.airports.loc[c, 'name']}, {self.airports.loc[c, 'state']})" for c in shown)
        return self._result(query, "ambiguous", shown, more_matches=len(ordered) - len(shown),
                            ask=f"Which airport do you mean by '{query}': {names}?")

    def _not_found(self, query: str) -> dict:
        return self._result(query, "not_found", [], message=f"No covered airport matches '{query}'.",
                            ask="Please give the airport code or the full airport name.", retry_hint=RETRY_HINT)

    def resolve(self, query: str) -> dict:
        raw = (query or "").strip()
        if not raw:
            return self._not_found(raw)
        up = raw.upper()
        if re.fullmatch(r"[A-Za-z]{3}", raw) and up in self.codes:
            return self._resolved(raw, up)
        words = _words(raw)
        if words and len("".join(words)) >= MIN_WORD_QUERY:
            sets = [self.vocab.get(w, set()) for w in words]
            matched = set.intersection(*sets) if all(sets) else set()
            if matched:
                return self._choose(raw, matched)
        return self._not_found(raw)


def resolve_airport(query: str, store: Store, settings: dict | None = None) -> dict:
    return Resolver(store, settings).resolve(query)
