#!/usr/bin/env python3
"""
Weekly cron/launchd entry point — runs the pipeline via file_discovery.py,
independent of whether the FastAPI server (uvicorn) is up. Point your
scheduler at this script directly; it doesn't need the UI running.

Setup (macOS/Linux, cron) — every Monday 6am local time:
    crontab -e
    0 6 * * 1 /usr/bin/python3 /path/to/mplc_pop_engine/ui_app/scripts/weekly_run.py >> ~/mplc_pop_engine_data/weekly_run.log 2>&1

Before the schedule fires, drop the week's fresh Salesforce exports into
~/mplc_pop_engine_data/incoming/ (or wherever POP_ENGINE_DATA_DIR points).
On success, those files are moved into archive/<run_date>/ automatically.
"""
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.db import init_db, get_session  # noqa: E402
from backend.pipeline_runner import run_and_persist  # noqa: E402
from backend.file_discovery import (  # noqa: E402
    discover_weekly_files, archive_files, DiscoveryError, OUTPUT_DIR,
)


def main() -> int:
    init_db()
    run_date = date.today().isoformat()
    print(f"[{run_date}] Weekly pipeline run starting...")

    try:
        files = discover_weekly_files()
    except DiscoveryError as e:
        print(f"[{run_date}] ABORTED: {e}")
        return 1

    print(f"[{run_date}] Found input files:")
    for role, path in files.items():
        print(f"  {role}: {path}")

    run_output_dir = OUTPUT_DIR / run_date
    run_output_dir.mkdir(parents=True, exist_ok=True)

    try:
        with get_session() as session:
            summary = run_and_persist(
                session=session,
                salesforce_export_path=str(files["salesforce_export"]),
                output_dir=str(run_output_dir),
                run_date=run_date,
                open_deals_path=str(files["open_deals"]),
                activity_90_days_path=str(files["activity_90_days"]) if "activity_90_days" in files else None,
                lost_deals_9_months_path=str(files["lost_deals_9_months"]) if "lost_deals_9_months" in files else None,
                verbose=True,
            )
    except Exception as e:
        print(f"[{run_date}] FAILED: {e}")
        return 1

    archive_files(files, run_date)
    print(f"[{run_date}] COMPLETE. Summary: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
