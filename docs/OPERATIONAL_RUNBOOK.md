# RetinaShield — Operational Runbook & System Guide

> [!IMPORTANT]
> **STATUTORY & CLINICAL SAFETY NOTICE**
> RetinaShield is an **investigational research and screening prototype**.
> It is **NOT approved as a medical device** under CDSCO Medical Device Rules 2017 or international regulatory standards (FDA 510(k), CE mark).
> It is strictly designed for research, workflow triage assistance, and operational evaluation under human-in-the-loop oversight.
> **All AI-generated findings must be reviewed, confirmed, or amended by a qualified ophthalmologist before clinical action.**

---

## 1. System Overview & Architecture

RetinaShield is engineered to provide diabetic retinopathy (DR) screening in resource-constrained Primary Health Centres (PHCs). The platform supports three distinct operational tiers:

```mermaid
graph TD
    subgraph Local PHC Node (Offline Capable)
        A[Fundus Camera] -->|USB/LAN| B[Private Encrypted Storage]
        B --> C[Local SQLite/PostgreSQL DB]
        C --> D[FastAPI Backend :8000]
        D --> E[Next.js Local Web UI :3000]
        D --> F[MATLAB Worker Engine/MCR]
    end
    subgraph Central Facility / Cloud
        G[Central Synchronization Server]
        H[Remote Ophthalmologist Review Station]
    end
    D <-->|Durable Outbox Sync when Online| G
    G <--> H
```

### Operational Tier Distinctions
1. **Offline Capture & Queuing**: Health workers capture images, record demographics, and store findings securely on the local facility machine.
2. **Offline Inference**: Executes on the local host only when the standalone compiled MATLAB component (or licensed MATLAB Engine) and neural weights are installed. *A cached web interface alone cannot execute MATLAB models without a local backend runtime.*
3. **Online Synchronization & Remote Review**: When connectivity is restored, records synchronise via the durable outbox. Remote ophthalmologists can review flagged cases and sign reports.

---

## 2. Licensing & Runtime Requirements

| Component | Dev / Research Mode | Production PHC Deployment | Fallback / CI Mode |
| :--- | :--- | :--- | :--- |
| **MATLAB** | Licensed MathWorks MATLAB (R2022b+) + Image Processing + Deep Learning Toolboxes | MATLAB Runtime (MCR v913+) — Royalty-free redistribution | Not required |
| **Python** | Python 3.10 – 3.12, PyTorch, Torchvision, ReportLab, FastAPI | Python 3.10 – 3.12, Uvicorn, SQLAlchemy | Python 3.10+, OpenCV, NumPy, SciPy |
| **Node.js** | Node 18+ (Next.js 14 App Router) | Node 18+ (Next.js Standalone build) | Node 18+ |
| **Database** | SQLite (`aiosqlite`) or PostgreSQL 15+ | Encrypted SQLite (SQLCipher) or PostgreSQL with TLS | SQLite |

### MATLAB Runtime (MCR) Configuration
1. Download and install MathWorks MATLAB Compiler Runtime (MCR) version matching compilation (e.g. `R2022b / v913`).
2. Set environment variables in `/etc/retinashield/backend.env`:
   ```bash
   MATLAB_MODE=mcr
   MCR_ROOT=/usr/local/MATLAB/MATLAB_Runtime/v913
   MATLAB_COMPILED_PACKAGE=/opt/retinashield/bin/analyze_fundus
   ```
3. When `MATLAB_MODE=engine`, the system starts the Python MATLAB engine via `import matlab.engine`.
4. When neither is installed or binary is missing, `MATLABUnavailableAdapter` produces an **explicit, uncorrupted error** rather than inventing synthetic predictions.

---

## 3. Configuration & Security Settings

Configuration is managed strictly through environment variables or `.env` files located in `backend/.env`. Keys and credentials are never stored in browser `localStorage`.

```ini
# Core Configuration
APP_NAME=RetinaShield
APP_ENV=production
DEBUG=false
DATABASE_URL=sqlite+aiosqlite:///./data/retinashield.db

# Storage Paths (Secured with POSIX 0700 permissions)
IMAGE_STORAGE_PATH=/var/lib/retinashield/images
BACKUP_STORAGE_PATH=/var/lib/retinashield/backups

# Security & Tokens
JWT_SECRET_KEY=<64-char-cryptographically-random-hex>
ACCESS_TOKEN_EXPIRE_MINUTES=480

# Operational Monitoring & Privacy
MONITORING_SMALL_CELL_THRESHOLD=5
MONITORING_LOOKBACK_DAYS=30

# Interoperability & ABDM Guardrails
ABDM_EXCHANGE_ENABLED=false
ABHA_LINKING_ENABLED=false
```

