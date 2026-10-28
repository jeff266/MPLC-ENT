"""
Phase 0 — Industry Re-classifier

Corrects Salesforce industry labels before vertical routing using:
  Tier 1: Regex on account name (zero cost, deterministic)
  Tier 2: Claude Haiku (cheap, ~$0.0002/account — opt-in via use_llm=True)

Results are persisted in vertical_corrections.db so each account is only
classified once. Re-running the same CSV is O(cache hits) for known accounts.
Force re-classification on a single account with classify(..., force=True),
or the whole batch with reclassify_batch(..., force=True).

Phase 0 order:
  Salesforce CSV export
    → Step 1: EDGAR join / employee count
    → Step 2: ROE segmentation
    → Step 3a: THIS MODULE — industry label correction     ← here
    → Step 3b: Vertical router (routes corrected industry)
    → Step 4+: Vertical detection pipelines
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Canonical Salesforce industry labels (must match INDUSTRY_ROUTE_MAP keys)
# ---------------------------------------------------------------------------
V_RELIGIOUS   = "Religious Institutions"
V_EDUCATION   = "Education"
V_HEALTHCARE  = "Health Care Services"
V_AUTO        = "Auto Dealerships"
V_MDU         = "Multi-Dwelling Units"
V_CORPORATE   = "Corporations"
V_RESTAURANTS = "Bars, Restaurants"

# ---------------------------------------------------------------------------
# Tier-1 regex rules
# Rules are evaluated in order; the FIRST match wins.
# Only include patterns with near-zero ambiguity — edge cases go to LLM tier.
# ---------------------------------------------------------------------------

_RULES: list[tuple[re.Pattern, str]] = []


def _add(patterns: list[str], vertical: str) -> None:
    for p in patterns:
        _RULES.append((re.compile(p, re.IGNORECASE), vertical))


_add([
    # -----------------------------------------------------------------------
    # RELIGIOUS — words that almost exclusively appear in religious org names
    # -----------------------------------------------------------------------
    r"\bchurch(?:es)?\b",
    r"\bfellowship\b",
    r"\bchapel\b",
    r"\bcathedral\b",
    r"\bparish\b",
    r"\bministr(?:y|ies)\b",
    r"\bcongregation(?:al)?\b",
    r"\bbaptist\b",
    r"\bpresbyterian\b",
    r"\bmethodist\b",
    r"\bepiscop(?:al|alian)?\b",
    r"\blutheran?\b",
    r"\b(?:roman\s+)?catholic\s+(?:church|parish|cathedral|diocese|archdiocese)\b",
    r"\bseventh[-\s]day\s+adventist\b",
    r"\bassembly\s+of\s+god\b",
    r"\bbrethren\b",
    r"\bmennonite\b",
    r"\bmosque\b",
    r"\bsynagogue\b",
    r"\bmasjid\b",
    r"\bpentecostal\b",
    r"\bapostolic\b",
    r"\bnazarene\b",
    r"\bevangelical\b",
    r"\bchurch\s+of\s+(?:god|christ|the\s+nazarene|the\s+brethren)\b",
    r"\borthodox\s+(?:church|christian)\b",
    r"\breformed\s+church\b",
    r"\bkingdom\s+hall\b",           # Jehovah's Witnesses
    r"\bfriends\s+(?:church|meeting)\b",   # Quakers
    r"\bumc\b",                       # United Methodist Church abbreviation
    r"\bame\s+(?:church|zion)\b",     # African Methodist Episcopal
    r"\bsda\s+(?:church|fellowship)\b",    # Seventh-day Adventist abbreviation
    r"\bdisciples\s+of\s+christ\b",
    r"\bunited\s+church\s+of\s+christ\b",
], V_RELIGIOUS)

_add([
    # -----------------------------------------------------------------------
    # EDUCATION — words that nearly always signal an educational institution
    # "college" and "school" alone are kept to catch the common case;
    # they could collide with "Culinary Institute" etc. but in MPLC's customer
    # base the false-positive rate is acceptable.
    # -----------------------------------------------------------------------
    r"\belementary\b",
    r"\bhigh\s+school\b",
    r"\bmiddle\s+school\b",
    r"\bjunior\s+high\b",
    r"\bschool\s+district\b",
    r"\buniversity\b",
    r"\bcommunity\s+college\b",
    r"\bstate\s+college\b",
    r"\bchristian\s+(?:school|academy)\b",
    r"\bcatholic\s+(?:school|academy|high|prep)\b",
    r"\bpreschool\b",
    r"\bkindergarten\b",
    r"\bpta\b",              # Parent Teacher Association
    r"\bptsa\b",             # Parent Teacher Student Association
    r"\bptg\b",              # Parent Teacher Group
    r"\bmontessori\b",
    r"\b(?:preparatory|prep)\s+(?:school|academy)\b",
    r"\blearning\s+academy\b",
    r"\bstem\s+(?:school|academy)\b",
], V_EDUCATION)

_add([
    # -----------------------------------------------------------------------
    # HEALTHCARE — avoid "medical spa", "medical supplies" (borderline);
    # keep only facilities with physical waiting/common areas
    # -----------------------------------------------------------------------
    r"\bhospital\b",
    r"\bmedical\s+center\b",
    r"\bhealth\s+(?:system|network|campus)\b",
    r"\burgent\s+care\b",
    r"\bchiropractic\b",
    r"\borthopedic\b",
    r"\bnursing\s+(?:home|facility|center)\b",
    r"\brehabilitation\s+center\b",
    r"\bphysical\s+therapy\b",
    r"\bmental\s+health\s+(?:center|clinic|services)\b",
    r"\bdialysis\s+center\b",
    r"\bcancer\s+center\b",
], V_HEALTHCARE)

_add([
    # -----------------------------------------------------------------------
    # AUTO DEALERSHIPS — brand + dealership qualifier avoids collisions
    # -----------------------------------------------------------------------
    r"\bauto\s+(?:group|mall|plaza|nation|park|world|center|gallery)\b",
    r"\bcar\s+dealer(?:ship)?\b",
    r"\bauto\s+dealer(?:ship)?\b",
    r"\bused\s+cars?\b",
    r"\bpre[-\s]owned\s+(?:vehicles?|cars?|autos?)\b",
    # Major brand + local-market qualifier
    (
        r"\b(?:ford|toyota|honda|chevrolet|chevy|nissan|hyundai|kia|subaru|jeep|"
        r"dodge|chrysler|volkswagen|bmw|mercedes[-\s]?benz|audi|lexus|acura|infiniti|"
        r"cadillac|buick|gmc|volvo|mazda|mitsubishi|lincoln|porsche|landrover|"
        r"land\s+rover|jaguar|genesis|ram|fiat|alfa\s+romeo)\s+"
        r"(?:of\s+\w[\w\s]{1,20}|dealership|auto|motors|direct|sales)\b"
    ),
], V_AUTO)

_add([
    # -----------------------------------------------------------------------
    # MDU / LUXURY APARTMENTS — common-area TVs are the evidence target
    # -----------------------------------------------------------------------
    r"\bapartments?\s+(?:community|at\b|of\b|homes)\b",
    r"\bluxury\s+(?:apartments?|living|residences?|flats?)\b",
    r"\bassisted\s+living\b",
    r"\b(?:senior|independent)\s+living\b",
    r"\bretirement\s+(?:community|village|resort)\b",
    r"\bmulti[-\s]family\s+(?:community|residence|housing)\b",
], V_MDU)

_add([
    # -----------------------------------------------------------------------
    # RESTAURANTS / BARS — unambiguous food-service terms
    # -----------------------------------------------------------------------
    r"\brestaurant\b",
    r"\bsteakhouse\b",
    r"\bpizzeria\b",
    r"\bbrewpub\b",
    r"\btaproom\b",
    r"\bbar\s+(?:&|and)\s+grill\b",
    r"\bbistro\b",
], V_RESTAURANTS)


# ---------------------------------------------------------------------------
# Salesforce industry → canonical vertical (for confirming matches)
# Same keys as INDUSTRY_ROUTE_MAP; used to detect genuine corrections.
# ---------------------------------------------------------------------------
_SF_TO_CANONICAL: dict[str, str] = {
    "Religious Institutions": V_RELIGIOUS,
    "Churches":               V_RELIGIOUS,
    "Education":              V_EDUCATION,
    "Schools":                V_EDUCATION,
    "Health Care Services":   V_HEALTHCARE,
    "Hospitals":              V_HEALTHCARE,
    "Doctors":                V_HEALTHCARE,
    "Medical":                V_HEALTHCARE,
    "Auto Dealers":           V_AUTO,
    "Auto Dealerships":       V_AUTO,
    "Multi-Dwelling Units":   V_MDU,
    "Communal Living Facilities": V_MDU,
    "Seniors":                V_MDU,
    "Bars, Restaurants":      V_RESTAURANTS,
    "Restaurants, Clubs, Pubs": V_RESTAURANTS,
    "Corporations":           V_CORPORATE,
    "Commercial Establishments & Waiting Areas": V_CORPORATE,
    "Activity Centers":       V_CORPORATE,
}


# ---------------------------------------------------------------------------
# DB / cache
# ---------------------------------------------------------------------------

_DEFAULT_DB = "vertical_corrections.db"


class VerticalReclassifier:
    """
    Corrects Salesforce industry labels before vertical routing.

    Usage::
        rc = VerticalReclassifier()
        stats = rc.reclassify_batch(accounts)
        rc.close()

    After reclassify_batch():
    - account["industry"] holds the corrected value
    - account["_original_industry"] preserves the original Salesforce value
    - account["_industry_corrected"] is True when a correction was made
    - account["_industry_reason"] explains why

    Re-running on the same CSV is fast: already-classified accounts are served
    from the SQLite cache without re-running regex or LLM.
    """

    def __init__(self, db_path: str = _DEFAULT_DB):
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS vertical_corrections (
                account_key          TEXT PRIMARY KEY,
                account_name         TEXT NOT NULL,
                state                TEXT NOT NULL DEFAULT '',
                salesforce_industry  TEXT NOT NULL DEFAULT '',
                corrected_industry   TEXT NOT NULL,
                was_corrected        INTEGER NOT NULL DEFAULT 0,
                confidence           TEXT NOT NULL,
                method               TEXT NOT NULL,
                reason               TEXT,
                classified_at        TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_vc_name
                ON vertical_corrections (account_name);
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Cache key
    # ------------------------------------------------------------------

    @staticmethod
    def _key(account_name: str, state: str) -> str:
        raw = f"{account_name.lower().strip()}|{state.lower().strip()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(
        self,
        account_name: str,
        state: str,
        salesforce_industry: str,
        *,
        use_llm: bool = False,
        force: bool = False,
    ) -> dict:
        """
        Return the correct vertical for this account.

        Keys in the returned dict:
            corrected_industry  str   — vertical label to use for routing
            salesforce_industry str   — original Salesforce value
            was_corrected       bool  — True if we overrode Salesforce
            confidence          str   — 'high' | 'medium' | 'low' | 'passthrough'
            method              str   — 'regex' | 'llm' | 'passthrough'
            reason              str   — human-readable explanation
            _from_cache         bool  — True if result came from DB
        """
        key = self._key(account_name, state)

        # --- Cache check ---
        if not force:
            row = self._conn.execute(
                "SELECT * FROM vertical_corrections WHERE account_key = ?", (key,)
            ).fetchone()
            if row:
                return {
                    "corrected_industry":  row["corrected_industry"],
                    "salesforce_industry": row["salesforce_industry"],
                    "was_corrected":       bool(row["was_corrected"]),
                    "confidence":          row["confidence"],
                    "method":              row["method"],
                    "reason":              row["reason"],
                    "_from_cache":         True,
                }

        # --- Tier 1: regex ---
        result = self._classify_regex(account_name, salesforce_industry)

        # --- Tier 2: LLM (opt-in, only for low-confidence cases) ---
        if result["confidence"] == "low" and use_llm:
            result = self._classify_llm(account_name, state, salesforce_industry)

        # --- Persist ---
        self._conn.execute("""
            INSERT OR REPLACE INTO vertical_corrections
                (account_key, account_name, state, salesforce_industry,
                 corrected_industry, was_corrected, confidence, method,
                 reason, classified_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            key,
            account_name,
            state,
            salesforce_industry,
            result["corrected_industry"],
            int(result["was_corrected"]),
            result["confidence"],
            result["method"],
            result["reason"],
            datetime.now(timezone.utc).isoformat(),
        ))
        self._conn.commit()

        result["_from_cache"] = False
        return result

    def reclassify_batch(
        self,
        accounts: list[dict],
        *,
        use_llm: bool = False,
        force: bool = False,
    ) -> dict:
        """
        Reclassify all accounts in-place.

        Modifies:
            account["industry"]            → corrected vertical label
            account["_original_industry"]  → original Salesforce value
            account["_industry_corrected"] → True if corrected
            account["_industry_reason"]    → explanation string

        Returns stats dict:
            total        int — accounts processed
            from_cache   int — served from DB (skipped re-classification)
            corrected    int — industry label changed
            passthrough  int — label kept as-is
        """
        stats = {"total": 0, "from_cache": 0, "corrected": 0, "passthrough": 0}

        for account in accounts:
            name  = account.get("account_name", "")
            state = account.get("state", "") or ""
            orig  = (account.get("industry", "") or "").strip()

            result = self.classify(name, state, orig, use_llm=use_llm, force=force)

            account["_original_industry"]  = orig
            account["_industry_corrected"] = result["was_corrected"]
            account["_industry_reason"]    = result["reason"]
            account["_industry_confidence"] = result["confidence"]

            if result["was_corrected"]:
                account["industry"] = result["corrected_industry"]
                stats["corrected"] += 1
            else:
                stats["passthrough"] += 1

            stats["total"] += 1
            if result.get("_from_cache"):
                stats["from_cache"] += 1

        return stats

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Tier 1: regex
    # ------------------------------------------------------------------

    def _classify_regex(
        self, account_name: str, salesforce_industry: str
    ) -> dict:
        sf_canonical = _SF_TO_CANONICAL.get(salesforce_industry)

        for pattern, vertical in _RULES:
            m = pattern.search(account_name)
            if m:
                matched_token = m.group(0)
                was_corrected = (vertical != sf_canonical) if sf_canonical else bool(salesforce_industry)

                if was_corrected:
                    reason = (
                        f'name contains "{matched_token}" → {vertical}'
                        f' (Salesforce said: {salesforce_industry!r})'
                    )
                else:
                    reason = f'name confirms "{matched_token}" → {vertical}'

                return {
                    "corrected_industry": vertical,
                    "salesforce_industry": salesforce_industry,
                    "was_corrected": was_corrected,
                    "confidence": "high",
                    "method": "regex",
                    "reason": reason,
                }

        # No regex hit — trust Salesforce
        return {
            "corrected_industry": salesforce_industry or "Other",
            "salesforce_industry": salesforce_industry,
            "was_corrected": False,
            "confidence": "low" if not salesforce_industry else "passthrough",
            "method": "passthrough",
            "reason": "no regex match; Salesforce label retained",
        }

    # ------------------------------------------------------------------
    # Tier 2: Claude Haiku (opt-in)
    # ------------------------------------------------------------------

    def _classify_llm(
        self, account_name: str, state: str, salesforce_industry: str
    ) -> dict:
        try:
            import anthropic
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent))
            import config

            client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

            vertical_choices = (
                "Religious Institutions | Education | Health Care Services | "
                "Auto Dealerships | Multi-Dwelling Units | Bars, Restaurants | "
                "Corporations | Other"
            )
            prompt = (
                f"Account name: {account_name!r}  State: {state}\n"
                f"Salesforce industry: {salesforce_industry!r}\n\n"
                "Based ONLY on the account name, pick the most likely vertical:\n"
                f"{vertical_choices}\n\n"
                'Reply with ONLY: {"vertical":"<choice>","confidence":"high"|"medium"|"low","reason":"<one sentence>"}'
            )

            resp = client.messages.create(
                model="claude-haiku-5-5",
                max_tokens=120,
                messages=[{"role": "user", "content": prompt}],
            )

            data = json.loads(resp.content[0].text.strip())
            detected = data.get("vertical", salesforce_industry)
            sf_canonical = _SF_TO_CANONICAL.get(salesforce_industry)
            was_corrected = (detected != sf_canonical) if sf_canonical else bool(salesforce_industry)

            return {
                "corrected_industry": detected,
                "salesforce_industry": salesforce_industry,
                "was_corrected": was_corrected,
                "confidence": data.get("confidence", "medium"),
                "method": "llm",
                "reason": data.get("reason", "LLM classification"),
            }

        except Exception as exc:
            return {
                "corrected_industry": salesforce_industry or "Other",
                "salesforce_industry": salesforce_industry,
                "was_corrected": False,
                "confidence": "low",
                "method": "passthrough",
                "reason": f"LLM unavailable ({exc}); Salesforce label retained",
            }


