"""
SQLAlchemy models — single source of truth for the PoP Detection Engine UI.

Replaces the "N ad hoc CSV shapes with no shared structure" pattern flagged
in MDU_Engine_Phase2_Productization_Spec.md (section 5) as the single
biggest recurring failure in the MDU live session — generalized here to the
whole pipeline (Stage A/B/C + Clay dedupe), not just MDU.

Design principles (per the "designing first principles for the UI"
conversation, 2026-11-11):
  - `accounts` is refreshed in place, one row per real Salesforce account.
    It is NOT re-inserted every run — a weekly pipeline run UPDATES it.
  - Every pipeline stage's output is a *_runs table, keyed by
    (account_id, run_date), so history is kept rather than overwritten.
    This also means segmentation_runs/classification_runs/eligibility_runs
    are append-only — querying "latest run" is a filter, not a destructive
    write.
  - Room is deliberately left for two future stages Jeff named (name
    cleanser, industry fixer): `accounts.canonical_name` and
    `accounts.cleansed_industry` are already present (nullable, unused for
    now), and a `name_cleanser_runs` / `industry_fixer_runs` table can slot
    in later using the exact same (account_id, run_date) pattern as
    classification_runs/segmentation_runs below — no redesign needed.
  - SQLite for now (Jeff: local-only, solo user today). Written against
    plain SQLAlchemy Core/ORM with no SQLite-specific types, so moving to
    Postgres later (when the data team comes online) is a connection-string
    change in db.py, not a model rewrite.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, Text, ForeignKey, Index,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    """A login account for this app. Added 2026-11-14 per Jeff: the backend
    had zero auth and wide-open CORS (`allow_origins=["*"]` in main.py) —
    fine for a read-only local triage tool, not fine once a settings page
    can write API keys and DATABASE_URL. Multi-user with sign-up (Jeff's
    choice over a single fixed admin account), protecting the whole app
    via middleware (auth.py), not just the new settings endpoints."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid4
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Account(Base):
    """One row per real Salesforce account. Refreshed in place by each
    weekly pipeline run — never re-inserted for the same account_id."""
    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String(18), primary_key=True)
    account_name: Mapped[Optional[str]] = mapped_column(String(500))
    website: Mapped[Optional[str]] = mapped_column(String(500))
    account_status: Mapped[Optional[str]] = mapped_column(String(100))
    parent_account_id: Mapped[Optional[str]] = mapped_column(String(18))
    industry: Mapped[Optional[str]] = mapped_column(String(200))
    account_sub_industry: Mapped[Optional[str]] = mapped_column(String(200))
    state: Mapped[Optional[str]] = mapped_column(String(100))
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    # Added 2026-11-12 (Jeff: need to filter by Country / Operating Market /
    # Capacity / Capacity Type — he's primarily focused on US MM+ENT today).
    # All 4 are real Salesforce export columns, confirmed present and
    # carried through unchanged by account_eligibility.py's
    # compute_eligibility_vectorized (its own docstring: "every original
    # column... preserved"). country uses "Account Country (text only)"
    # (167 distinct values) rather than the picklist "Account Country" —
    # same convention as `state` using the "(text only)" variant.
    # operating_market is NOT redundant with country: it has only 18
    # distinct values and splits out brand/division variants (e.g.
    # "CVLI United States" vs "United States") that country collapses.
    # capacity is genuinely sparse (15,321 of 703,260 real rows) and
    # numeric — kept as Integer, not String, so it can be range-filtered
    # (capacity_min/capacity_max), not just exact-matched.
    country: Mapped[Optional[str]] = mapped_column(String(100))
    operating_market: Mapped[Optional[str]] = mapped_column(String(100))
    capacity: Mapped[Optional[int]] = mapped_column(Integer)
    capacity_type: Mapped[Optional[str]] = mapped_column(String(50))
    created_date: Mapped[Optional[str]] = mapped_column(String(50))
    last_modified_date: Mapped[Optional[str]] = mapped_column(String(50))
    last_activity: Mapped[Optional[str]] = mapped_column(String(50))

    # Reserved for future stages (name cleanser / industry fixer) — not
    # written to by anything built so far. See module docstring.
    canonical_name: Mapped[Optional[str]] = mapped_column(String(500))
    cleansed_industry: Mapped[Optional[str]] = mapped_column(String(200))

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow,
                                                   onupdate=datetime.utcnow)

    eligibility_runs: Mapped[list["EligibilityRun"]] = relationship(back_populates="account")
    classification_runs: Mapped[list["ClassificationRun"]] = relationship(back_populates="account")
    segmentation_runs: Mapped[list["SegmentationRun"]] = relationship(back_populates="account")
    actions: Mapped[list["Action"]] = relationship(back_populates="account")


