"""
RetinaShield — Pydantic Schemas Package
"""

from app.schemas.patient import PatientCreate, PatientRead, PatientUpdate
from app.schemas.screening import (
    ScreeningCreate,
    ScreeningRead,
    ScreeningSummary,
    AnalysisRequest,
    AnalysisResponse,
)
from app.schemas.analysis_result import (
    AnalysisResult,
    QualityAssessment,
    SeverityClassification,
    GradCAMExplanation,
    ConfidenceCalibration,
    ConsistencyAnalysis,
    ReferralRecommendation,
)
from app.schemas.evaluation import (
    MetricWithCI,
    PerClassMetric,
    ConfusionMatrixData,
    EvaluationReport,
)
from app.schemas.auth import (
    Token,
    TokenPayload,
    LoginRequest,
    UserCreate,
    UserRead,
    UserRoleUpdate,
    UserStatusUpdate,
)
from app.schemas.consent import (
    ConsentCreate,
    ConsentRead,
    ConsentWithdraw,
)
from app.schemas.clinical import (
    ClinicianReviewCreate,
    ClinicianReviewRead,
    ReportCreate,
    ReportRead,
    AuditEventRead,
)

__all__ = [
    "PatientCreate",
    "PatientRead",
    "PatientUpdate",
    "ScreeningCreate",
    "ScreeningRead",
    "ScreeningSummary",
    "AnalysisRequest",
    "AnalysisResponse",
    "AnalysisResult",
    "QualityAssessment",
    "SeverityClassification",
    "GradCAMExplanation",
    "ConfidenceCalibration",
    "ConsistencyAnalysis",
    "ReferralRecommendation",
    "MetricWithCI",
    "PerClassMetric",
    "ConfusionMatrixData",
    "EvaluationReport",
    "Token",
    "TokenPayload",
    "LoginRequest",
    "UserCreate",
    "UserRead",
    "UserRoleUpdate",
    "UserStatusUpdate",
    "ConsentCreate",
    "ConsentRead",
    "ConsentWithdraw",
    "ClinicianReviewCreate",
    "ClinicianReviewRead",
    "ReportCreate",
    "ReportRead",
    "AuditEventRead",
]
