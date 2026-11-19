#!/usr/bin/env python3
"""
CLI worker entry point for custom (config-driven) verticals.

Jeff asked (2026-11-18 follow-up): a custom vertical shows up in Step 2's
vertical picker, but dispatching it fails -- enrichment.py's dispatch_job()
gated on the hardcoded DISPATCHABLE_VERTICALS dict and shelled out to
unified_worker.py, which only knows healthcare/corporate/mdu/hotels. This
script is the other half of that fix: enrichment.py now shells out to
THIS script instead, for any vertical_key that's a row in the
custom_verticals table, while unified_worker.py and the three hardcoded
verticals stay completely untouched (same "leave production alone" rule
Custom_Vertical_Builder_Design.md §1 already committed to).

Deliberately reuses unified_worker.py's SupabaseWriter class (imported,
not copied) so a custom vertical's job writes to the exact same
account_enrichment_results / worker_heartbeat tables the same way --
Step 3's Pipeline Monitor (enrichment.job_progress(), which reads purely
from Supabase + PID liveness) needs zero changes to work for a custom
vertical's jobs too.

CLI shape mirrors unified_worker.py's (same flags enrichment.py's
dispatch_job() already builds a Popen command with), so dispatch_job only
needs to pick which script to invoke, not build a different command line.
"""

import csv
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

_WORKERS_DIR = Path(__file__).resolve().parent.parent.parent / "production" / "workers"
sys.path.insert(0, str(_WORKERS_DIR))
from unified_worker import SupabaseWriter, PSYCOPG2_AVAILABLE  # noqa: E402

_UI_APP_DIR = Path(__file__).resolve().parent.parent.parent.parent / "ui_app"
sys.path.insert(0, str(_UI_APP_DIR))
from backend.db import SessionLocal  # noqa: E402
from backend import models  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import runner  # noqa: E402
from base import AccountContext  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("custom_vertical_worker")

VERSION = "2026-11-18-custom-vertical-builder"


def _load_channel_rows(vertical_key: str) -> list[runner.ChannelConfigRow]:
    """Reads the vertical's enabled channels straight from the same
    SQLite DB the Settings-tab UI writes to (db.py's POP_ENGINE_DB_URL) --
    no API call, this script runs as a local subprocess alongside that
    backend, same way unified_worker.py reads its batch CSV directly off
    disk rather than through the API."""
    db = SessionLocal()
    try:
        vertical = db.get(models.CustomVertical, vertical_key)
        if vertical is None:
            raise ValueError(f"No custom vertical '{vertical_key}' found in the UI's database.")
        rows = [
            runner.ChannelConfigRow(
                step_order=c.step_order,
                channel_type=c.channel_type,
                enabled=c.enabled,
                config_json=c.config_json,
            )
            for c in vertical.channels
        ]
        if not any(r.enabled for r in rows):
            raise ValueError(
                f"Custom vertical '{vertical_key}' has no enabled channel steps -- "
                "nothing would ever run. Add or enable a step in Settings first."
            )
        return rows
    finally:
        db.close()


def _record_to_context(record: dict, vertical_key: str) -> AccountContext:
    """batch CSV columns, per enrichment.py's dispatch_job(): account_id,
    account_name, website, operating_market, segment, state, country,
    industry. (state/country/industry added 2026-11-18 -- see
    dispatch_job()'s comment: they were being queried from the Account
    table and then silently dropped before reaching this CSV, which meant
    entity_verification.verify_entity_match()'s geographic-distance and
    category-incompatibility layers could never fire for a custom
    vertical, and {state}/{country} query-template placeholders silently
    formatted to blank strings instead of real values -- NOT skipped, as
    a previous version of this comment incorrectly claimed: str.format()
    happily substitutes AccountContext's default empty string, it doesn't
    raise. No `city` column -- models.Account has no city field at all,
    so that one genuinely has no upstream source to propagate and stays
    unset; a query template using {city} still formats, just always
    blank.)"""
    return AccountContext(
        account_name=record.get("account_name", ""),
        website=record.get("website", ""),
        operating_market=record.get("operating_market") or "United States",
        segment=record.get("segment", ""),
        state=record.get("state", ""),
        country=record.get("country") or "United States",
        industry=record.get("industry") or None,
        vertical=vertical_key,
    )