### Privacy & Data Protection Safeguards
- **Aadhaar Protection**: Full 12-digit Aadhaar numbers are **strictly prohibited** in the schema. Only optional last-4 digits are permitted.
- **ABDM Guardrails**: Live ABDM gateway calls and ABHA linking are hard-coded disabled until approved sandbox credentials, registered HIP/HIU bridge credentials, and verified consent artifacts are installed.
- **Small Cell Suppression**: The operational monitoring service automatically suppresses cells with $k < 5$ counts, returning `"< 5"` to prevent re-identification in rural PHC cohorts.

---

## 4. Backup & Disaster Recovery Procedures

### Automated Database Backup
Run the backup script or configure daily cron:
```bash
# SQLite Hot Backup
sqlite3 /var/lib/retinashield/data/retinashield.db ".backup '/var/lib/retinashield/backups/retinashield_$(date +%Y%m%d_%H%M%S).bak'"

# PostgreSQL
pg_dump -U retinashield -Fc retinashield_db > /var/lib/retinashield/backups/retinashield_$(date +%Y%m%d_%H%M%S).dump
```

### Image Storage Backup & Manifest Verification
Image storage is backed up alongside SHA-256 manifest files:
```bash
python3 backend/scripts/backup_service.py --backup-all --verify-checksums
```

### Restore Procedure
1. Stop the application services:
   ```bash
   sudo systemctl stop retinashield-backend retinashield-worker
   ```
2. Verify backup checksum integrity:
   ```bash
   sha256sum -c /var/lib/retinashield/backups/retinashield_YYYYMMDD.sha256
   ```
3. Restore database file and restart services.
4. Verify health endpoint: `curl -s http://localhost:8000/health`.

---

## 5. Model Rollback & Versioning Protocol

RetinaShield enforces **strictly immutable model provenance**. All screenings store the exact model version, classifier hash, and preprocessing pipeline ID.

> [!WARNING]
> **NO AUTOMATIC RETRAINING**
> The system **never retrains automatically** from unverified operational AI outputs or feedback loops.
> Retraining requires expert-labeled ground truth, formal offline evaluation against frozen benchmarks, and review by an institutional clinical governance committee.

### Model Rollback Steps
If a deployed model version exhibits operational anomaly or calibration drift:
1. Locate the approved previous checkpoint in `/opt/retinashield/models/provenance/`:
   ```bash
   ls -la /opt/retinashield/models/provenance/
   # Example: efficientnet_b0_dr_v1.0.0.mat (SHA-256: 4a2b9f...)
   ```
2. Update the symlink in `matlab/models/efficientnet_b0_dr.mat`:
   ```bash
   ln -sfn /opt/retinashield/models/provenance/efficientnet_b0_dr_v1.0.0.mat /opt/retinashield/models/efficientnet_b0_dr.mat
   ```
3. Restart the worker service:
   ```bash
   sudo systemctl restart retinashield-worker retinashield-backend
   ```
4. Verify the active model hash in `/api/monitoring/operational` matches the intended rollback target.

---

## 6. Offline Synchronization & Conflict Handling

The durable synchronization engine operates on an **outbox pattern** with idempotent HTTP headers and partial-upload chunk recovery.

### Conflict Resolution Invariant
- **Clinician Supremacy**: If a local screening record conflicts with a remotely modified record, the **clinician-reviewed diagnosis always takes precedence** over unreviewed or automated changes.
- Conflicts are quarantined in the `sync_conflicts` table and surfaced on the `/sync` dashboard for manual administrative review. Records are **never silently overwritten**.

---

## 7. Known System Limitations

1. **Monocular Single-Field Limitations**: Single 45° macula-centered fundus photographs can miss mid-peripheral lesions (e.g. peripheral microaneurysms, neovascularization outside the arcades).
2. **Quality Dependencies**: Dense cataracts, corneal opacities, and un-dilated pupils (< 3.5 mm) cause high ungradeable rates ($> 15\%$). The system enforces strict quality rejection to prevent false negatives.
3. **Speech Playback**: Offline TTS relies on operating system speech synthesizers (`say` on macOS, `espeak-ng` or `festival` on Linux). When native Hindi speech voices are not installed, the platform safely falls back to high-contrast on-screen text.
4. **Research Disclaimer**: All printed and exported documents prominently display: *"PROVISIONAL — AWAITING OPHTHALMOLOGIST SIGN-OFF"*.
