"""add analysis_jobs table

Revision ID: 0002_add_analysis_jobs
Revises: 0001_initial_schema
Create Date: 2026-09-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from app.db.types import GUID

# revision identifiers, used by Alembic.
revision: str = '0002_add_analysis_jobs'
down_revision: Union[str, None] = '0001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'analysis_jobs',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('screening_id', GUID(), nullable=False),
        sa.Column('image_id', GUID(), nullable=True),
        sa.Column('facility_id', sa.String(length=100), nullable=True),
        sa.Column('idempotency_key', sa.String(length=128), nullable=False, comment='Unique idempotency token preventing duplicate job dispatch'),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='queued', comment='queued, running, completed, failed, cancelled'),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0', comment='Queue priority (higher executes first)'),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False, server_default='300'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_trace', sa.Text(), nullable=True),
        sa.Column('worker_id', sa.String(length=100), nullable=True),
        sa.Column('parameters', sa.JSON(), nullable=True),
        sa.Column('result_json', sa.JSON(), nullable=True),
        sa.Column('timings', sa.JSON(), nullable=True),
        sa.Column('model_metadata', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['screening_id'], ['screenings.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['image_id'], ['screening_images.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key')
    )
    op.create_index(op.f('ix_analysis_jobs_screening_id'), 'analysis_jobs', ['screening_id'], unique=False)
    op.create_index(op.f('ix_analysis_jobs_image_id'), 'analysis_jobs', ['image_id'], unique=False)
    op.create_index(op.f('ix_analysis_jobs_facility_id'), 'analysis_jobs', ['facility_id'], unique=False)
    op.create_index(op.f('ix_analysis_jobs_idempotency_key'), 'analysis_jobs', ['idempotency_key'], unique=True)
    op.create_index(op.f('ix_analysis_jobs_status'), 'analysis_jobs', ['status'], unique=False)
    op.create_index('ix_analysis_jobs_facility_status', 'analysis_jobs', ['facility_id', 'status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_analysis_jobs_facility_status', table_name='analysis_jobs')
    op.drop_index(op.f('ix_analysis_jobs_status'), table_name='analysis_jobs')
    op.drop_index(op.f('ix_analysis_jobs_idempotency_key'), table_name='analysis_jobs')
    op.drop_index(op.f('ix_analysis_jobs_facility_id'), table_name='analysis_jobs')
    op.drop_index(op.f('ix_analysis_jobs_image_id'), table_name='analysis_jobs')
    op.drop_index(op.f('ix_analysis_jobs_screening_id'), table_name='analysis_jobs')
    op.drop_table('analysis_jobs')