def process_batch(batch_file: str, vertical: str, worker_id: int, run_date: str = None) -> str:
    """Mirrors unified_worker.py's process_batch() structure closely
    (pre-populate -> mark_in_progress -> process -> upsert_completed/
    failed -> heartbeat -> CSV backup) so the two are easy to compare and
    keep in sync, but calls the custom-vertical runner instead of one of
    the three hardcoded process_* functions. No work-partitioning
    (--total-workers) support -- enrichment.py's dispatch_job() only ever
    launches a single worker today for any vertical, same as it already
    does for the hardcoded ones."""
    log.info(f"Custom vertical worker {worker_id} starting: {vertical} - {batch_file}")

    run_date_obj = date.fromisoformat(run_date) if run_date else date.today()

    if not PSYCOPG2_AVAILABLE:
        log.error("FATAL: psycopg2 not available. Install with: pip install psycopg2-binary")
        sys.exit(1)

    try:
        sb_writer = SupabaseWriter()
        log.info(f"Supabase writer initialized (source: {sb_writer.source_droplet})")
    except Exception as e:
        log.error(f"FATAL: Failed to initialize Supabase writer: {e}")
        sys.exit(1)

    try:
        channel_rows = _load_channel_rows(vertical)
        # Built ONCE for the whole batch, not per record -- see
        # runner.build_channels()'s docstring: rebuilding per account
        # would reload YouTubeVideoEvidenceChannel's YOLO model from disk
        # on every single account instead of once per job.
        channels = runner.build_channels(channel_rows)
    except ValueError as e:
        log.error(f"FATAL: {e}")
        sys.exit(1)

    with open(batch_file, "r") as f:
        records = list(csv.DictReader(f))
    log.info(f"Loaded {len(records)} records")

    try:
        accounts = [
            {
                "account_id": r.get("account_id", ""),
                "account_name": r.get("account_name", ""),
                "vertical": vertical,
                "segment": r.get("segment"),
            }
            for r in records
        ]
        inserted = sb_writer.pre_populate_batch(accounts, run_date_obj, is_prospect=False)
        log.info(f"Pre-populated {inserted} pending rows")
    except Exception as e:
        log.error(f"Failed to pre-populate Supabase: {e}")

    heartbeat_id = sb_writer.insert_heartbeat(
        worker_id=str(worker_id), vertical=vertical, pid=os.getpid(),
        batch_file=batch_file, records_total=len(records),
    )

    results = []
    processed_count = 0
    skipped_count = 0

    for i, record in enumerate(records, 1):
        account_id = record.get("account_id", "")
        account_name = record.get("account_name", "Unknown")

        try:
            if sb_writer.check_already_completed(account_id, run_date_obj, vertical):
                log.info(f"[{i}/{len(records)}] SKIP {account_name} (already completed)")
                skipped_count += 1
                continue
        except Exception as e:
            log.warning(f"Failed to check completion status: {e}")

        try:
            sb_writer.mark_in_progress(account_id, run_date_obj)
        except Exception as e:
            log.warning(f"Failed to mark in_progress: {e}")

        try:
            log.info(f"[{i}/{len(records)}] Processing {account_name}")
            ctx = _record_to_context(record, vertical)
            result = runner.run_vertical_for_account(vertical, channels, ctx)
            full_result = {**record, **result}
            results.append(full_result)
            processed_count += 1

            try:
                sb_writer.upsert_completed(account_id, run_date_obj, full_result, enricher_version=VERSION)
            except Exception as e:
                log.error(f"Failed to write completed result to Supabase: {e}")

            sb_writer.update_heartbeat(heartbeat_id, processed_count, last_account_name=account_name)
            if processed_count % 50 == 0:
                log.info(f"Progress: {processed_count}/{len(records)} ({processed_count/len(records)*100:.1f}%)")
            time.sleep(0.5)  # same rate-limit pause unified_worker.py uses between accounts

        except Exception as e:
            log.error(f"Error processing record {i} ({account_name}): {e}")
            error_result = {**record, "error": str(e), "lead_status": "no_evidence"}
            results.append(error_result)
            processed_count += 1
            try:
                sb_writer.upsert_failed(account_id, run_date_obj, str(e), enricher_version=VERSION)
            except Exception as e2:
                log.error(f"Failed to write failed result to Supabase: {e2}")
            sb_writer.update_heartbeat(heartbeat_id, processed_count, last_account_name=account_name, last_error=str(e)[:500])

    output_file = f"results_{vertical}_worker_{worker_id}.csv"
    if results:
        all_keys = set()
        for r in results:
            all_keys.update(r.keys())
        fieldnames = sorted(all_keys)
    else:
        fieldnames = list(records[0].keys()) if records else []
    with open(output_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    log.info(f"Worker {worker_id} completed: {output_file}")
    log.info(f"   Processed: {processed_count} records, skipped: {skipped_count}")
    try:
        status = sb_writer.get_batch_status(run_date_obj, vertical)
        log.info(f"   Supabase status ({vertical}): {status}")
    except Exception as e:
        log.warning(f"Failed to get Supabase status: {e}")

    return output_file


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Custom (config-driven) vertical worker")
    parser.add_argument("vertical", help="custom vertical_key, as created in Settings")
    parser.add_argument("batch_file", help="CSV batch file to process")
    parser.add_argument("--worker-id", type=int, required=True)
    parser.add_argument("--run-date", type=str, help="Run date (YYYY-MM-DD, defaults to today)")
    args = parser.parse_args()

    log.info("=" * 80)
    log.info(f"CUSTOM VERTICAL WORKER - {args.vertical}")
    log.info(f"VERSION: {VERSION}")
    log.info("=" * 80)

    output = process_batch(args.batch_file, args.vertical, args.worker_id, run_date=args.run_date)

    log.info("=" * 80)
    log.info("WORKER COMPLETED SUCCESSFULLY")
    log.info(f"Output: {output}")


if __name__ == "__main__":
    main()
