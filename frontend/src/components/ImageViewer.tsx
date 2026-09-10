'use client';

import React, { useState } from 'react';
import { EmptyState } from './ui/EmptyState';
import { t } from '../lib/i18n';
import type { 
  LesionDetection, 
  LesionDetectionResult, 
  OpticDisc, 
  Macula, 
  FieldOfView, 
  Vasculature,
  GradCAMExplanation 
} from '@/lib/types';

interface ImageViewerProps {
  originalPath: string;
  enhancedPath?: string;
  greenChannelPath?: string;
  lesions?: LesionDetection[];
  lesionDetectionResult?: LesionDetectionResult | null;
  opticDisc?: OpticDisc | null;
  macula?: Macula | null;
  fovea?: Macula | null;
  fieldOfView?: FieldOfView | null;
  vasculature?: Vasculature | null;
  vesselOverlayPath?: string;
  heatmapPath?: string;
  gradcamExplanation?: GradCAMExplanation | null;
  isExperimental?: boolean;
}

const LESION_COLORS: Record<string, string> = {
  microaneurysm: "#ef4444",
  hemorrhage: "#dc2626",
  hard_exudate: "#eab308",
  soft_exudate: "#f97316",
  cotton_wool_spot: "#f97316",
  neovascularization: "#a855f7",
};

