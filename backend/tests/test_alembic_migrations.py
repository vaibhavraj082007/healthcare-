"""
RetinaShield — Alembic Migration Test Suite

Verifies that Alembic versioned migrations are syntactically valid
and generate complete PostgreSQL DDL for all system tables.
"""

from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path
from alembic.config import Config
from alembic import command


class TestAlembicMigrations(unittest.TestCase):
    """Test suite for Alembic PostgreSQL migrations."""

    def test_alembic_offline_sql_generation(self):
        """Verify that alembic upgrade head --sql generates valid DDL for all 12 tables."""
        backend_dir = Path(__file__).resolve().parent.parent
        ini_path = backend_dir / "alembic.ini"

        alembic_cfg = Config(str(ini_path))
        alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))

        buf = io.StringIO()
        alembic_cfg.stdout = buf

        with contextlib.redirect_stdout(buf):
            command.upgrade(alembic_cfg, "head", sql=True)
        sql_output = buf.getvalue()

        required_tables = [
            "facilities",
            "users",
            "patients",
            "consent_records",
            "screenings",
            "screening_images",
            "image_provenance",
            "quality_results",
            "model_outputs",
            "clinician_reviews",
            "reports",
            "audit_events",
            "analysis_jobs",
        ]

        for table in required_tables:
            self.assertIn(f"CREATE TABLE {table}", sql_output, f"Missing table {table} in migration DDL")

        self.assertIn("alembic_version", sql_output)
        self.assertIn("0001_initial_schema", sql_output)
        self.assertIn("0002_add_analysis_jobs", sql_output)

