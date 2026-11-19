"""
Backend wiring for the Custom Vertical Builder.

Jeff (2026-11-18): "Let's imagine I want to create a new vertical in the
app... is there a way to order steps and set an option to not run the rest
of the steps if it's decided it's a prospect" -- see
claude/Custom_Vertical_Builder_Design.md in the MPLC project for the full
design. This module is the CRUD layer on top of the CustomVertical /
CustomVerticalChannel models (models.py); the actual detection logic lives
in production/channels/{serper_image,youtube_video,website_scrape}_channel.py
and the execution loop in MPLC/verticals/custom/runner.py -- this module
never duplicates either, same separation duplicate_detection.py and
clay_import.py already use (thin DB-facing wiring, real logic elsewhere,
independently testable).

The one-time LLM config-generation call (production/channels/
config_from_description.py) is invoked from here, at channel-creation time
-- exactly once per channel, never per account, per the explicit mechanism
decision in the design doc.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from . import models

_CHANNELS_DIR = Path(__file__).resolve().parent.parent.parent / "MPLC" / "production" / "channels"
if str(_CHANNELS_DIR) not in sys.path:
    sys.path.insert(0, str(_CHANNELS_DIR))

_CUSTOM_VERTICAL_RUNNER_DIR = Path(__file__).resolve().parent.parent.parent / "MPLC" / "verticals" / "custom"
if str(_CUSTOM_VERTICAL_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_CUSTOM_VERTICAL_RUNNER_DIR))

import config_from_description  # noqa: E402

VALID_CHANNEL_TYPES = {"serper_image", "youtube_video", "website_scrape"}


class CustomVerticalError(Exception):
    """Raised for any user-facing error (not found, bad channel_type,
    duplicate key) -- main.py's endpoint handlers turn this into a 400/404,
    same pattern DuplicateDetectionError already uses."""
    pass


def _validate_config_json(channel_type: str, config_json: str) -> None:
    """Checks a config_json string has the shape runner.build_channel()
    actually requires before it's saved, rather than letting a bad
    hand-edit (typo'd JSON, a field renamed, a list where a string was
    needed) surface only at dispatch time -- where today it crashes an
    entire batch job on account #1 (runner.build_channel's json.loads
    raises a ValueError, which propagates straight up through
    build_channels()'s list comprehension in the caller's "fail fast
    before running a single account" step).

    Validates the shape, not business-level correctness (e.g. a query
    template referencing an unknown placeholder still passes -- that's
    the per-account str.format(...) skip-on-KeyError behavior already
    documented in serper_image_channel.py/youtube_video_channel.py, a
    silent skip rather than an error on purpose). All three channel types
    (per config_from_description.py's GeneratedChannelConfig) share the
    same config schema: query_templates / target_spaces / excluded_spaces,
    all lists of strings -- so one check covers add_channel's generated
    config and update_channel's hand-edited one.

    Found during the 2026-11-18 optimization pass (finding #4): this is
    the missing validation that let update_channel's config_json param
    through to the DB with zero shape checking."""
    try:
        cfg = json.loads(config_json)
    except (TypeError, json.JSONDecodeError) as e:
        raise CustomVerticalError(f"config_json is not valid JSON: {e}") from e

    if not isinstance(cfg, dict):
        raise CustomVerticalError(
            f"config_json must decode to a JSON object, got {type(cfg).__name__}"
        )

    for field in ("query_templates", "target_spaces", "excluded_spaces"):
        if field not in cfg:
            raise CustomVerticalError(f"config_json is missing required field '{field}'")
        value = cfg[field]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise CustomVerticalError(
                f"config_json field '{field}' must be a list of strings, got {value!r}"
            )


def _vertical_to_dict(v: models.CustomVertical) -> Dict[str, Any]:
    return {
        "vertical_key": v.vertical_key,
        "display_name": v.display_name,
        "match_keywords_json": v.match_keywords_json,
        "match_keywords_generated_cost": v.match_keywords_generated_cost,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "updated_at": v.updated_at.isoformat() if v.updated_at else None,
        "channels": [_channel_to_dict(c) for c in v.channels],
    }


def _channel_to_dict(c: models.CustomVerticalChannel) -> Dict[str, Any]:
    return {
        "id": c.id,
        "vertical_key": c.vertical_key,
        "step_order": c.step_order,
        "channel_type": c.channel_type,
        "enabled": c.enabled,
        "description": c.description,
        "config_json": c.config_json,
        "config_generated_cost": c.config_generated_cost,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def list_custom_verticals(db: Session) -> List[Dict[str, Any]]:
    rows = db.execute(select(models.CustomVertical)).scalars().all()
    return [_vertical_to_dict(v) for v in rows]


def get_custom_vertical(db: Session, vertical_key: str) -> Dict[str, Any]:
    v = db.get(models.CustomVertical, vertical_key)
    if v is None:
        raise CustomVerticalError(f"No custom vertical '{vertical_key}'")
    return _vertical_to_dict(v)


def create_custom_vertical(
    db: Session,
    vertical_key: str,
    display_name: str,
    reserved_keys: Optional[set] = None,
) -> Dict[str, Any]:
    """reserved_keys: the hardcoded vertical keys (healthcare/corporate/mdu)
    this custom one must not collide with. Passed in by the caller
    (main.py already imports enrichment.DISPATCHABLE_VERTICALS, so it's
    positioned to pass its keys) rather than imported from enrichment.py
    directly here, since enrichment.py already imports custom_verticals.py
    -- importing it back would be circular. Without this check, a
    collision used to resolve silently in enrichment.py's union logic
    (the hardcoded entry always wins) with no error surfaced to whoever
    created the custom vertical; found during the 2026-11-18 optimization
    pass (finding #5)."""
    if db.get(models.CustomVertical, vertical_key) is not None:
        raise CustomVerticalError(f"A custom vertical '{vertical_key}' already exists")
    if not vertical_key or not vertical_key.replace("_", "").isalnum():
        raise CustomVerticalError(
            "vertical_key must be a slug (letters, digits, underscores) -- "
            f"got '{vertical_key}'"
        )
    if reserved_keys and vertical_key in reserved_keys:
        raise CustomVerticalError(
            f"vertical_key '{vertical_key}' collides with a built-in vertical "
            f"({sorted(reserved_keys)}) -- choose a different key. A built-in "
            "vertical always wins a dispatch collision, so a custom vertical "
            "using the same key could never actually run."
        )
    v = models.CustomVertical(vertical_key=vertical_key, display_name=display_name)
    db.add(v)
    db.commit()
    db.refresh(v)
    return _vertical_to_dict(v)


def delete_custom_vertical(db: Session, vertical_key: str) -> None:
    v = db.get(models.CustomVertical, vertical_key)
    if v is None:
        raise CustomVerticalError(f"No custom vertical '{vertical_key}'")
    db.delete(v)  # cascade="all, delete-orphan" on CustomVertical.channels takes the rows with it
    db.commit()


def add_channel(
    db: Session,
    vertical_key: str,
    channel_type: str,
    description: str,
    step_order: Optional[int] = None,
    anthropic_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Creates a channel row AND runs the one-time config-generation call
    against `description`. The generation cost is recorded on the row
    (config_generated_cost) -- logged, never hidden, per CLAUDE.md's "Track
    costs" workflow item and the design doc's explicit call-out that this
    cost should be visible even though it's one-time, not per-account."""
    vertical = db.get(models.CustomVertical, vertical_key)
    if vertical is None:
        raise CustomVerticalError(f"No custom vertical '{vertical_key}'")
    if channel_type not in VALID_CHANNEL_TYPES:
        raise CustomVerticalError(
            f"Unknown channel_type '{channel_type}', expected one of {sorted(VALID_CHANNEL_TYPES)}"
        )

    if step_order is None:
        existing_max = max((c.step_order for c in vertical.channels), default=-1)
        step_order = existing_max + 1

    try:
        generated = config_from_description.generate_channel_config(
            description=description,
            channel_type=channel_type,
            anthropic_api_key=anthropic_api_key,
        )
    except ValueError as e:
        # Config generation failed (bad JSON from the model, or no API
        # key available) -- don't silently create a channel with an empty
        # config that would later raise confusingly deep inside the
        # runner; surface it here instead.
        raise CustomVerticalError(f"Config generation failed: {e}") from e

    generated_json = generated.to_json()
    # Found alongside fix #4 in the 2026-11-18 optimization pass: the
    # hand-edit path (config_json param, below) got shape validation, but
    # the LLM-generated path never did -- so a malformed model response
    # (a string where a list was expected, say) would pass straight
    # through to the DB unchecked and only surface later at dispatch time,
    # the exact failure mode fix #4 was meant to close. Same validator,
    # applied here too.
    _validate_config_json(channel_type, generated_json)

    channel = models.CustomVerticalChannel(
        vertical_key=vertical_key,
        step_order=step_order,
        channel_type=channel_type,
        enabled=True,
        description=description,
        config_json=generated_json,
        config_generated_cost=generated.cost,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return _channel_to_dict(channel)


def update_channel(
    db: Session,
    channel_id: int,
    *,
    step_order: Optional[int] = None,
    enabled: Optional[bool] = None,
    config_json: Optional[str] = None,
    regenerate_from_description: Optional[str] = None,
    anthropic_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Handles every write the Settings UI needs on one channel row:
    reorder (step_order), toggle (enabled), hand-edit the generated config
    (config_json), or regenerate it from an edited description
    (regenerate_from_description) -- the four operations
    Custom_Vertical_Builder_Design.md §6 lists for this endpoint, kept as
    one function rather than four near-duplicate ones since a UI save can
    combine any of them in one request (e.g. edit the description AND
    regenerate in one click)."""
    channel = db.get(models.CustomVerticalChannel, channel_id)
    if channel is None:
        raise CustomVerticalError(f"No channel with id {channel_id}")

    if regenerate_from_description is not None:
        try:
            generated = config_from_description.generate_channel_config(
                description=regenerate_from_description,
                channel_type=channel.channel_type,
                anthropic_api_key=anthropic_api_key,
            )
        except ValueError as e:
            raise CustomVerticalError(f"Config regeneration failed: {e}") from e
        regenerated_json = generated.to_json()
        _validate_config_json(channel.channel_type, regenerated_json)
        channel.description = regenerate_from_description
        channel.config_json = regenerated_json
        # Regeneration cost accumulates on top of the original -- it's a
        # real additional LLM call, not a replacement of the first one's
        # cost, and CLAUDE.md's QA bar requires every cost to be tracked,
        # not just the first attempt's.
        channel.config_generated_cost = (channel.config_generated_cost or 0.0) + generated.cost
    elif config_json is not None:
        _validate_config_json(channel.channel_type, config_json)
        channel.config_json = config_json

    if step_order is not None:
        channel.step_order = step_order
    if enabled is not None:
        channel.enabled = enabled

    channel.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(channel)
    return _channel_to_dict(channel)


def delete_channel(db: Session, channel_id: int) -> None:
    channel = db.get(models.CustomVerticalChannel, channel_id)
    if channel is None:
        raise CustomVerticalError(f"No channel with id {channel_id}")
    db.delete(channel)
    db.commit()


def _validate_match_keywords_json(match_keywords_json: str) -> None:
    """Same shape-validation discipline as _validate_config_json above,
    applied to match_keywords_json -- a hand-edit or a malformed LLM
    response here shouldn't surface only when pipeline_runner's matching
    pass runs against the whole account table."""
    try:
        parsed = json.loads(match_keywords_json)
    except (TypeError, json.JSONDecodeError) as e:
        raise CustomVerticalError(f"match_keywords_json is not valid JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise CustomVerticalError(
            f"match_keywords_json must decode to a JSON object, got {type(parsed).__name__}"
        )
    keywords = parsed.get("keywords")
    if keywords is None:
        raise CustomVerticalError("match_keywords_json is missing required field 'keywords'")
    if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
        raise CustomVerticalError(
            f"match_keywords_json field 'keywords' must be a list of strings, got {keywords!r}"
        )


def generate_match_keywords(
    db: Session,
    vertical_key: str,
    anthropic_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """The one-time call behind match_keywords_json. Reads every channel's
    description on this vertical (regardless of enabled/disabled -- a
    disabled channel's description still describes what the business
    looks like) and makes ONE LLM call to draft industry-match keywords,
    per Jeff's 2026-11-18 scoping answer ("one-time LLM call from channel
    descriptions, hand-editable afterward" -- same mechanism as channel
    config generation, deliberately not re-run per account or per
    channel edit)."""
    vertical = db.get(models.CustomVertical, vertical_key)
    if vertical is None:
        raise CustomVerticalError(f"No custom vertical '{vertical_key}'")

    descriptions = [c.description for c in vertical.channels if c.description]
    if not descriptions:
        raise CustomVerticalError(
            f"Custom vertical '{vertical_key}' has no channels with a description yet -- "
            "add a channel first."
        )

    try:
        generated = config_from_description.generate_match_keywords(
            display_name=vertical.display_name,
            channel_descriptions=descriptions,
            anthropic_api_key=anthropic_api_key,
        )
    except ValueError as e:
        raise CustomVerticalError(f"Match-keyword generation failed: {e}") from e

    generated_json = generated.to_json()
    _validate_match_keywords_json(generated_json)  # defense in depth, same lesson as fix #4/#4-extension

    vertical.match_keywords_json = generated_json
    vertical.match_keywords_generated_cost = (vertical.match_keywords_generated_cost or 0.0) + generated.cost
    vertical.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(vertical)
    return _vertical_to_dict(vertical)


def update_match_keywords(db: Session, vertical_key: str, match_keywords_json: str) -> Dict[str, Any]:
    """Hand-edit path for match_keywords_json -- same split as
    update_channel's config_json param vs. regenerate_from_description."""
    vertical = db.get(models.CustomVertical, vertical_key)
    if vertical is None:
        raise CustomVerticalError(f"No custom vertical '{vertical_key}'")
    _validate_match_keywords_json(match_keywords_json)
    vertical.match_keywords_json = match_keywords_json
    vertical.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(vertical)
    return _vertical_to_dict(vertical)


def dispatchable_custom_verticals(db: Session) -> Dict[str, str]:
    """vertical_key -> display_name for every custom vertical, in the same
    shape as enrichment.DISPATCHABLE_VERTICALS, so main.py's
    /enrichment/verticals endpoint can union the two (design doc §6)."""
    rows = db.execute(select(models.CustomVertical)).scalars().all()
    return {v.vertical_key: v.display_name for v in rows}


# ---------------------------------------------------------------------------
# Custom-vertical account matching -- answers Jeff's 2026-11-18 follow-up:
# "when we create a vertical, does it map to the correct pipeline post-
# Step-1 (safe to distribute)?" Deliberately NOT a change to Stage B's
# classifier (industry_reclassifier.py) -- that's a fixed, already-
# validated 7-category taxonomy with no notion of custom verticals, and
# teaching it about them would mean re-validating tested infra. This is a
# separate, additive tagging pass writing to its own table
# (CustomVerticalMatch), run automatically right after Stage B in the
# weekly pipeline (pipeline_runner.match_custom_verticals) and also
# on-demand (POST /custom-verticals/rematch, Settings' "Re-match now").
# ---------------------------------------------------------------------------

# Same SQL-variable-budget chunking pipeline_runner.py uses for bulk
# inserts (SQLite caps bound variables per statement). CustomVerticalMatch
# writes 4 columns (account_id, vertical_key, run_date, matched_keyword),
# so a 900-variable budget is a chunk size of 225 rows.
_MATCH_VARIABLE_BUDGET = 900
_MATCH_INSERT_COLUMNS = 4


def _match_chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def match_accounts_to_custom_verticals(db: Session, run_date: str) -> Dict[str, int]:
    """For every custom vertical with match_keywords_json populated, scans
    every account that is 'safe to distribute' on `run_date` (an
    EligibilityRun row with excluded=False) and checks a free,
    case-insensitive substring match of each keyword against that
    account's industry text and account_name. A match writes a row to
    CustomVerticalMatch (upserted on (account_id, vertical_key, run_date),
    so re-running the same run_date is idempotent, same convention as
    classification_runs/segmentation_runs). Returns {vertical_key: match_count}
    for whichever UI triggered this (the weekly pipeline summary, or the
    "Re-match now" button's response) to show.

    Deliberately does NOT remove a previously-matched row that no longer
    matches on a later run of the SAME run_date -- an upsert only adds or
    refreshes matches, it never deletes, mirroring the append-only,
    never-destructive convention every other *_runs table in this schema
    already follows. A genuinely stale match from an OLDER run_date simply
    isn't returned by a query scoped to the current run_date (see
    queries.py's custom-vertical filter branch)."""
    verticals = (
        db.execute(select(models.CustomVertical).where(models.CustomVertical.match_keywords_json.is_not(None)))
        .scalars()
        .all()
    )
    if not verticals:
        return {}

    # Parse each vertical's keywords once, not per account -- same
    # "don't redo per-account work that doesn't change per account"
    # principle as this session's runner.build_channels() fix.
    vertical_keywords: Dict[str, List[str]] = {}
    for v in verticals:
        try:
            parsed = json.loads(v.match_keywords_json)
            keywords = parsed.get("keywords", [])
        except (TypeError, json.JSONDecodeError):
            # A malformed match_keywords_json shouldn't crash the whole
            # matching pass for every OTHER vertical -- skip just this
            # one and let it surface next time Jeff edits/regenerates it
            # (both paths are shape-validated going forward; this only
            # protects against a row written before that validation
            # existed, or hand-edited directly in the DB).
            continue
        if keywords:
            vertical_keywords[v.vertical_key] = [k.lower() for k in keywords if k]

    if not vertical_keywords:
        return {}

    safe_accounts = db.execute(
        select(models.Account.account_id, models.Account.account_name, models.Account.industry)
        .join(
            models.EligibilityRun,
            and_(
                models.EligibilityRun.account_id == models.Account.account_id,
                models.EligibilityRun.run_date == run_date,
                models.EligibilityRun.excluded.is_(False),
            ),
        )
    ).all()

    match_counts: Dict[str, int] = {k: 0 for k in vertical_keywords}
    rows_to_insert: List[Dict[str, Any]] = []
    for account_id, account_name, industry in safe_accounts:
        haystack = f"{account_name or ''} {industry or ''}".lower()
        if not haystack.strip():
            continue
        for vertical_key, keywords in vertical_keywords.items():
            matched_keyword = next((kw for kw in keywords if kw in haystack), None)
            if matched_keyword is not None:
                match_counts[vertical_key] += 1
                rows_to_insert.append({
                    "account_id": account_id,
                    "vertical_key": vertical_key,
                    "run_date": run_date,
                    "matched_keyword": matched_keyword,
                })

    if not rows_to_insert:
        return match_counts

    table = models.CustomVerticalMatch.__table__
    chunk_size = max(1, _MATCH_VARIABLE_BUDGET // _MATCH_INSERT_COLUMNS)
    for chunk in _match_chunks(rows_to_insert, chunk_size):
        stmt = sqlite_insert(table).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["account_id", "vertical_key", "run_date"],
            set_={"matched_keyword": stmt.excluded.matched_keyword},
        )
        db.execute(stmt)
    db.commit()

    return match_counts
