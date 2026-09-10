'use client';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { ImageViewer } from '@/components/ImageViewer';
import { ConsistencyPanel } from '@/components/ConsistencyPanel';
import { GradCAMOverlay } from '@/components/GradCAMOverlay';
import { t } from '@/lib/i18n';
import React from 'react';
import type {
  ConfidenceCalibration,
  ConsistencyAnalysis,
  LesionDetectionResult,
  GradCAMExplanation,
} from '@/lib/types';

export default function ScreeningResults({ params }: { params: { id: string } }) {
  // ─── Mock data representing a full analysis result ───────────────────────
  // In production this is fetched from /api/analysis/{params.id}

  const calibration: ConfidenceCalibration = {
    status: 'calibrated',
    temperature: 1.42,
    max_calibrated_probability: 0.71,
    confidence_margin: 0.55,
    shannon_entropy: 0.28,
    is_uncertain: false,
  };

  const consistency: ConsistencyAnalysis = {
    consistency_status: 'concordant',
    finding_label: 'Concordant AI findings',
    human_review_required: false,
    review_reasons: [],
    recommended_grade: 2,
    recommended_urgency: 'priority',
    rules_version: '1.0.0',
  };

  const classProbabilities = [0.08, 0.10, 0.71, 0.09, 0.02];

  const result = {
    patientId: 'PAT-9821',
    date: 'Oct 14, 2026',
    quality: 'acceptable',
    severity: 2,
    severityLabel: 'Moderate NPDR',
    urgency: 'priority',
    imageOriginal: 'https://images.unsplash.com/photo-1579684385127-1ef15d508118?auto=format&fit=crop&w=800&q=80',
    imageEnhanced: 'https://images.unsplash.com/photo-1579684385127-1ef15d508118?auto=format&fit=crop&w=800&q=80',
    opticDisc: {
      detected: true,
      center_x: 180,
      center_y: 200,
      radius: 42,
      confidence: 0.89,
      is_reliable: true,
      algorithm_version: 'v0.2.0-classical',
    },
    fovea: {
      detected: true,
      center_x: 390,
      center_y: 215,
      radius: 18,
      confidence: 0.82,
      is_reliable: true,
      inferred_laterality: 'OD' as const,
      algorithm_version: 'v0.2.0-classical',
    },
    fieldOfView: {
      center_x: 300,
      center_y: 200,
      radius: 190,
      area_ratio: 0.885,
      is_reliable: true,
    },
    vasculature: {
      vessel_density: 0.092,
      tortuosity_index: 1.14,
      caliber_proxy: 1.25,
      is_reliable: true,
    },
    lesions: [
      { lesion_type: 'microaneurysm' as const, bbox: { x_min: 240, y_min: 160, x_max: 260, y_max: 180 }, confidence: 0.95, approximate_extent: { area_pixels: 400, equivalent_diameter: 22.56 } },
      { lesion_type: 'hard_exudate' as const, bbox: { x_min: 340, y_min: 170, x_max: 375, y_max: 200 }, confidence: 0.88, approximate_extent: { area_pixels: 1050, equivalent_diameter: 36.56 } },
    ],
    lesionDetectionResult: {
      model: 'yolov8x-retina-tiles-v0.2.0',
      status: 'ready' as const,
      message: 'High-resolution tiled inference complete',
      detections: [
        { lesion_type: 'microaneurysm' as const, bbox: { x_min: 240, y_min: 160, x_max: 260, y_max: 180 }, confidence: 0.95, approximate_extent: { area_pixels: 400, equivalent_diameter: 22.56 } },
        { lesion_type: 'hard_exudate' as const, bbox: { x_min: 340, y_min: 170, x_max: 375, y_max: 200 }, confidence: 0.88, approximate_extent: { area_pixels: 1050, equivalent_diameter: 36.56 } },
      ],
      model_estimated_count: { microaneurysm: 1, hemorrhage: 0, hard_exudate: 1, cotton_wool_spot: 0 },
      model_trained: true,
    } satisfies LesionDetectionResult,
  };

  const gradcamExplanation: GradCAMExplanation = {
    status: 'available',
    reason: '',
    gradcam_heatmap_path: 'https://images.unsplash.com/photo-1579684385127-1ef15d508118?auto=format&fit=crop&w=800&q=80',
    gradcam_overlay_path: 'https://images.unsplash.com/photo-1579684385127-1ef15d508118?auto=format&fit=crop&w=800&q=80',
    target_layer: 'top_conv',
    target_class: 'Moderate NPDR',
    predicted_class: 'Moderate NPDR',
    algorithm_version: '1.0.0-gradcam',
    disclaimer: 'Grad-CAM shows model-influential regions, not confirmed lesions or proof that a prediction is correct.',
    preprocessing_transform: {
      original_size: [2136, 3216],
      model_input_size: [224, 224],
      scale_factor_h: 0.1048,
      scale_factor_w: 0.0696,
    },
    pointing_game_hit: true,
    expert_iou: 0.46,
    energy_pointing_game: 0.68,
  };

  const gradeColor = ['var(--rs-grade-0)','var(--rs-grade-1)','var(--rs-grade-2)','var(--rs-grade-3)','var(--rs-grade-4)'];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      {/* ── Page header ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ fontSize: '1.8rem', color: 'var(--rs-primary-dark)' }}>{t.results.title}</h1>
          <p style={{ color: 'var(--rs-text-muted)' }}>
            Patient: {result.patientId} • Screened: {result.date}
          </p>
        </div>
        <Button onClick={() => window.print()}>Print Report</Button>
      </div>

      {/* ── KPI cards ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '20px' }}>
        <Card style={{ borderTop: `4px solid ${gradeColor[result.severity]}` }}>
          <h3 style={{ color: 'var(--rs-text-muted)', fontSize: '0.9rem' }}>{t.results.severity}</h3>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, color: gradeColor[result.severity] }}>
            {result.severityLabel}
          </div>
        </Card>
        <Card style={{ borderTop: `4px solid ${gradeColor[result.severity]}` }}>
          <h3 style={{ color: 'var(--rs-text-muted)', fontSize: '0.9rem' }}>{t.results.urgency}</h3>
          <div style={{ marginTop: '8px' }}>
            <span className="urgency-tag priority">Priority Referral (3 Months)</span>
          </div>
        </Card>
        <Card style={{ borderTop: '4px solid var(--rs-grade-0)' }}>
          <h3 style={{ color: 'var(--rs-text-muted)', fontSize: '0.9rem' }}>{t.results.quality}</h3>
          <div style={{ marginTop: '8px' }}>
            <span className="severity-badge grade-0">Acceptable</span>
          </div>
        </Card>
      </div>

      {/* ── Image viewer with multi-layer overlays (Grad-CAM, Lesions, Anatomical) ── */}
      <Card>
        <ImageViewer
          originalPath={result.imageOriginal}
          enhancedPath={result.imageEnhanced}
          opticDisc={result.opticDisc}
          fovea={result.fovea}
          fieldOfView={result.fieldOfView}
          vasculature={result.vasculature}
          lesions={result.lesions}
          lesionDetectionResult={result.lesionDetectionResult}
          gradcamExplanation={gradcamExplanation}
          isExperimental={true}
        />
      </Card>

      {/* ── Classifier Grad-CAM Deep Dive ── */}
      <Card>
        <GradCAMOverlay
          explanation={gradcamExplanation}
          originalUrl={result.imageOriginal}
          predictedClass={result.severityLabel}
          modelTrained={true}
        />
      </Card>

      {/* ── Consistency Analysis Panel ── */}
      <Card>
        <h2 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: '16px', color: 'var(--rs-primary-dark)' }}>
          AI Engine Consistency Analysis
          <span
            style={{
              marginLeft: '10px',
              fontSize: '0.72rem',
              padding: '2px 7px',
              borderRadius: '4px',
              background: 'rgba(234,179,8,0.15)',
              color: '#ca8a04',
              fontWeight: 600,
              border: '1px solid rgba(234,179,8,0.3)',
              verticalAlign: 'middle',
            }}
          >
            EXPERIMENTAL
          </span>
        </h2>
        <ConsistencyPanel
          consistency={consistency}
          calibration={calibration}
          classProbabilities={classProbabilities}
        />
      </Card>
    </div>
  );
}