# ---------------------------------------------------------------------------
# CLI — audit / one-off classification
# ---------------------------------------------------------------------------

def _cli() -> None:
    import argparse
    import csv

    parser = argparse.ArgumentParser(
        description="Industry re-classifier — correct Salesforce vertical labels"
    )
    parser.add_argument("csv_path", help="Accounts CSV (must have account_name, state, industry)")
    parser.add_argument("--db",       default=_DEFAULT_DB, help="SQLite cache path")
    parser.add_argument("--use-llm",  action="store_true", help="Enable Tier-2 LLM for ambiguous names")
    parser.add_argument("--force",    action="store_true", help="Re-classify even if cached")
    parser.add_argument("--show-all", action="store_true", help="Print all accounts, not just corrections")
    args = parser.parse_args()

    with open(args.csv_path, newline="", encoding="utf-8-sig") as f:
        accounts = [
            {k.strip().lower().replace(" ", "_"): v for k, v in row.items()}
            for row in csv.DictReader(f)
        ]

    rc = VerticalReclassifier(db_path=args.db)
    stats = rc.reclassify_batch(accounts, use_llm=args.use_llm, force=args.force)
    rc.close()

    print(f"\nRe-classification summary")
    print(f"  Total:       {stats['total']}")
    print(f"  From cache:  {stats['from_cache']}")
    print(f"  Corrected:   {stats['corrected']}")
    print(f"  Passthrough: {stats['passthrough']}")

    corrections = [a for a in accounts if a.get("_industry_corrected")]
    if corrections:
        print(f"\n{'Account':<45} {'Original':<28} {'Corrected':<28} Reason")
        print("-" * 130)
        for a in corrections:
            print(
                f"  {a['account_name']:<43} "
                f"  {a['_original_industry']:<26} "
                f"  {a['industry']:<26} "
                f"  {a['_industry_reason']}"
            )
    elif not args.show_all:
        print("\nNo corrections made (all Salesforce labels confirmed by regex).")

    if args.show_all:
        print(f"\n{'Account':<45} {'Salesforce':<28} {'Result':<28} Method")
        print("-" * 130)
        for a in accounts:
            mark = "✓" if a.get("_industry_corrected") else " "
            print(
                f"{mark} {a['account_name']:<43} "
                f"  {a['_original_industry']:<26} "
                f"  {a['industry']:<26} "
                f"  {a.get('_industry_confidence','')}/{a.get('_industry_method','')}"
            )


if __name__ == "__main__":
    _cli()
