# RetinaShield 🛡️

> **RESEARCH SCREENING PROTOTYPE** — All outputs are research screening results, NOT autonomous clinical diagnoses. Must be reviewed by a qualified ophthalmologist.

Explainable diabetic retinopathy (DR) screening for rural Indian primary healthcare centres.

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌─────────────────────────────┐
│  Next.js UI  │────▶│  FastAPI API  │────▶│   MATLAB Pipeline            │
│  (React/TS)  │◀────│  (Python)    │◀────│   ┌─ IQA (BRISQUE)          │
└──────────────┘     │              │     │   ├─ Enhancement (CLAHE)     │
                     │              │────▶│   ├─ Structure Segmentation  │
                     │              │◀────│   ├─ EfficientNet-B0 (DR)   │
                     │              │     │   └─ Grad-CAM               │
                     │              │     └─────────────────────────────┘
                     │              │     ┌──────────────┐
                     │              │────▶│  YOLOv8      │
                     │              │◀────│  (Lesions)   │
                     └──────┬───────┘     └──────────────┘
                            │
                     ┌──────▼───────┐
                     │  PostgreSQL  │
                     │  + Image     │
                     │    Storage   │
                     └──────────────┘
```

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | Next.js 15 + React + TypeScript | Screening UI, reports, image viewer |
| **Backend** | FastAPI + SQLAlchemy | REST API, DB, image management |
| **MATLAB Core** | MATLAB R2023b+ | IQA, enhancement, segmentation, EfficientNet-B0, Grad-CAM |
| **Lesion Detection** | YOLOv8 (Python) | Microaneurysm, hemorrhage, exudate detection |
| **Database** | PostgreSQL 16 | Patient records, screening results |
| **Offline** | Facility Service + SQLite | Local processing at centres without connectivity |

## Quick Start

```bash
# 1. Clone and setup
chmod +x scripts/setup_dev.sh
./scripts/setup_dev.sh

# 2. Start backend
cd backend && source venv/bin/activate
uvicorn app.main:app --reload

# 3. Start frontend (new terminal)
cd frontend && npm run dev

# 4. Open browser
open http://localhost:3000       # UI
open http://localhost:8000/docs  # API docs
```

## Project Structure

```
├── matlab/         # MATLAB analysis pipeline (IQA, enhance, segment, classify, Grad-CAM)
├── backend/        # FastAPI server (API, DB, MATLAB bridge, YOLOv8 service)
├── frontend/       # Next.js web interface (dashboard, screening, reports)
├── facility/       # Offline facility processing service
├── shared/         # Shared schemas (JSON Schema, severity codes)
└── scripts/        # Setup, dataset download, test image generation
```

## Current Status

| Component | Status |
|-----------|--------|
| Project structure | ✅ Complete |
| Shared schemas | ✅ Complete |
| MATLAB pipeline (.m files) | ✅ Code ready — **requires MATLAB installation** |
| FastAPI backend | ✅ Skeleton complete — requires PostgreSQL |
| Next.js frontend | ✅ Skeleton complete with components |
| Facility service | ✅ Skeleton complete |
| EfficientNet-B0 weights | ❌ Untrained — requires dataset |
| YOLOv8 weights | ❌ Untrained — requires dataset |

## Blockers

1. **MATLAB not installed** — Pipeline code is written but cannot execute. Python fallback provides basic IQA and enhancement.
2. **No dataset** — Models are untrained. All outputs clearly labelled as `UNTRAINED`.
3. **No PostgreSQL** — Install via `brew install postgresql@16` or use Docker Compose.

## License

Research prototype — not licensed for clinical use.