class PipelineRun(Base):
    """A single invocation of the weekly pipeline (or one stage of it).
    Lets the UI show run history instead of only ever seeing the latest
    overwrite, and gives every *_run row below a run_id to point back to."""
    __tablename__ = "pipeline_runs"

    run_id: Mapped[str] = mapped_column(String(50), primary_key=True)  # e.g. "2026-11-11_full"
    run_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    stage: Mapped[str] = mapped_column(String(10))  # A | B | C | ALL | CLAY_DEDUPE
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|completed|failed
    counts_json: Mapped[Optional[str]] = mapped_column(Text)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class EligibilityRun(Base):
    """Stage A's audit row for one account on one run_date. Append-only —
    never update an existing row, insert a new one per run_date."""
    __tablename__ = "eligibility_runs"
    __table_args__ = (
        UniqueConstraint("account_id", "run_date", name="uq_eligibility_account_run"),
        Index("ix_eligibility_run_date_excluded", "run_date", "excluded"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    run_date: Mapped[str] = mapped_column(String(10), index=True)
    excluded: Mapped[bool] = mapped_column(Boolean, index=True)
    exclusion_reasons: Mapped[Optional[str]] = mapped_column(Text)  # semicolon-delimited
    hierarchy_component: Mapped[Optional[str]] = mapped_column(String(50))
    domain_component: Mapped[Optional[str]] = mapped_column(String(50))
    name_component: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    account: Mapped["Account"] = relationship(back_populates="eligibility_runs")


class ClassificationRun(Base):
    """Stage B's vertical assignment for one account on one run_date."""
    __tablename__ = "classification_runs"
    __table_args__ = (
        UniqueConstraint("account_id", "run_date", name="uq_classification_account_run"),
        Index("ix_classification_run_date_vertical", "run_date", "vertical"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    run_date: Mapped[str] = mapped_column(String(10), index=True)
    vertical: Mapped[str] = mapped_column(String(200), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    account: Mapped["Account"] = relationship(back_populates="classification_runs")


class SegmentationRun(Base):
    """Stage C's ROE segment for one account on one run_date. `segment`
    being UNRESOLVED (plus `missing_data`/`edge_case` populated) is exactly
    how the three known review-queue cases surface — see roe_rules/*.py
    docstrings for why Corporate/Healthcare/MDU route here 100% today."""
    __tablename__ = "segmentation_runs"
    __table_args__ = (
        UniqueConstraint("account_id", "run_date", name="uq_segmentation_account_run"),
        Index("ix_segmentation_run_date_segment", "run_date", "vertical", "segment"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    run_date: Mapped[str] = mapped_column(String(10), index=True)
    # Nullable: Stage B has a real blank-string vertical bucket (unmapped/
    # junk industry codes, ~3,642 real accounts — see weekly_pipeline.py's
    # own run output, logged as "  : 3,642 accounts"). That blank name
    # round-trips through the ROE audit CSV as NaN, not an empty string —
    # confirmed real, not a data error, so this column must allow NULL
    # rather than coercing it back to "" silently.
    vertical: Mapped[Optional[str]] = mapped_column(String(200), index=True)
    segment: Mapped[str] = mapped_column(String(20), index=True)  # SB|MM|ENT|UNRESOLVED|FORTUNE500|GOV
    confidence: Mapped[Optional[str]] = mapped_column(String(20))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    missing_data: Mapped[Optional[str]] = mapped_column(Text)  # pipe-delimited
    edge_case: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    account: Mapped["Account"] = relationship(back_populates="segmentation_runs")


class ClayMatch(Base):
    """One Clay-export row's dedupe result against the Salesforce universe,
    from clay_dedupe.py. Not FK'd tightly to Account by account_id alone
    because a Clay row may match 0 or >1 candidates (num_candidates) —
    matched_account_id is the primary/best candidate; ambiguous cases
    (num_candidates > 1) are the review queue."""
    __tablename__ = "clay_matches"
    __table_args__ = (
        Index("ix_clay_batch", "batch_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(50), index=True)
    clay_company_name: Mapped[Optional[str]] = mapped_column(String(500))
    clay_website: Mapped[Optional[str]] = mapped_column(String(500))
    classification: Mapped[str] = mapped_column(String(30), index=True)
    match_method: Mapped[Optional[str]] = mapped_column(String(30))
    match_confidence: Mapped[Optional[str]] = mapped_column(String(30))
    matched_account_id: Mapped[Optional[str]] = mapped_column(String(18))
    matched_account_name: Mapped[Optional[str]] = mapped_column(String(500))
    num_candidates: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # AI brand-verification (2026-11-16, Jeff: "is there a way for the low
    # confidence to have claude api open up both websites and do a
    # comparison?" -- for a POSSIBLE_MATCH_BRAND row, fetches both
    # companies' homepages and asks Claude whether they're the same
    # real-world business under different names/domains, or genuinely
    # different companies that happen to share a brand word. Nullable/
    # unset until a human actually requests a verification for that row
    # (never run automatically -- same "never silently trusted" bar as
    # the brand-fuzzy match itself).
    ai_verdict: Mapped[Optional[str]] = mapped_column(String(20))          # same / different / uncertain
    ai_reasoning: Mapped[Optional[str]] = mapped_column(String(2000))
    ai_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # Real spend for that one AI Check click (2026-11-16, Jeff: "when i
    # click on AI Check are we cost tracking that?" -- it wasn't, until
    # this). Computed from the Anthropic response's own token usage in
    # brand_verify.py, not estimated; 0.0 when no API call was actually
    # made (e.g. both homepage fetches failed first).
    ai_check_cost: Mapped[Optional[float]] = mapped_column(Float)


class Action(Base):
    """Audit trail of what a human actually did in the UI (the real
    'select rows -> dispatch' triage action), separate from what the
    pipeline computed. created_by is nullable today (solo user) and
    becomes meaningful once the data team is on this tool."""
    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    action_type: Mapped[str] = mapped_column(String(50), index=True)  # dispatch_to_enrichment|export_clay|mark_reviewed
    status: Mapped[str] = mapped_column(String(20), default="pending")
    payload_json: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    account: Mapped["Account"] = relationship(back_populates="actions")


class EnrichmentJob(Base):
    """One local dispatch of unified_worker.py against a batch of accounts
    (Step 2, 2026-11-13: "take selected accounts and run it through
    vertical pipelines + check already enriched accounts to not burn
    credits"). This table is OUR local bookkeeping only — the actual
    per-account enrichment state/results live in Supabase's
    account_enrichment_results (and, per-run, worker_heartbeat), written by
    the subprocess itself. We track just enough here (pid, batch/log file
    paths, which accounts were actually dispatched vs. skipped as already
    enriched) to scope a Supabase query to *this* job specifically, since
    account_enrichment_results has no job_id column of its own — see
    EnrichmentJobAccount."""
    __tablename__ = "enrichment_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid4
    vertical: Mapped[str] = mapped_column(String(20), index=True)  # worker's vertical key: healthcare|corporate|mdu
    display_vertical: Mapped[str] = mapped_column(String(200))  # our app's vertical label, e.g. "Health Care Services"
    run_date: Mapped[str] = mapped_column(String(10), index=True)
    batch_file: Mapped[str] = mapped_column(String(500))
    log_file: Mapped[str] = mapped_column(String(500))
    worker_script: Mapped[str] = mapped_column(String(500))
    pid: Mapped[Optional[int]] = mapped_column(Integer)
    total_requested: Mapped[int] = mapped_column(Integer)  # accounts selected before the already-enriched filter
    total_dispatched: Mapped[int] = mapped_column(Integer)  # accounts actually in the batch file (after filtering)
    skipped_already_enriched: Mapped[int] = mapped_column(Integer, default=0)
    # "running" until we observe the pid has exited; then "completed" (clean
    # exit) or "failed" (nonzero exit / exited before fully processing).
    # Never trust "running" alone as proof of life — the progress endpoint
    # re-checks the pid every time, this column is a cache of the last check.
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_by: Mapped[Optional[str]] = mapped_column(String(100))

    job_accounts: Mapped[list["EnrichmentJobAccount"]] = relationship(back_populates="job")


class EnrichmentJobAccount(Base):
    """Which account_ids were actually dispatched in a given EnrichmentJob —
    lets the progress endpoint scope its Supabase query to WHERE account_id
    = ANY(these) AND run_date = job.run_date AND vertical = job.vertical,
    so two jobs for the same vertical on the same day never bleed into each
    other's progress view."""
    __tablename__ = "enrichment_job_accounts"
    __table_args__ = (
        Index("ix_enrichment_job_accounts_job", "job_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("enrichment_jobs.id"), index=True)
    account_id: Mapped[str] = mapped_column(String(18), index=True)

    job: Mapped["EnrichmentJob"] = relationship(back_populates="job_accounts")


class CustomVertical(Base):
    """A vertical Jeff defines from the Settings tab instead of a new Python
    file. See claude/Custom_Vertical_Builder_Design.md in the project.
    `vertical_key` is a slug and doubles as the key DISPATCHABLE_VERTICALS
    uses for the hardcoded verticals, so Step 2's dispatch dropdown can
    union the two without a separate ID scheme."""
    __tablename__ = "custom_verticals"

    vertical_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    # Added 2026-11-18 ("when we create a vertical, does it map to the
    # correct pipeline post-Step-1?" follow-up): Stage B's classifier
    # (industry_reclassifier.py) is a fixed, already-validated 7-category
    # taxonomy with zero knowledge of custom verticals, and extending it
    # was explicitly ruled out in favor of a separate, additive tagger --
    # see pipeline_runner.py's match_custom_verticals() and
    # CustomVerticalMatch below. match_keywords_json is generated ONCE (a
    # single LLM call from this vertical's own channel descriptions, same
    # "one-time, not per-account" principle as config_json on
    # CustomVerticalChannel) via a JSON list of plain keyword/phrase
    # strings, then hand-editable in Settings the same way a channel's
    # config is. Matching itself (checking these keywords against each
    # safe account's industry/account_name) is a free substring check --
    # no LLM cost per account, no cost tracking needed for that part.
    match_keywords_json: Mapped[Optional[str]] = mapped_column(Text)
    match_keywords_generated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow,
                                                   onupdate=datetime.utcnow)

    channels: Mapped[list["CustomVerticalChannel"]] = relationship(
        back_populates="vertical", cascade="all, delete-orphan",
        order_by="CustomVerticalChannel.step_order",
    )
    matches: Mapped[list["CustomVerticalMatch"]] = relationship(
        back_populates="vertical", cascade="all, delete-orphan",
    )


class CustomVerticalChannel(Base):
    """One step in a custom vertical's recipe. Execution order is
    `step_order`; the runner (verticals/custom/runner.py) stops at the
    first enabled channel that returns tier=PROSPECT -- same early-exit
    convention every hardcoded vertical already uses, just config-driven
    here instead of a hand-written if/elif chain.

    `description` is Jeff's plain-English input, kept even after
    `config_json` is generated so a channel can be regenerated later
    without re-typing it. `config_json` is generated ONCE (not per account
    enriched) by production/channels/config_from_description.py, then
    hand-editable -- see design doc §2."""
    __tablename__ = "custom_vertical_channels"
    __table_args__ = (
        Index("ix_custom_vertical_channels_vertical", "vertical_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vertical_key: Mapped[str] = mapped_column(ForeignKey("custom_verticals.vertical_key"))
    step_order: Mapped[int] = mapped_column(Integer, default=0)
    # "serper_image" | "youtube_video" | "website_scrape"
    channel_type: Mapped[str] = mapped_column(String(30))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str] = mapped_column(Text)
    config_json: Mapped[Optional[str]] = mapped_column(Text)  # JSON: query_templates, target_spaces, excluded_spaces
    config_generated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow,
                                                   onupdate=datetime.utcnow)

    vertical: Mapped["CustomVertical"] = relationship(back_populates="channels")


class CustomVerticalMatch(Base):
    """One safe account matching one custom vertical's keywords, on one
    run_date. Deliberately a SEPARATE table from ClassificationRun, not an
    extension of it -- Stage B's classifier assigns exactly ONE of its 7
    fixed categories per account per run_date (enforced by
    classification_runs' uq_classification_account_run unique constraint),
    but a custom vertical is not mutually exclusive with those categories
    or with another custom vertical: the same account could plausibly
    match two different custom verticals' keywords (e.g. "senior living"
    and "memory care" verticals both matching an assisted-living account).
    So this is a many-to-many shape (account_id, vertical_key, run_date),
    not a single-value-per-account-per-date column like
    classification_runs.vertical.

    Populated by pipeline_runner.py's match_custom_verticals() -- run
    automatically right after Stage B in the weekly pipeline, and also
    on-demand via POST /custom-verticals/rematch (Settings' "Re-match now"
    button) for whenever Jeff edits a vertical's keywords and doesn't want
    to wait for next week's run. Append-only per run_date, same pattern as
    eligibility_runs/classification_runs/segmentation_runs, so history is
    kept rather than overwritten."""
    __tablename__ = "custom_vertical_matches"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "vertical_key", "run_date",
            name="uq_custom_vertical_match_account_vertical_run",
        ),
        Index("ix_custom_vertical_matches_run_vertical", "run_date", "vertical_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    vertical_key: Mapped[str] = mapped_column(ForeignKey("custom_verticals.vertical_key"), index=True)
    run_date: Mapped[str] = mapped_column(String(10), index=True)
    matched_keyword: Mapped[Optional[str]] = mapped_column(String(200))  # which keyword matched, for debugging/audit
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    vertical: Mapped["CustomVertical"] = relationship(back_populates="matches")
