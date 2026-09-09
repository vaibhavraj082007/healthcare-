'use client';

import React, { useState } from 'react';
import { EmptyState } from './ui/EmptyState';
import { t } from '../lib/i18n';
import type { LesionDetection, OpticDisc, Macula } from '@/lib/types';

interface ImageViewerProps {
  originalPath: string;
  enhancedPath?: string;
  lesions?: LesionDetection[];
  opticDisc?: OpticDisc | null;
  macula?: Macula | null;
  vesselOverlayPath?: string;
  heatmapPath?: string;
}

const LESION_COLORS: Record<string, string> = {
  microaneurysm: "#ef4444",
  hemorrhage: "#dc2626",
  hard_exudate: "#eab308",
  soft_exudate: "#f97316",
  neovascularization: "#a855f7",
};

export function ImageViewer({ 
  originalPath, 
  enhancedPath, 
  lesions = [], 
  opticDisc, 
  macula, 
  vesselOverlayPath, 
  heatmapPath 
}: ImageViewerProps) {
  const [activeTab, setActiveTab] = useState<'original' | 'enhanced' | 'lesion' | 'vessel' | 'heatmap'>('original');

  const tabs = [
    { id: 'original', label: t.viewers.original },
    { id: 'enhanced', label: t.viewers.enhanced },
    { id: 'lesion', label: t.viewers.lesion },
    { id: 'vessel', label: t.viewers.vessel },
    { id: 'heatmap', label: t.viewers.heatmap },
  ] as const;

  const getImagePathForTab = (tabId: string) => {
    switch (tabId) {
      case 'original': return originalPath;
      case 'enhanced': return enhancedPath;
      case 'lesion': return enhancedPath || originalPath; // Render overlays on top
      case 'vessel': return vesselOverlayPath;
      case 'heatmap': return heatmapPath;
      default: return undefined;
    }
  };

  const currentPath = getImagePathForTab(activeTab);
  const showAnnotations = activeTab === 'lesion';

  return (
    <div className="glass-card" style={{ padding: '0', overflow: 'hidden' }}>
      <div style={{ display: 'flex', borderBottom: '1px solid var(--rs-border)', background: 'var(--rs-bg-elevated)', overflowX: 'auto' }}>
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as any)}
            style={{
              padding: '12px 20px',
              border: 'none',
              background: activeTab === tab.id ? 'var(--rs-bg-card)' : 'transparent',
              color: activeTab === tab.id ? 'var(--rs-primary-dark)' : 'var(--rs-text-muted)',
              fontWeight: activeTab === tab.id ? 600 : 500,
              cursor: 'pointer',
              borderBottom: activeTab === tab.id ? '2px solid var(--rs-primary)' : '2px solid transparent',
              whiteSpace: 'nowrap'
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>
      
      <div style={{ width: '100%', minHeight: '400px', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#0f172a', position: 'relative' }}>
        {currentPath ? (
          <div style={{ position: 'relative', display: 'inline-block', maxWidth: '100%', maxHeight: '600px' }}>
            <img src={currentPath} alt={`${activeTab} view`} style={{ display: 'block', maxWidth: '100%', maxHeight: '600px', objectFit: 'contain' }} />
            
            {showAnnotations && (
              <svg
                style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', pointerEvents: 'none' }}
                viewBox="0 0 100 100" 
                preserveAspectRatio="none"
                // Assuming SVG overlay coordinates are pre-calculated to image size in a real app, 
                // for this shell we simulate it using percentage or assume a fixed viewBox. 
                // Using 100x100 and percentage coords is a common hack if exact dims aren't known.
              >
                {/* Simulated annotations for the shell */}
                {lesions.map((lesion, i) => {
                  const color = LESION_COLORS[lesion.lesion_type] || "#ef4444";
                  return (
                    <rect
                      key={i}
                      x={lesion.bbox.x_min}
                      y={lesion.bbox.y_min}
                      width={lesion.bbox.x_max - lesion.bbox.x_min}
                      height={lesion.bbox.y_max - lesion.bbox.y_min}
                      fill="none"
                      stroke={color}
                      strokeWidth="2"
                    />
                  );
                })}
              </svg>
            )}
          </div>
        ) : (
          <div style={{ padding: '60px', width: '100%', maxWidth: '500px' }}>
            <EmptyState 
              title={t.common.modelUnavailable} 
              message="This visualization is not available. The model service may be disconnected or processing failed."
              icon="🔌"
            />
          </div>
        )}
      </div>
    </div>
  );
}
