"""
Weekly-file discovery for the local, cron-triggered pipeline run.

Jeff's own words (2026-11-11): "The files will be on my local computer.
I can create a directory file structure. Or the UI can find the files
that way it knows where to point to." This resolves that with a fixed
"incoming" directory Jeff drops the weekly Salesforce exports into, found
by filename PATTERN rather than an exact name — Salesforce's own exports
embed a timestamp in the filename (confirmed in the real files used for
validation this session, e.g.
"22acd1d2-All_Open_Deals-2026-11-11-19-28-26.csv"), so requiring an exact
name would break every week.

Directory layout (under POP_ENGINE_DATA_DIR, default ~/mplc_pop_engine_data):
    incoming/          <- Jeff drops/exports the weekly CSVs here, any filename
    archive/<run_date>/ <- moved here after a successful run (audit trail,
                            and keeps discovery from re-picking a stale file)
    output/<run_date>/  <- the pipeline's own per-run CSV outputs

Only two roles are required (salesforce_export, open_deals) to match
run_weekly_pipeline's own required args; the other two are optional there
too, so a missing activity/lost-deals file degrades the run rather than
blocking it.
"""

import os
import shutil
from pathlib import Path
from typing import Optional

DATA_DIR = Path(os.environ.get("POP_ENGINE_DATA_DIR", str(Path.home() / "mplc_pop_engine_data")))
INCOMING_DIR = DATA_DIR / "incoming"
ARCHIVE_DIR = DATA_DIR / "archive"
OUTPUT_DIR = DATA_DIR / "output"

REQUIRED_ROLES = ("salesforce_export", "open_deals")

# role -> filename substrings to match (case-insensitive, checked against
# the whole filename after stripping separators — see _normalize below),
# in no particular priority — first match wins among ties by picking the
# most recently modified file. Write patterns with underscores; they're
# matched against filenames however Salesforce actually spells them
# ("All Accounts-...", "All_Accounts_...", "all-accounts-..." all match
# "all_account" after normalization).
ROLE_PATTERNS = {
    "salesforce_export": ["all_account", "account_export", "accounts_export", "salesforce_export"],
    "open_deals": ["open_deal"],
    "activity_90_days": ["activit"],  # "Activities", "Activity", "90 Day(s)"
    "lost_deals_9_months": ["closed_lost", "lost_deal"],
}


def _normalize(s: str) -> str:
    """Strips spaces/underscores/hyphens so pattern matching doesn't care
    which separator a given Salesforce export actually used. Bug found
    2026-11-12 (Jeff's real exports use spaces — "All Accounts-...",
    "All Open Deals-...", "Closed Lost L9M-..." — but ROLE_PATTERNS was
    underscore-only, so every file except the one pattern with no
    separator ("activit") silently failed to match)."""
    return s.lower().replace(" ", "").replace("_", "").replace("-", "")


class DiscoveryError(Exception):
    pass


def ensure_dirs() -> None:
    for d in (INCOMING_DIR, ARCHIVE_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _find_candidates(role: str) -> list[Path]:
    patterns = [_normalize(pat) for pat in ROLE_PATTERNS[role]]
    return sorted(
        (p for p in INCOMING_DIR.glob("*.csv") if any(pat in _normalize(p.name) for pat in patterns)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def discover_weekly_files(verbose: bool = True) -> dict:
    """Returns {role: Path} for whichever of the 4 roles are found in
    incoming/. Raises DiscoveryError naming exactly which REQUIRED role(s)
    are missing, rather than silently running on stale/partial data.

    If more than one file matches a role, picks the most-recently-modified
    one but prints a warning naming every candidate — "most recent wins"
    is a real way to silently run on the wrong file if a prior week's
    export never got cleaned out of incoming/ (confirmed: caught this
    exact case testing against copies of this session's real export
    files, where two Open_Deals exports from different weeks both
    matched). archive_files() moving used files out of incoming/ after
    each run is the main mitigation; this warning covers the gap before
    that's had a chance to run (first-ever run, or a manually dropped
    extra file)."""
    ensure_dirs()
    found = {}
    missing_required = []
    for role in ROLE_PATTERNS:
        candidates = _find_candidates(role)
        if not candidates:
            if role in REQUIRED_ROLES:
                missing_required.append(role)
            continue
        found[role] = candidates[0]
        if len(candidates) > 1 and verbose:
            print(
                f"WARNING: {len(candidates)} files matched role '{role}' in "
                f"{INCOMING_DIR}: {[p.name for p in candidates]}. "
                f"Using most recently modified: {candidates[0].name}. "
                f"Clean out old exports from incoming/ to avoid this."
            )
    if missing_required:
        raise DiscoveryError(
            f"Missing required weekly file(s) in {INCOMING_DIR}: "
            f"{', '.join(missing_required)}. Drop the latest Salesforce "
            f"exports there and retry."
        )
    return found


def archive_files(files: dict, run_date: str) -> None:
    """Moves this run's input files into archive/<run_date>/ so discovery
    never re-picks a stale file next time, and there's a record of exactly
    which export produced which run."""
    dest_dir = ARCHIVE_DIR / run_date
    dest_dir.mkdir(parents=True, exist_ok=True)
    for path in files.values():
        if path and path.exists():
            shutil.move(str(path), str(dest_dir / path.name))