export function ImageViewer({ 
  originalPath, 
  enhancedPath, 
  greenChannelPath,
  lesions = [], 
  lesionDetectionResult,
  opticDisc, 
  macula, 
  fovea,
  fieldOfView,
  vasculature,
  vesselOverlayPath, 
  heatmapPath,
  gradcamExplanation,
  isExperimental = true,
}: ImageViewerProps) {
  // Base image selection
  const [baseImage, setBaseImage] = useState<'original' | 'enhanced' | 'green'>('original');

  // Multi-layer overlay toggle controls
  const [showOpticDisc, setShowOpticDisc] = useState<boolean>(true);
  const [showFovea, setShowFovea] = useState<boolean>(true);
  const [showVessels, setShowVessels] = useState<boolean>(false);
  const [showFOV, setShowFOV] = useState<boolean>(false);
  const [showLesions, setShowLesions] = useState<boolean>(true);
  const [showHeatmap, setShowHeatmap] = useState<boolean>(true);
  const [showLegend, setShowLegend] = useState<boolean>(true);

  // Opacity sliders (0 - 100%)
  const [vesselOpacity, setVesselOpacity] = useState<number>(70);
  const [heatmapOpacity, setHeatmapOpacity] = useState<number>(60);

  // Zoom level (1.0 = 100%, max 3.0)
  const [zoomLevel, setZoomLevel] = useState<number>(1.0);

  // Active lesion detections and state
  const activeLesions = lesionDetectionResult?.detections ?? lesions ?? [];
  const isLesionUnavailable = lesionDetectionResult?.status === 'unavailable';
  const estimatedCounts = lesionDetectionResult?.model_estimated_count ?? null;

  // Resolve fovea object (supports either fovea or macula prop)
  const activeFovea = fovea || macula;
  const activeVesselPath = vesselOverlayPath || vasculature?.segmentation_mask_path;

  // Grad-CAM resolution
  const activeHeatmapPath = gradcamExplanation?.gradcam_heatmap_path || heatmapPath;
  const isGradcamAvailable = gradcamExplanation ? gradcamExplanation.status === 'available' : Boolean(activeHeatmapPath);
  const isGradcamUnavailable = gradcamExplanation ? gradcamExplanation.status === 'unavailable' || gradcamExplanation.status === 'error' : false;
  const gradcamReason = gradcamExplanation?.reason || (!activeHeatmapPath ? 'No trained classifier weights or activations available' : '');

  // Determine current base image URL
  const getBaseImageUrl = () => {
    switch (baseImage) {
      case 'enhanced': return enhancedPath || originalPath;
      case 'green': return greenChannelPath || enhancedPath || originalPath;
      case 'original':
      default:
        return originalPath;
    }
  };

  const currentImageUrl = getBaseImageUrl();

  // Helper coordinate normalization: assumes 600x400 viewbox coordinates
  const normX = (x: number | null | undefined, maxW = 600) => {
    if (x === null || x === undefined || isNaN(x)) return null;
    return x > 1 ? x : x * maxW;
  };
  const normY = (y: number | null | undefined, maxH = 400) => {
    if (y === null || y === undefined || isNaN(y)) return null;
    return y > 1 ? y : y * maxH;
  };

  const odX = normX(opticDisc?.center_x);
  const odY = normY(opticDisc?.center_y);
  const odR = opticDisc?.radius ? (opticDisc.radius > 1 ? opticDisc.radius : opticDisc.radius * 400) : 35;

  const fovX = normX(activeFovea?.center_x);
  const fovY = normY(activeFovea?.center_y);
  const fovR = activeFovea?.radius ? (activeFovea.radius > 1 ? activeFovea.radius : activeFovea.radius * 400) : 18;

  const handleZoomIn = () => setZoomLevel((z) => Math.min(3.0, +(z + 0.25).toFixed(2)));
  const handleZoomOut = () => setZoomLevel((z) => Math.max(0.75, +(z - 0.25).toFixed(2)));
  const handleZoomReset = () => setZoomLevel(1.0);

  return (
    <div className="glass-card" style={{ padding: '0', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      
      {/* 1. Prominent Experimental Warning Banner */}
      {isExperimental && (
        <div style={{
          background: '#fffbeb',
          borderBottom: '1px solid #fde68a',
          padding: '10px 16px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '8px',
          fontSize: '0.85rem',
          color: '#92400e'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{
              background: '#d97706',
              color: '#ffffff',
              padding: '2px 8px',
              borderRadius: '4px',
              fontSize: '0.72rem',
              fontWeight: 700,
              letterSpacing: '0.04em'
            }}>
              EXPERIMENTAL
            </span>
            <span>
              RetinaShield Explainability & Segmentation Suite. Grad-CAM identifies <strong>model-influential regions</strong>, not confirmed lesions or clinical proof.
            </span>
          </div>
          <span style={{ fontSize: '0.75rem', color: '#b45309', fontWeight: 600 }}>
            Research Screening Only
          </span>
        </div>
      )}

      {/* 2. Base Image Selector Strip */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: '1px solid var(--rs-border)',
        background: 'var(--rs-bg-elevated)',
        padding: '0 12px',
        overflowX: 'auto',
        gap: '12px'
      }}>
        <div style={{ display: 'flex', gap: '4px' }}>
          <button
            type="button"
            onClick={() => setBaseImage('original')}
            style={{
              padding: '10px 16px',
              border: 'none',
              background: baseImage === 'original' ? 'var(--rs-bg-card)' : 'transparent',
              color: baseImage === 'original' ? 'var(--rs-primary-dark)' : 'var(--rs-text-muted)',
              fontWeight: baseImage === 'original' ? 600 : 500,
              cursor: 'pointer',
              borderBottom: baseImage === 'original' ? '2px solid var(--rs-primary)' : '2px solid transparent',
              fontSize: '0.85rem',
              whiteSpace: 'nowrap'
            }}
          >
            {t.viewers.original}
          </button>
          <button
            type="button"
            onClick={() => setBaseImage('enhanced')}
            style={{
              padding: '10px 16px',
              border: 'none',
              background: baseImage === 'enhanced' ? 'var(--rs-bg-card)' : 'transparent',
              color: baseImage === 'enhanced' ? 'var(--rs-primary-dark)' : 'var(--rs-text-muted)',
              fontWeight: baseImage === 'enhanced' ? 600 : 500,
              cursor: 'pointer',
              borderBottom: baseImage === 'enhanced' ? '2px solid var(--rs-primary)' : '2px solid transparent',
              fontSize: '0.85rem',
              whiteSpace: 'nowrap'
            }}
          >
            {t.viewers.enhanced} (CLAHE)
          </button>
          {greenChannelPath && (
            <button
              type="button"
              onClick={() => setBaseImage('green')}
              style={{
                padding: '10px 16px',
                border: 'none',
                background: baseImage === 'green' ? 'var(--rs-bg-card)' : 'transparent',
                color: baseImage === 'green' ? 'var(--rs-primary-dark)' : 'var(--rs-text-muted)',
                fontWeight: baseImage === 'green' ? 600 : 500,
                cursor: 'pointer',
                borderBottom: baseImage === 'green' ? '2px solid var(--rs-primary)' : '2px solid transparent',
                fontSize: '0.85rem',
                whiteSpace: 'nowrap'
              }}
            >
              Green Channel
            </button>
          )}
        </div>

        {/* Zoom & Pan Toolbar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <button
            type="button"
            onClick={handleZoomOut}
            disabled={zoomLevel <= 0.75}
            title="Zoom Out"
            style={{
              padding: '4px 10px',
              background: 'var(--rs-bg-card)',
              border: '1px solid var(--rs-border)',
              borderRadius: '4px',
              fontSize: '0.8rem',
              cursor: zoomLevel <= 0.75 ? 'not-allowed' : 'pointer',
              color: 'var(--rs-text)'
            }}
          >
            −
          </button>
          <span style={{ fontSize: '0.8rem', fontWeight: 600, minWidth: '46px', textAlign: 'center' }}>
            {Math.round(zoomLevel * 100)}%
          </span>
          <button
            type="button"
            onClick={handleZoomIn}
            disabled={zoomLevel >= 3.0}
            title="Zoom In"
            style={{
              padding: '4px 10px',
              background: 'var(--rs-bg-card)',
              border: '1px solid var(--rs-border)',
              borderRadius: '4px',
              fontSize: '0.8rem',
              cursor: zoomLevel >= 3.0 ? 'not-allowed' : 'pointer',
              color: 'var(--rs-text)'
            }}
          >
            +
          </button>
          {zoomLevel !== 1.0 && (
            <button
              type="button"
              onClick={handleZoomReset}
              title="Reset Zoom"
              style={{
                padding: '4px 8px',
                background: 'transparent',
                border: '1px solid var(--rs-border)',
                borderRadius: '4px',
                fontSize: '0.75rem',
                cursor: 'pointer',
                color: 'var(--rs-primary-dark)'
              }}
            >
              Reset
            </button>
          )}
        </div>

        {/* Eye Laterality Badge */}
        {activeFovea?.inferred_laterality && (
          <div style={{
            fontSize: '0.78rem',
            color: 'var(--rs-text-muted)',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            background: 'var(--rs-bg-card)',
            padding: '4px 10px',
            borderRadius: '12px',
            border: '1px solid var(--rs-border)'
          }}>
            <span>Laterality:</span>
            <strong style={{ color: 'var(--rs-primary-dark)' }}>
              {activeFovea.inferred_laterality === 'OD' ? 'OD (Right Eye)' : activeFovea.inferred_laterality === 'OS' ? 'OS (Left Eye)' : 'Unspecified'}
            </strong>
          </div>
        )}
      </div>

      {/* 3. Multi-Layer Overlay Controls Toolbar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '12px',
        padding: '10px 16px',
        background: '#1e293b',
        color: '#f1f5f9',
        fontSize: '0.82rem',
        borderBottom: '1px solid #334155'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '14px' }}>
          <span style={{ fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', fontSize: '0.72rem', letterSpacing: '0.05em' }}>
            Layers:
          </span>

          {/* Optic Disc Toggle */}
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer', userSelect: 'none' }}>
            <input
              type="checkbox"
              checked={showOpticDisc}
              onChange={(e) => setShowOpticDisc(e.target.checked)}
              style={{ accentColor: '#10b981', cursor: 'pointer' }}
            />
            <span style={{
              color: showOpticDisc ? '#34d399' : '#94a3b8',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              fontWeight: showOpticDisc ? 600 : 400
            }}>
              <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#10b981', display: 'inline-block' }} />
              Optic Disc
            </span>
          </label>

          {/* Fovea / Macula Toggle */}
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer', userSelect: 'none' }}>
            <input
              type="checkbox"
              checked={showFovea}
              onChange={(e) => setShowFovea(e.target.checked)}
              style={{ accentColor: '#8b5cf6', cursor: 'pointer' }}
            />
            <span style={{
              color: showFovea ? '#a78bfa' : '#94a3b8',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              fontWeight: showFovea ? 600 : 400
            }}>
              <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#8b5cf6', display: 'inline-block' }} />
              Fovea
            </span>
          </label>

          {/* Retinal Vessels Toggle + Opacity Slider */}
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer', userSelect: 'none' }}>
              <input
                type="checkbox"
                checked={showVessels}
                onChange={(e) => setShowVessels(e.target.checked)}
                style={{ accentColor: '#06b6d4', cursor: 'pointer' }}
              />
              <span style={{
                color: showVessels ? '#22d3ee' : '#94a3b8',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                fontWeight: showVessels ? 600 : 400
              }}>
                <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#06b6d4', display: 'inline-block' }} />
                Vessels
              </span>
            </label>
            {showVessels && (
              <input
                type="range"
                min="10"
                max="100"
                value={vesselOpacity}
                onChange={(e) => setVesselOpacity(Number(e.target.value))}
                style={{ width: '65px', height: '4px', accentColor: '#06b6d4', cursor: 'pointer' }}
                title={`Vessel Opacity: ${vesselOpacity}%`}
              />
            )}
          </div>

          {/* Field of View (FOV) Toggle */}
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer', userSelect: 'none' }}>
            <input
              type="checkbox"
              checked={showFOV}
              onChange={(e) => setShowFOV(e.target.checked)}
              style={{ accentColor: '#3b82f6', cursor: 'pointer' }}
            />
            <span style={{
              color: showFOV ? '#60a5fa' : '#94a3b8',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              fontWeight: showFOV ? 600 : 400
            }}>
              <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#3b82f6', display: 'inline-block' }} />
              FOV
            </span>
          </label>

          {/* Lesions Toggle */}
          {(activeLesions.length > 0 || isLesionUnavailable) && (
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer', userSelect: 'none' }}>
              <input
                type="checkbox"
                checked={showLesions}
                onChange={(e) => setShowLesions(e.target.checked)}
                style={{ accentColor: '#ef4444', cursor: 'pointer' }}
              />
              <span style={{
                color: showLesions ? (isLesionUnavailable ? '#94a3b8' : '#f87171') : '#94a3b8',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                fontWeight: showLesions ? 600 : 400
              }}>
                <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: isLesionUnavailable ? '#64748b' : '#ef4444', display: 'inline-block' }} />
                {isLesionUnavailable ? 'Lesions (Unavailable)' : `Lesions (${activeLesions.length})`}
              </span>
            </label>
          )}

          {/* Grad-CAM Heatmap Toggle & Opacity Slider */}
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: isGradcamAvailable ? 'pointer' : 'default', userSelect: 'none' }}>
              <input
                type="checkbox"
                checked={showHeatmap && isGradcamAvailable}
                disabled={!isGradcamAvailable}
                onChange={(e) => setShowHeatmap(e.target.checked)}
                style={{ accentColor: '#f59e0b', cursor: isGradcamAvailable ? 'pointer' : 'not-allowed' }}
              />
              <span style={{
                color: (showHeatmap && isGradcamAvailable) ? '#fbbf24' : isGradcamAvailable ? '#94a3b8' : '#64748b',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                fontWeight: (showHeatmap && isGradcamAvailable) ? 600 : 400
              }}>
                <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: isGradcamAvailable ? '#f59e0b' : '#64748b', display: 'inline-block' }} />
                Grad-CAM {!isGradcamAvailable && '(Unavailable)'}
              </span>
            </label>
            {showHeatmap && isGradcamAvailable && (
              <input
                type="range"
                min="10"
                max="100"
                value={heatmapOpacity}
                onChange={(e) => setHeatmapOpacity(Number(e.target.value))}
                style={{ width: '65px', height: '4px', accentColor: '#f59e0b', cursor: 'pointer' }}
                title={`Grad-CAM Opacity: ${heatmapOpacity}%`}
              />
            )}
          </div>
        </div>

        {/* Legend toggle button */}
        <button
          type="button"
          onClick={() => setShowLegend(!showLegend)}
          style={{
            background: showLegend ? '#334155' : 'transparent',
            color: '#cbd5e1',
            border: '1px solid #475569',
            borderRadius: '4px',
            padding: '3px 8px',
            fontSize: '0.75rem',
            cursor: 'pointer'
          }}
        >
          {showLegend ? 'Hide Legend' : 'Show Legend'}
        </button>
      </div>

      {/* 4. Main Canvas & Overlays */}
      <div style={{
        width: '100%',
        minHeight: '440px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#0a0f1d',
        position: 'relative',
        overflow: 'auto',
        padding: '16px'
      }}>
        {currentImageUrl ? (
          <div 
            style={{ 
              position: 'relative', 
              display: 'inline-block', 
              maxWidth: '100%', 
              transform: `scale(${zoomLevel})`,
              transformOrigin: 'center center',
              transition: 'transform 0.15s ease-out'
            }}
          >
            
            {/* Base Image */}
            <img
              src={currentImageUrl}
              alt="Fundus examination"
              style={{
                display: 'block',
                maxWidth: '100%',
                maxHeight: '600px',
                objectFit: 'contain'
              }}
            />

            {/* Vessel Mask Layer */}
            {showVessels && activeVesselPath && (
              <img
                src={activeVesselPath}
                alt="Retinal vessel mask overlay"
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  height: '100%',
                  objectFit: 'contain',
                  opacity: vesselOpacity / 100,
                  mixBlendMode: 'screen',
                  pointerEvents: 'none'
                }}
              />
            )}

            {/* Grad-CAM Heatmap Layer (Real activations only) */}
            {showHeatmap && isGradcamAvailable && activeHeatmapPath && (
              <img
                src={activeHeatmapPath}
                alt="Classifier Grad-CAM activation heatmap"
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  height: '100%',
                  objectFit: 'contain',
                  opacity: heatmapOpacity / 100,
                  mixBlendMode: 'screen',
                  pointerEvents: 'none'
                }}
              />
            )}

            {/* SVG Geometric Annotation Layer */}
            <svg
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: '100%',
                pointerEvents: 'none'
              }}
              viewBox="0 0 600 400"
              preserveAspectRatio="none"
            >
              {/* Field of View (FOV) Outline */}
              {showFOV && (
                <circle
                  cx={normX(fieldOfView?.center_x) ?? 300}
                  cy={normY(fieldOfView?.center_y) ?? 200}
                  r={normX(fieldOfView?.radius) ?? 190}
                  fill="none"
                  stroke="#3b82f6"
                  strokeWidth="2.5"
                  strokeDasharray="6 4"
                  opacity="0.85"
                />
              )}

              {/* Temporal Vector OD to Fovea */}
              {showOpticDisc && showFovea && opticDisc?.detected && activeFovea?.detected && odX && odY && fovX && fovY && (
                <line
                  x1={odX}
                  y1={odY}
                  x2={fovX}
                  y2={fovY}
                  stroke="#ec4899"
                  strokeWidth="1.8"
                  strokeDasharray="4 3"
                  opacity="0.75"
                />
              )}

              {/* Optic Disc Boundary & Centroid */}
              {showOpticDisc && opticDisc?.detected && odX && odY && (
                <g>
                  <circle
                    cx={odX}
                    cy={odY}
                    r={odR}
                    fill="rgba(16, 185, 129, 0.15)"
                    stroke="#10b981"
                    strokeWidth="2.5"
                  />
                  <line x1={odX - 8} y1={odY} x2={odX + 8} y2={odY} stroke="#10b981" strokeWidth="2" />
                  <line x1={odX} y1={odY - 8} x2={odX} y2={odY + 8} stroke="#10b981" strokeWidth="2" />
                  <text
                    x={odX}
                    y={odY - odR - 6}
                    fill="#34d399"
                    fontSize="11"
                    fontWeight="600"
                    textAnchor="middle"
                    style={{ textShadow: '0 1px 3px rgba(0,0,0,0.8)' }}
                  >
                    Optic Disc {opticDisc.confidence ? `(${Math.round(opticDisc.confidence * 100)}%)` : ''}
                  </text>
                </g>
              )}

              {/* Fovea / Macula Marker */}
              {showFovea && activeFovea?.detected && fovX && fovY && (
                <g>
                  <circle
                    cx={fovX}
                    cy={fovY}
                    r={fovR}
                    fill="rgba(139, 92, 246, 0.18)"
                    stroke="#8b5cf6"
                    strokeWidth="2"
                    strokeDasharray="3 2"
                  />
                  <circle cx={fovX} cy={fovY} r="3" fill="#a78bfa" />
                  <line x1={fovX - 6} y1={fovY} x2={fovX + 6} y2={fovY} stroke="#a78bfa" strokeWidth="1.5" />
                  <line x1={fovX} y1={fovY - 6} x2={fovX} y2={fovY + 6} stroke="#a78bfa" strokeWidth="1.5" />
                  <text
                    x={fovX}
                    y={fovY + fovR + 14}
                    fill="#c4b5fd"
                    fontSize="11"
                    fontWeight="600"
                    textAnchor="middle"
                    style={{ textShadow: '0 1px 3px rgba(0,0,0,0.8)' }}
                  >
                    Fovea {activeFovea.confidence ? `(${Math.round(activeFovea.confidence * 100)}%)` : ''}
                  </text>
                </g>
              )}

              {/* Lesions Bounding Boxes */}
              {showLesions && activeLesions.map((lesion, i) => {
                const color = LESION_COLORS[lesion.lesion_type] || "#ef4444";
                const bx = normX(lesion.bbox.x_min) ?? 0;
                const by = normY(lesion.bbox.y_min) ?? 0;
                const bw = (normX(lesion.bbox.x_max) ?? 0) - bx;
                const bh = (normY(lesion.bbox.y_max) ?? 0) - by;
                const isCandidate = lesion.is_heuristic_candidate ?? false;

                return (
                  <g key={i}>
                    <rect
                      x={bx}
                      y={by}
                      width={Math.max(4, bw)}
                      height={Math.max(4, bh)}
                      fill={isCandidate ? "rgba(234, 179, 8, 0.08)" : "rgba(239, 68, 68, 0.12)"}
                      stroke={color}
                      strokeWidth={isCandidate ? "1.5" : "2"}
                      strokeDasharray={isCandidate ? "3 2" : undefined}
                    />
                    <text
                      x={bx}
                      y={Math.max(12, by - 4)}
                      fill={color}
                      fontSize="9"
                      fontWeight="bold"
                      style={{ textShadow: '0 1px 2px rgba(0,0,0,0.9)' }}
                    >
                      {isCandidate ? `[Cand] ` : ''}{lesion.lesion_type.replace('_', ' ')}
                      {lesion.confidence ? ` (${Math.round(lesion.confidence * 100)}%)` : ''}
                    </text>
                  </g>
                );
              })}
            </svg>

            {/* 5. Explicit Diagnostics and Failure Notifications */}
            <div style={{
              position: 'absolute',
              top: '12px',
              left: '12px',
              display: 'flex',
              flexDirection: 'column',
              gap: '6px',
              pointerEvents: 'none'
            }}>
              {showOpticDisc && opticDisc && !opticDisc.detected && (
                <div style={{
                  background: 'rgba(15, 23, 42, 0.85)',
                  border: '1px solid #f59e0b',
                  color: '#fef3c7',
                  padding: '4px 10px',
                  borderRadius: '6px',
                  fontSize: '0.75rem',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  backdropFilter: 'blur(4px)'
                }}>
                  <span>⚠️ Optic Disc:</span>
                  <strong>{opticDisc.failure_reason || 'Not localized / Outside FOV'}</strong>
                </div>
              )}

              {showFovea && activeFovea && !activeFovea.detected && (
                <div style={{
                  background: 'rgba(15, 23, 42, 0.85)',
                  border: '1px solid #f59e0b',
                  color: '#fef3c7',
                  padding: '4px 10px',
                  borderRadius: '6px',
                  fontSize: '0.75rem',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  backdropFilter: 'blur(4px)'
                }}>
                  <span>⚠️ Fovea:</span>
                  <strong>{activeFovea.failure_reason || 'Not localized / Outside FOV'}</strong>
                </div>
              )}

              {showLesions && isLesionUnavailable && (
                <div style={{
                  background: 'rgba(15, 23, 42, 0.85)',
                  border: '1px solid #64748b',
                  color: '#94a3b8',
                  padding: '4px 10px',
                  borderRadius: '6px',
                  fontSize: '0.75rem',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  backdropFilter: 'blur(4px)'
                }}>
                  <span>ℹ️ Lesions:</span>
                  <strong>{lesionDetectionResult?.message || 'Lesion detector unavailable (weights not loaded)'}</strong>
                </div>
              )}

              {/* Explicit Grad-CAM Unavailable Notification */}
              {isGradcamUnavailable && (
                <div style={{
                  background: 'rgba(15, 23, 42, 0.85)',
                  border: '1px solid #f59e0b',
                  color: '#fef3c7',
                  padding: '4px 10px',
                  borderRadius: '6px',
                  fontSize: '0.75rem',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  backdropFilter: 'blur(4px)'
                }}>
                  <span>ℹ️ Grad-CAM:</span>
                  <strong>{gradcamReason || 'Model explanation unavailable (untrained weights)'}</strong>
                </div>
              )}
            </div>

          </div>
        ) : (
          <div style={{ padding: '60px', width: '100%', maxWidth: '500px' }}>
            <EmptyState 
              title={t.common.modelUnavailable} 
              message="This visualization is not available. The analysis pipeline may still be processing or failed."
              icon="🔌"
            />
          </div>
        )}
      </div>

      {/* 6. Comprehensive Legend & Provenance Bar */}
      {showLegend && (
        <div style={{
          padding: '10px 16px',
          background: '#0f172a',
          borderTop: '1px solid #334155',
          fontSize: '0.78rem',
          color: '#cbd5e1',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
            {/* Grad-CAM Jet Colormap Legend */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: '240px' }}>
              <span style={{ fontWeight: 600, color: '#f59e0b' }}>Grad-CAM Activation:</span>
              <span style={{ fontSize: '0.7rem', color: '#94a3b8' }}>Low (0.0)</span>
              <div style={{
                width: '100px',
                height: '8px',
                borderRadius: '4px',
                background: 'linear-gradient(90deg, #00008f, #0000ff, #007fff, #00ffff, #7fff7f, #ffff00, #ff7f00, #ff0000, #7f0000)'
              }} />
              <span style={{ fontSize: '0.7rem', color: '#f87171' }}>High (1.0)</span>
            </div>

            {/* Anatomical Landmarks */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#10b981' }} />
                Optic Disc
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#8b5cf6' }} />
                Fovea
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#3b82f6' }} />
                FOV Boundary
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#06b6d4' }} />
                Vessels
              </span>
            </div>

            {/* Lesion Classes */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                <span style={{ width: '8px', height: '8px', background: '#ef4444' }} />
                MA
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                <span style={{ width: '8px', height: '8px', background: '#dc2626' }} />
                Hemorrhage
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                <span style={{ width: '8px', height: '8px', background: '#eab308' }} />
                Hard Exudate
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                <span style={{ width: '8px', height: '8px', background: '#f97316' }} />
                Cotton Wool
              </span>
            </div>
          </div>

          {/* Grad-CAM Provenance & Evaluation Bar */}
          {gradcamExplanation && gradcamExplanation.status === 'available' && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              flexWrap: 'wrap',
              gap: '12px',
              paddingTop: '6px',
              borderTop: '1px solid #1e293b',
              fontSize: '0.72rem',
              color: '#94a3b8'
            }}>
              <div>
                <span>Layer: <strong style={{ color: '#e2e8f0' }}>{gradcamExplanation.target_layer || 'auto'}</strong></span>
                <span style={{ margin: '0 8px' }}>•</span>
                <span>Explaining Class: <strong style={{ color: '#f59e0b' }}>{gradcamExplanation.target_class || 'Predicted'}</strong></span>
                <span style={{ margin: '0 8px' }}>•</span>
                <span>Algorithm: <strong style={{ color: '#38bdf8' }}>{gradcamExplanation.algorithm_version}</strong></span>
              </div>

              {/* Explanation localization sanity check metrics (if expert mask provided) */}
              {(gradcamExplanation.pointing_game_hit !== undefined && gradcamExplanation.pointing_game_hit !== null) && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <span>Expert Mask Check:</span>
                  <span style={{
                    color: gradcamExplanation.pointing_game_hit ? '#34d399' : '#f87171',
                    fontWeight: 600
                  }}>
                    Pointing Game: {gradcamExplanation.pointing_game_hit ? 'HIT' : 'MISS'}
                  </span>
                  {gradcamExplanation.expert_iou !== null && gradcamExplanation.expert_iou !== undefined && (
                    <span>IoU: <strong>{(gradcamExplanation.expert_iou * 100).toFixed(1)}%</strong></span>
                  )}
                  {gradcamExplanation.energy_pointing_game !== null && gradcamExplanation.energy_pointing_game !== undefined && (
                    <span>Inside Energy: <strong>{(gradcamExplanation.energy_pointing_game * 100).toFixed(1)}%</strong></span>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Clear Disclaimer */}
          <div style={{
            fontSize: '0.7rem',
            color: '#94a3b8',
            fontStyle: 'italic',
            borderTop: '1px solid #1e293b',
            paddingTop: '4px'
          }}>
            Notice: Grad-CAM reflects model activation gradients for the selected class. It does not constitute verified pathology, anatomical segmentation, or autonomous diagnosis.
          </div>
        </div>
      )}

      {/* 7. Quantitative Structure Biomarkers Bar */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
        gap: '12px',
        padding: '12px 16px',
        background: 'var(--rs-bg-card)',
        borderTop: '1px solid var(--rs-border)',
        fontSize: '0.8rem'
      }}>
        {/* Optic Disc Info */}
        <div>
          <div style={{ color: 'var(--rs-text-muted)', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Optic Disc
          </div>
          <div style={{ fontWeight: 600, marginTop: '2px', color: opticDisc?.detected ? 'var(--rs-success)' : 'var(--rs-warning)' }}>
            {opticDisc?.detected 
              ? `Detected (r=${opticDisc.radius ? Math.round(opticDisc.radius) : '—'}px)` 
              : opticDisc ? 'Outside FOV / Unreliable' : 'Unprocessed'}
          </div>
        </div>

        {/* Fovea Info */}
        <div>
          <div style={{ color: 'var(--rs-text-muted)', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Fovea / Macula
          </div>
          <div style={{ fontWeight: 600, marginTop: '2px', color: activeFovea?.detected ? '#8b5cf6' : 'var(--rs-warning)' }}>
            {activeFovea?.detected 
              ? `Localized (${activeFovea.inferred_laterality || 'Auto'})` 
              : activeFovea ? 'Not Detected / Obscured' : 'Unprocessed'}
          </div>
        </div>

        {/* Vessel Density */}
        <div>
          <div style={{ color: 'var(--rs-text-muted)', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Vessel Density
          </div>
          <div style={{ fontWeight: 600, marginTop: '2px', color: 'var(--rs-text)' }}>
            {vasculature?.vessel_density !== undefined && vasculature?.vessel_density !== null
              ? `${(vasculature.vessel_density * 100).toFixed(1)}%`
              : '—'}
          </div>
        </div>

        {/* Vessel Tortuosity */}
        <div>
          <div style={{ color: 'var(--rs-text-muted)', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Tortuosity Index
          </div>
          <div style={{ fontWeight: 600, marginTop: '2px', color: 'var(--rs-text)' }}>
            {vasculature?.tortuosity_index ? vasculature.tortuosity_index.toFixed(2) : '1.00'}
          </div>
        </div>

        {/* Algorithm Version & Reliability */}
        <div>
          <div style={{ color: 'var(--rs-text-muted)', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Algorithm Provenance
          </div>
          <div style={{ fontWeight: 600, marginTop: '2px', color: 'var(--rs-primary-dark)', fontSize: '0.78rem' }}>
            {gradcamExplanation?.algorithm_version || opticDisc?.algorithm_version || 'v1.0.0-gradcam'}
          </div>
        </div>

        {/* Model Estimated Lesion Counts */}
        <div style={{ gridColumn: 'span 2' }}>
          <div style={{ color: 'var(--rs-text-muted)', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.04em', display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span>Model Estimated Lesions</span>
            <span style={{ fontSize: '0.65rem', background: '#e2e8f0', color: '#475569', padding: '1px 4px', borderRadius: '3px' }}>Experimental</span>
          </div>
          <div style={{ fontWeight: 600, marginTop: '2px', color: isLesionUnavailable ? 'var(--rs-text-muted)' : 'var(--rs-text)', fontSize: '0.78rem' }}>
            {isLesionUnavailable ? (
              <span style={{ color: '#94a3b8' }}>Unavailable (No weights)</span>
            ) : estimatedCounts ? (
              <span style={{ display: 'inline-flex', gap: '8px', flexWrap: 'wrap' }}>
                <span style={{ color: '#ef4444' }}>MA: {estimatedCounts['microaneurysm'] ?? 0}</span>
                <span style={{ color: '#dc2626' }}>HE: {estimatedCounts['hemorrhage'] ?? 0}</span>
                <span style={{ color: '#eab308' }}>EX: {estimatedCounts['hard_exudate'] ?? 0}</span>
                <span style={{ color: '#f97316' }}>CWS: {estimatedCounts['cotton_wool_spot'] ?? estimatedCounts['soft_exudate'] ?? 0}</span>
              </span>
            ) : activeLesions.length > 0 ? (
              `${activeLesions.length} estimated candidates`
            ) : (
              'None detected'
            )}
          </div>
        </div>
      </div>

    </div>
  );
}
