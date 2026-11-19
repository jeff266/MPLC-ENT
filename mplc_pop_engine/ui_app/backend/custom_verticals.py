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

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select
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


def _vertical_to_dict(v: models.CustomVertical) -> Dict[str, Any]:
    return {
        "vertical_key": v.vertical_key,
        "display_name": v.display_name,
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


def create_custom_vertical(db: Session, vertical_key: str, display_name: str) -> Dict[str, Any]:
    if db.get(models.CustomVertical, vertical_key) is not None:
        raise CustomVerticalError(f"A custom vertical '{vertical_key}' already exists")
    if not vertical_key or not vertical_key.replace("_", "").isalnum():
        raise CustomVerticalError(
            "vertical_key must be a slug (letters, digits, underscores) -- "
            f"got '{vertical_key}'"
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

    channel = models.CustomVerticalChannel(
        vertical_key=vertical_key,
        step_order=step_order,
        channel_type=channel_type,
        enabled=True,
        description=description,
        config_json=generated.to_json(),
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
        channel.description = regenerate_from_description
        channel.config_json = generated.to_json()
        # Regeneration cost accumulates on top of the original -- it's a
        # real additional LLM call, not a replacement of the first one's
        # cost, and CLAUDE.md's QA bar requires every cost to be tracked,
        # not just the first attempt's.
        channel.config_generated_cost = (channel.config_generated_cost or 0.0) + generated.cost
    elif config_json is not None:
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


def dispatchable_custom_verticals(db: Session) -> Dict[str, str]:
    """vertical_key -> display_name for every custom vertical, in the same
    shape as enrichment.DISPATCHABLE_VERTICALS, so main.py's
    /enrichment/verticals endpoint can union the two (design doc §6)."""
    rows = db.execute(select(models.CustomVertical)).scalars().all()
    return {v.vertical_key: v.display_name for v in rows}
