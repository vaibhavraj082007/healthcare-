"""initial retinashield schema

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-09-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from app.db.types import GUID

# revision identifiers, used by Alembic.
revision: str = '0001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Facilities
    op.create_table(
        'facilities',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('facility_code', sa.String(length=100), nullable=False, comment='Unique facility code (e.g., PHC-MH-PUNE-001)'),
        sa.Column('name', sa.String(length=300), nullable=False),
        sa.Column('facility_type', sa.String(length=50), nullable=False, server_default='PHC'),
        sa.Column('state', sa.String(length=100), nullable=True),
        sa.Column('district', sa.String(length=100), nullable=True),
        sa.Column('block', sa.String(length=100), nullable=True),
        sa.Column('pin_code', sa.String(length=10), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('has_fundus_camera', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('camera_model', sa.String(length=200), nullable=True),
        sa.Column('has_internet', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('offline_capable', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('contact_person', sa.String(length=200), nullable=True),
        sa.Column('contact_phone', sa.String(length=20), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('pending_sync_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('facility_code')
    )
    op.create_index(op.f('ix_facilities_facility_code'), 'facilities', ['facility_code'], unique=True)

    # 2. Users (Staff)
    op.create_table(
        'users',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('username', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False),
        sa.Column('facility_id', sa.String(length=100), nullable=True),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.facility_code'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
        sa.UniqueConstraint('email')
    )
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_role'), 'users', ['role'], unique=False)
    op.create_index(op.f('ix_users_facility_id'), 'users', ['facility_id'], unique=False)

    # 3. Patients (Minimal details, no mandatory Aadhaar/ABHA)
    op.create_table(
        'patients',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('first_name', sa.String(length=100), nullable=False),
        sa.Column('last_name', sa.String(length=100), nullable=False),
        sa.Column('date_of_birth', sa.Date(), nullable=True),
        sa.Column('gender', sa.String(length=20), nullable=True),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('aadhaar_last4', sa.String(length=4), nullable=True),
        sa.Column('diabetes_type', sa.String(length=20), nullable=True),
        sa.Column('diabetes_duration_years', sa.Integer(), nullable=True),
        sa.Column('on_insulin', sa.Boolean(), nullable=True),
        sa.Column('hba1c_latest', sa.Float(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('facility_id', sa.String(length=100), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deletion_reason', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_patients_facility_id'), 'patients', ['facility_id'], unique=False)
    op.create_index(op.f('ix_patients_is_deleted'), 'patients', ['is_deleted'], unique=False)

    # 4. Consent Records
    op.create_table(
        'consent_records',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('patient_id', GUID(), nullable=False),
        sa.Column('consent_type', sa.String(length=100), nullable=False),
        sa.Column('granted', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('consent_date', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('obtained_by_name', sa.String(length=255), nullable=True),
        sa.Column('witness_name', sa.String(length=255), nullable=True),
        sa.Column('withdrawn', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('withdrawn_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('withdrawal_reason', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_consent_records_patient_id'), 'consent_records', ['patient_id'], unique=False)

    # 5. Screenings
    op.create_table(
        'screenings',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('patient_id', GUID(), nullable=False),
        sa.Column('facility_id', sa.String(length=100), nullable=True),
        sa.Column('screener_id', GUID(), nullable=True),
        sa.Column('screener_name', sa.String(length=200), nullable=True),
        sa.Column('eye', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='pending'),
        sa.Column('analysis_result', sa.JSON(), nullable=True),
        sa.Column('quality_verdict', sa.String(length=20), nullable=True),
        sa.Column('dr_grade', sa.Integer(), nullable=True),
        sa.Column('dr_grade_label', sa.String(length=50), nullable=True),
        sa.Column('dr_confidence', sa.Float(), nullable=True),
        sa.Column('referral_urgency', sa.String(length=20), nullable=True),
        sa.Column('model_trained', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('disclaimer', sa.Text(), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('screened_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('analyzed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('synced', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['screener_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_screenings_patient_id'), 'screenings', ['patient_id'], unique=False)
    op.create_index(op.f('ix_screenings_facility_id'), 'screenings', ['facility_id'], unique=False)
    op.create_index(op.f('ix_screenings_is_deleted'), 'screenings', ['is_deleted'], unique=False)

    # 6. Screening Images
    op.create_table(
        'screening_images',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('screening_id', GUID(), nullable=False),
        sa.Column('original_filename', sa.String(length=500), nullable=False),
        sa.Column('stored_filename', sa.String(length=500), nullable=False),
        sa.Column('storage_path', sa.String(length=1000), nullable=False),
        sa.Column('content_type', sa.String(length=50), nullable=False, server_default='image/jpeg'),
        sa.Column('file_size_bytes', sa.Integer(), nullable=True),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('eye', sa.String(length=10), nullable=False),
        sa.Column('sha256_hash', sa.String(length=64), nullable=True),
        sa.Column('enhanced_image_path', sa.String(length=1000), nullable=True),
        sa.Column('gradcam_image_path', sa.String(length=1000), nullable=True),
        sa.Column('vessel_mask_path', sa.String(length=1000), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['screening_id'], ['screenings.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_screening_images_screening_id'), 'screening_images', ['screening_id'], unique=False)
    op.create_index(op.f('ix_screening_images_sha256_hash'), 'screening_images', ['sha256_hash'], unique=False)

    # 7. Image Provenance
    op.create_table(
        'image_provenance',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('image_id', GUID(), nullable=False),
        sa.Column('camera_make', sa.String(length=100), nullable=True),
        sa.Column('camera_model', sa.String(length=100), nullable=True),
        sa.Column('lens_type', sa.String(length=100), nullable=True),
        sa.Column('fov_angle_degrees', sa.Float(), nullable=True),
        sa.Column('capture_timestamp', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sha256_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['image_id'], ['screening_images.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('image_id')
    )
    op.create_index(op.f('ix_image_provenance_sha256_hash'), 'image_provenance', ['sha256_hash'], unique=False)

    # 8. Quality Results
    op.create_table(
        'quality_results',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('image_id', GUID(), nullable=False),
        sa.Column('screening_id', GUID(), nullable=False),
        sa.Column('verdict', sa.String(length=30), nullable=False),
        sa.Column('ungradeable', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('overall_quality_score', sa.Float(), nullable=True),
        sa.Column('contrast', sa.Float(), nullable=True),
        sa.Column('sharpness', sa.Float(), nullable=True),
        sa.Column('illumination_uniformity', sa.Float(), nullable=True),
        sa.Column('blur_score', sa.Float(), nullable=True),
        sa.Column('valid_retina_percentage', sa.Float(), nullable=True),
        sa.Column('failure_reasons', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['image_id'], ['screening_images.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['screening_id'], ['screenings.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_quality_results_image_id'), 'quality_results', ['image_id'], unique=False)
    op.create_index(op.f('ix_quality_results_screening_id'), 'quality_results', ['screening_id'], unique=False)

    # 9. Model Outputs (AI findings)
    op.create_table(
        'model_outputs',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('screening_id', GUID(), nullable=False),
        sa.Column('image_id', GUID(), nullable=True),
        sa.Column('model_name', sa.String(length=100), nullable=False),
        sa.Column('model_version', sa.String(length=50), nullable=False),
        sa.Column('model_trained', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('predicted_dr_grade', sa.Integer(), nullable=True),
        sa.Column('predicted_grade_label', sa.String(length=50), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('class_probabilities', sa.JSON(), nullable=True),
        sa.Column('calibrated', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('uncertainty_entropy', sa.Float(), nullable=True),
        sa.Column('uncertainty_margin', sa.Float(), nullable=True),
        sa.Column('concordance_status', sa.String(length=50), nullable=True),
        sa.Column('lesion_detections_summary', sa.JSON(), nullable=True),
        sa.Column('gradcam_path', sa.String(length=1000), nullable=True),
        sa.Column('disclaimer', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['screening_id'], ['screenings.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['image_id'], ['screening_images.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_model_outputs_screening_id'), 'model_outputs', ['screening_id'], unique=False)

    # 10. Clinician Reviews (Clinician conclusions)
    op.create_table(
        'clinician_reviews',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('screening_id', GUID(), nullable=False),
        sa.Column('reviewer_id', GUID(), nullable=False),
        sa.Column('confirmed_dr_grade', sa.Integer(), nullable=False),
        sa.Column('macular_edema_present', sa.Boolean(), nullable=True),
        sa.Column('referral_recommendation', sa.String(length=30), nullable=False),
        sa.Column('follow_up_months', sa.Integer(), nullable=True),
        sa.Column('clinical_notes', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='final'),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['screening_id'], ['screenings.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reviewer_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_clinician_reviews_screening_id'), 'clinician_reviews', ['screening_id'], unique=False)
    op.create_index(op.f('ix_clinician_reviews_reviewer_id'), 'clinician_reviews', ['reviewer_id'], unique=False)

    # 11. Reports
    op.create_table(
        'reports',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('screening_id', GUID(), nullable=False),
        sa.Column('generated_by_id', GUID(), nullable=True),
        sa.Column('signed_by_id', GUID(), nullable=True),
        sa.Column('report_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='signed'),
        sa.Column('summary_json', sa.JSON(), nullable=False),
        sa.Column('file_path', sa.String(length=1000), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['screening_id'], ['screenings.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['generated_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['signed_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reports_screening_id'), 'reports', ['screening_id'], unique=False)

    # 12. Audit Events
    op.create_table(
        'audit_events',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('user_id', GUID(), nullable=True),
        sa.Column('facility_id', sa.String(length=100), nullable=True),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('resource_type', sa.String(length=50), nullable=False),
        sa.Column('resource_id', sa.String(length=100), nullable=True),
        sa.Column('ip_address', sa.String(length=50), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_events_event_type'), 'audit_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_audit_events_user_id'), 'audit_events', ['user_id'], unique=False)
    op.create_index(op.f('ix_audit_events_facility_id'), 'audit_events', ['facility_id'], unique=False)
    op.create_index(op.f('ix_audit_events_created_at'), 'audit_events', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_table('audit_events')
    op.drop_table('reports')
    op.drop_table('clinician_reviews')
    op.drop_table('model_outputs')
    op.drop_table('quality_results')
    op.drop_table('image_provenance')
    op.drop_table('screening_images')
    op.drop_table('screenings')
    op.drop_table('consent_records')
    op.drop_table('patients')
    op.drop_table('users')
    op.drop_table('facilities')
