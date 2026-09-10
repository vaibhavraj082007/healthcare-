"""ophthalmologist review queue — locking, versioning, amendments

Revision ID: 0003_review_queue
Revises: 0002_add_analysis_jobs
Create Date: 2026-09-10 10:00:00.000000

Adds to clinician_reviews:
  - review_version   : optimistic-concurrency stamp
  - locked_by_id     : UUID of reviewer who holds the case lock
  - locked_at        : when the lock was acquired
  - lock_expires_at  : TTL for stale-lock reclamation
  - recapture_requested : whether recapture was requested
  - is_ungradeable   : explicit ungradeable flag separate from grade=-1

Adds new table: review_amendments
  - Immutable append-only history of every change to a clinician_review
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from app.db.types import GUID

revision: str = "0003_review_queue"
down_revision: Union[str, None] = "0002_add_analysis_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Extend clinician_reviews
    # ------------------------------------------------------------------
    op.add_column(
        "clinician_reviews",
        sa.Column(
            "review_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="Optimistic-concurrency version stamp; incremented on each accepted edit",
        ),
    )
    op.add_column(
        "clinician_reviews",
        sa.Column(
            "locked_by_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            comment="User who currently holds the editing lock for this case",
        ),
    )
    op.add_column(
        "clinician_reviews",
        sa.Column(
            "locked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "clinician_reviews",
        sa.Column(
            "lock_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Lock TTL; stale locks older than this may be reclaimed",
        ),
    )
    op.add_column(
        "clinician_reviews",
        sa.Column(
            "recapture_requested",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "clinician_reviews",
        sa.Column(
            "is_ungradeable",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )

    # ------------------------------------------------------------------
    # review_amendments — immutable append-only audit trail for clinician edits
    # ------------------------------------------------------------------
    op.create_table(
        "review_amendments",
        sa.Column("id", GUID(), nullable=False),
        sa.Column(
            "review_id",
            GUID(),
            sa.ForeignKey("clinician_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "amended_by_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("previous_grade", sa.Integer(), nullable=True),
        sa.Column("new_grade", sa.Integer(), nullable=True),
        sa.Column("previous_referral", sa.String(30), nullable=True),
        sa.Column("new_referral", sa.String(30), nullable=True),
        sa.Column("previous_status", sa.String(20), nullable=True),
        sa.Column("new_status", sa.String(20), nullable=True),
        sa.Column(
            "change_reason",
            sa.Text(),
            nullable=True,
            comment="Required free-text reason when changing a final review",
        ),
        sa.Column("amendment_notes", sa.Text(), nullable=True),
        sa.Column(
            "amended_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_review_amendments_review_id",
        "review_amendments",
        ["review_id"],
        unique=False,
    )
    op.create_index(
        "ix_review_amendments_amended_by_id",
        "review_amendments",
        ["amended_by_id"],
        unique=False,
    )
    op.create_index(
        "ix_review_amendments_amended_at",
        "review_amendments",
        ["amended_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_review_amendments_amended_at", table_name="review_amendments")
    op.drop_index("ix_review_amendments_amended_by_id", table_name="review_amendments")
    op.drop_index("ix_review_amendments_review_id", table_name="review_amendments")
    op.drop_table("review_amendments")
    op.drop_column("clinician_reviews", "is_ungradeable")
    op.drop_column("clinician_reviews", "recapture_requested")
    op.drop_column("clinician_reviews", "lock_expires_at")
    op.drop_column("clinician_reviews", "locked_at")
    op.drop_column("clinician_reviews", "locked_by_id")
    op.drop_column("clinician_reviews", "review_version")
