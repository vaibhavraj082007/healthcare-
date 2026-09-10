'use client';

import React, { useState, useEffect, useRef } from 'react';
import { reviewsApi } from '@/lib/api';
import type { ReportRead, VoicePlaybackResponse } from '@/lib/types';

interface ReportViewerModalProps {
  screeningId: string;
  isOpen: boolean;
  onClose: () => void;
  canSign?: boolean;
}

export default function ReportViewerModal({
  screeningId,
  isOpen,
  onClose,
  canSign = false,
}: ReportViewerModalProps) {
  const [activeTab, setActiveTab] = useState<'technical' | 'patient'>('technical');
  const [language, setLanguage] = useState<'en' | 'hi'>('en');
  const [loading, setLoading] = useState<boolean>(false);
  const [generating, setGenerating] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const [currentReport, setCurrentReport] = useState<ReportRead | null>(null);
  const [reportsList, setReportsList] = useState<ReportRead[]>([]);

  // Voice playback state
  const [voiceConsent, setVoiceConsent] = useState<boolean>(false);
  const [voiceLoading, setVoiceLoading] = useState<boolean>(false);
  const [voiceResult, setVoiceResult] = useState<VoicePlaybackResponse | null>(null);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Load existing reports
  useEffect(() => {
    if (!isOpen || !screeningId) return;

    const loadReports = async () => {
      setLoading(true);
      setError(null);
      try {
        const list = await reviewsApi.listReports(screeningId);
        setReportsList(list);
        if (list.length > 0) {
          setCurrentReport(list[0]);
        } else {
          setCurrentReport(null);
        }
      } catch (err: any) {
        console.error('Failed to load reports:', err);
      } finally {
        setLoading(false);
      }
    };

    loadReports();
  }, [isOpen, screeningId]);

  // Handle generating a new report
  const handleGenerate = async (reportType: 'technical_report' | 'patient_summary', lang: 'en' | 'hi', sign: boolean) => {
    setGenerating(true);
    setError(null);
    try {
      const rep = await reviewsApi.generateReport(screeningId, {
        report_type: reportType,
        language: lang,
        is_signed: sign,
      });
      setCurrentReport(rep);
      setReportsList(prev => [rep, ...prev.filter(r => r.id !== rep.id)]);
      setVoiceResult(null);
      setIsPlaying(false);
    } catch (err: any) {
      setError(err?.message || 'Failed to generate report.');
    } finally {
      setGenerating(false);
    }
  };

  // Handle Voice Playback (Offline local TTS with fallback)
  const handleVoicePlayback = async () => {
    if (!currentReport) return;
    if (!voiceConsent) {
      setError('Please provide consent for audio playback.');
      return;
    }

    setVoiceLoading(true);
    setError(null);
    try {
      const res = await reviewsApi.synthesizeVoice(screeningId, currentReport.id, {
        voice_consent: true,
        language,
      });
      setVoiceResult(res);

      if (res.audio_base64) {
        // Play backend synthesized audio
        const audioSrc = `data:${res.audio_format || 'audio/wav'};base64,${res.audio_base64}`;
        if (!audioRef.current) {
          audioRef.current = new Audio(audioSrc);
        } else {
          audioRef.current.src = audioSrc;
        }
        audioRef.current.onended = () => setIsPlaying(false);
        await audioRef.current.play();
        setIsPlaying(true);
      } else if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
        // Browser client-side SpeechSynthesis fallback
        const utterance = new SpeechSynthesisUtterance(res.spoken_text);
        utterance.lang = language === 'hi' ? 'hi-IN' : 'en-US';
        utterance.onend = () => setIsPlaying(false);
        window.speechSynthesis.speak(utterance);
        setIsPlaying(true);
      }
    } catch (err: any) {
      setError(err?.message || 'Voice playback failed.');
    } finally {
      setVoiceLoading(false);
    }
  };

  const handleStopVoice = () => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    setIsPlaying(false);
  };

  if (!isOpen) return null;

  const summary = currentReport?.summary_json || {};
  const isProvisional = currentReport?.status !== 'signed';

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(15, 23, 42, 0.75)',
        backdropFilter: 'blur(4px)',
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px',
      }}
    >
      <div
        style={{
          backgroundColor: '#ffffff',
          borderRadius: '16px',
          width: '100%',
          maxWidth: '900px',
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
          border: '1px solid #e2e8f0',
          overflow: 'hidden',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '18px 24px',
            borderBottom: '1px solid #e2e8f0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: '#f8fafc',
          }}
        >
          <div>
            <h2 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 700, color: '#0f172a' }}>
              📄 Clinical Reports & Patient Summaries
            </h2>
            <p style={{ margin: '2px 0 0 0', fontSize: '0.82rem', color: '#64748b' }}>
              Deterministic, rule-based clinical reports with zero LLM hallucination risk
            </p>
          </div>
          <button
            onClick={onClose}
            style={{
              border: 'none',
              background: 'transparent',
              fontSize: '1.4rem',
              cursor: 'pointer',
              color: '#94a3b8',
              padding: '4px 8px',
            }}
          >
            ✕
          </button>
        </div>

        {/* Provisional Banner if not signed */}
        {isProvisional && (
          <div
            style={{
              padding: '10px 24px',
              backgroundColor: '#fef2f2',
              borderBottom: '1px solid #fecaca',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              fontSize: '0.85rem',
              color: '#991b1b',
            }}
          >
            <div>
              <strong>⚠️ PROVISIONAL — UNVERIFIED SCREENING RESULT</strong>
              <span style={{ marginLeft: '8px', opacity: 0.9 }}>
                Awaiting final ophthalmologist review & sign-off.
              </span>
            </div>
            {canSign && (
              <button
                onClick={() => handleGenerate(activeTab === 'technical' ? 'technical_report' : 'patient_summary', language, true)}
                disabled={generating}
                style={{
                  padding: '6px 14px',
                  backgroundColor: '#16a34a',
                  color: '#ffffff',
                  borderRadius: '6px',
                  border: 'none',
                  fontSize: '0.8rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Approve & Sign Report
              </button>
            )}
          </div>
        )}

        {/* Navigation Tabs & Actions Bar */}
        <div
          style={{
            padding: '12px 24px',
            borderBottom: '1px solid #e2e8f0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '12px',
          }}
        >
          {/* Tabs */}
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={() => {
                setActiveTab('technical');
                handleGenerate('technical_report', 'en', false);
              }}
              style={{
                padding: '8px 16px',
                borderRadius: '8px',
                border: 'none',
                fontWeight: 600,
                fontSize: '0.88rem',
                cursor: 'pointer',
                backgroundColor: activeTab === 'technical' ? '#0284c7' : '#f1f5f9',
                color: activeTab === 'technical' ? '#ffffff' : '#475569',
              }}
            >
              🔬 Technical Report
            </button>
            <button
              onClick={() => {
                setActiveTab('patient');
                handleGenerate('patient_summary', language, false);
              }}
              style={{
                padding: '8px 16px',
                borderRadius: '8px',
                border: 'none',
                fontWeight: 600,
                fontSize: '0.88rem',
                cursor: 'pointer',
                backgroundColor: activeTab === 'patient' ? '#0284c7' : '#f1f5f9',
                color: activeTab === 'patient' ? '#ffffff' : '#475569',
              }}
            >
              👤 Patient Summary
            </button>
          </div>

          {/* Language Selector (for patient summary) & PDF Export */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            {activeTab === 'patient' && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.85rem' }}>
                <span style={{ color: '#64748b' }}>Language:</span>
                <select
                  value={language}
                  onChange={(e) => {
                    const l = e.target.value as 'en' | 'hi';
                    setLanguage(l);
                    handleGenerate('patient_summary', l, false);
                  }}
                  style={{
                    padding: '6px 10px',
                    borderRadius: '6px',
                    border: '1px solid #cbd5e1',
                    fontSize: '0.85rem',
                    background: '#ffffff',
                  }}
                >
                  <option value="en">English</option>
                  <option value="hi">हिन्दी (Hindi)</option>
                </select>
              </div>
            )}

            {currentReport && (
              <a
                href={reviewsApi.getPdfUrl(screeningId, currentReport.id)}
                target="_blank"
                rel="noreferrer"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '7px 14px',
                  borderRadius: '6px',
                  backgroundColor: '#0f172a',
                  color: '#ffffff',
                  fontSize: '0.82rem',
                  fontWeight: 600,
                  textDecoration: 'none',
                }}
              >
                📥 Download PDF
              </a>
            )}
          </div>
        </div>

        {/* Content Area */}
        <div style={{ padding: '20px 24px', overflowY: 'auto', flex: 1 }}>
          {error && (
            <div style={{ padding: '10px 14px', backgroundColor: '#fef2f2', color: '#b91c1c', borderRadius: '8px', marginBottom: '16px', fontSize: '0.85rem' }}>
              {error}
            </div>
          )}

          {generating && (
            <div style={{ textAlign: 'center', padding: '40px', color: '#64748b' }}>
              Generating deterministic report...
            </div>
          )}

          {!generating && currentReport && activeTab === 'technical' && (
            <div>
              {/* Quality & Findings Card */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
                <div style={{ border: '1px solid #e2e8f0', borderRadius: '10px', padding: '14px', background: '#f8fafc' }}>
                  <h4 style={{ margin: '0 0 8px 0', fontSize: '0.85rem', color: '#0369a1', textTransform: 'uppercase' }}>
                    Image Quality Assessment
                  </h4>
                  <div style={{ fontSize: '0.85rem', lineHeight: 1.6 }}>
                    <strong>Verdict:</strong> {String(summary?.image_quality?.verdict || 'unknown').toUpperCase()}<br />
                    <strong>Sharpness Score:</strong> {summary?.image_quality?.sharpness ?? '—'}<br />
                    <strong>Signal-to-Noise:</strong> {summary?.image_quality?.snr_db ? `${summary.image_quality.snr_db} dB` : '—'}
                  </div>
                </div>

                <div style={{ border: '1px solid #e2e8f0', borderRadius: '10px', padding: '14px', background: '#f8fafc' }}>
                  <h4 style={{ margin: '0 0 8px 0', fontSize: '0.85rem', color: '#0369a1', textTransform: 'uppercase' }}>
                    Clinician Review
                  </h4>
                  <div style={{ fontSize: '0.85rem', lineHeight: 1.6 }}>
                    <strong>Confirmed Grade:</strong> {summary?.clinician_review?.confirmed_dr_label || 'Awaiting Review'}<br />
                    <strong>Reviewer:</strong> {summary?.clinician_review?.reviewer_name || 'Pending Sign-Off'}<br />
                    <strong>Referral:</strong> {summary?.clinician_review?.referral_recommendation || 'None'}
                  </div>
                </div>
              </div>

              {/* AI Findings */}
              <div style={{ border: '1px solid #e2e8f0', borderRadius: '10px', padding: '16px', marginBottom: '16px' }}>
                <div style={{ fontWeight: 700, fontSize: '0.9rem', color: '#4338ca', marginBottom: '8px' }}>
                  AI-GENERATED RESEARCH SCREENING RESULT (SECONDARY SUPPORT ONLY)
                </div>
                <p style={{ margin: '0 0 12px 0', fontSize: '0.78rem', color: '#64748b' }}>
                  {summary?.ai_research_screening_findings?.disclaimer}
                </p>

                <div style={{ fontSize: '0.85rem', marginBottom: '12px' }}>
                  <strong>Predicted Grade:</strong> {summary?.ai_research_screening_findings?.predicted_dr_label} (Confidence: {((summary?.ai_research_screening_findings?.confidence || 0) * 100).toFixed(1)}%)
                </div>

                {/* Probabilities Bars */}
                {summary?.ai_research_screening_findings?.calibrated_probabilities && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {Object.entries(summary.ai_research_screening_findings.calibrated_probabilities).map(([key, val]: any) => (
                      <div key={key} style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '0.8rem' }}>
                        <span style={{ width: '130px', color: '#475569' }}>{key.replace('_', ' ')}</span>
                        <div style={{ flex: 1, height: '8px', background: '#e2e8f0', borderRadius: '4px', overflow: 'hidden' }}>
                          <div style={{ width: `${(val * 100).toFixed(0)}%`, height: '100%', background: '#6366f1' }} />
                        </div>
                        <span style={{ width: '45px', textAlign: 'right', fontWeight: 600 }}>{(val * 100).toFixed(0)}%</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Model Provenance */}
              <div style={{ border: '1px solid #e2e8f0', borderRadius: '10px', padding: '12px 16px', background: '#f8fafc', fontSize: '0.8rem', color: '#64748b' }}>
                <strong>Model Architecture:</strong> {summary?.ai_research_screening_findings?.model_provenance?.classifier_architecture} ·{' '}
                <strong>Lesion Model:</strong> {summary?.ai_research_screening_findings?.model_provenance?.detector_architecture} ·{' '}
                <strong>Pipeline:</strong> {summary?.ai_research_screening_findings?.model_provenance?.matlab_engine_adapter}
              </div>
            </div>
          )}

          {!generating && currentReport && activeTab === 'patient' && (
            <div>
              {/* Patient Friendly Findings Card */}
              <div style={{ border: '1px solid #bae6fd', borderRadius: '12px', padding: '18px', background: '#f0f9ff', marginBottom: '16px' }}>
                <h3 style={{ margin: '0 0 6px 0', fontSize: '1.05rem', color: '#0369a1' }}>
                  {summary.title || 'Retinal Screening Summary for Patient'}
                </h3>
                <div style={{ fontSize: '1rem', fontWeight: 700, color: '#0f172a', marginBottom: '8px' }}>
                  {summary.grade_label}
                </div>
                <p style={{ margin: 0, fontSize: '0.92rem', color: '#334155', lineHeight: 1.6 }}>
                  {summary.findings_explanation}
                </p>
              </div>

              {/* Clinician Next Step */}
              <div style={{ border: '1px solid #bbf7d0', borderRadius: '12px', padding: '18px', background: '#f0fdf4', marginBottom: '16px' }}>
                <h4 style={{ margin: '0 0 6px 0', fontSize: '0.95rem', color: '#15803d' }}>
                  {summary.next_step_heading || 'Clinician-Approved Next Steps'}
                </h4>
                <p style={{ margin: '0 0 6px 0', fontSize: '0.92rem', color: '#166534', fontWeight: 600 }}>
                  {summary.referral_guidance}
                </p>
                <div style={{ fontSize: '0.85rem', color: '#475569' }}>
                  Recommended follow-up interval: Within {summary.follow_up_months || 12} months
                </div>
              </div>

              {/* Screening Limitations */}
              <div style={{ border: '1px solid #fef08a', borderRadius: '10px', padding: '14px', background: '#fffbeb', marginBottom: '16px', fontSize: '0.82rem', color: '#854d0e', lineHeight: 1.5 }}>
                {summary.screening_limitations}
              </div>

              {/* Translation governance notice if Hindi */}
              {language === 'hi' && (
                <div style={{ padding: '8px 12px', borderRadius: '6px', background: '#f8fafc', border: '1px solid #e2e8f0', fontSize: '0.78rem', color: '#64748b', marginBottom: '16px' }}>
                  ℹ️ <strong>अनुवाद स्थिति:</strong> यह सारांश <i>pending_qualified_clinical_review</i> चिह्नित है। योग्य नैदानिक अनुवादक द्वारा सत्यापन आवश्यक है।
                </div>
              )}

              {/* Offline Voice Playback Controller */}
              <div style={{ border: '1px solid #e2e8f0', borderRadius: '12px', padding: '16px', background: '#f8fafc' }}>
                <h4 style={{ margin: '0 0 8px 0', fontSize: '0.9rem', color: '#0f172a' }}>
                  🔊 Offline Voice Playback (Local TTS)
                </h4>
                <p style={{ margin: '0 0 10px 0', fontSize: '0.8rem', color: '#64748b' }}>
                  Plays back the patient summary using local on-device speech tools without sending patient data to third-party cloud services.
                </p>

                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                  <input
                    type="checkbox"
                    id="voiceConsent"
                    checked={voiceConsent}
                    onChange={(e) => setVoiceConsent(e.target.checked)}
                  />
                  <label htmlFor="voiceConsent" style={{ fontSize: '0.85rem', color: '#334155', cursor: 'pointer' }}>
                    I consent to voice playback using local on-device speech tools.
                  </label>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <button
                    onClick={handleVoicePlayback}
                    disabled={voiceLoading || !voiceConsent}
                    style={{
                      padding: '8px 16px',
                      backgroundColor: voiceConsent ? '#2563eb' : '#94a3b8',
                      color: '#ffffff',
                      borderRadius: '6px',
                      border: 'none',
                      fontSize: '0.85rem',
                      fontWeight: 600,
                      cursor: voiceConsent ? 'pointer' : 'not-allowed',
                    }}
                  >
                    {voiceLoading ? 'Synthesizing...' : isPlaying ? 'Restart Audio' : '▶️ Listen to Summary'}
                  </button>

                  {isPlaying && (
                    <button
                      onClick={handleStopVoice}
                      style={{
                        padding: '8px 14px',
                        backgroundColor: '#ef4444',
                        color: '#ffffff',
                        borderRadius: '6px',
                        border: 'none',
                        fontSize: '0.85rem',
                        fontWeight: 600,
                        cursor: 'pointer',
                      }}
                    >
                      ⏹ Stop
                    </button>
                  )}
                </div>

                {voiceResult?.fallback_to_text && (
                  <div style={{ marginTop: '10px', fontSize: '0.8rem', color: '#d97706' }}>
                    ⚠️ {voiceResult.status_message}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '12px 24px',
            borderTop: '1px solid #e2e8f0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: '#f8fafc',
            fontSize: '0.75rem',
            color: '#64748b',
          }}
        >
          <span>RetinaShield AI Decision Support Platform · Deterministic Templates</span>
          <button
            onClick={onClose}
            style={{
              padding: '6px 14px',
              borderRadius: '6px',
              border: '1px solid #cbd5e1',
              backgroundColor: '#ffffff',
              fontSize: '0.82rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
