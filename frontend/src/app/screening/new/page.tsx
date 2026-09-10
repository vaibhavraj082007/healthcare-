'use client';

import React, { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { RecaptureGuidance } from '@/components/RecaptureGuidance';
import {
  Patient,
  PatientCreate,
  Screening,
  UploadImageResponse,
  JobReadResponse,
  AnalysisResult,
  QualityAssessmentDetail,
} from '@/lib/types';
import {
  patientsApi,
  consentApi,
  screeningsApi,
  jobsApi,
} from '@/lib/api';

interface EyeEncounterState {
  currentUpload: UploadImageResponse | null;
  history: UploadImageResponse[];
  activeJob: JobReadResponse | null;
  isUploading: boolean;
  isSubmitting: boolean;
  error: string | null;
  fileInputKey: number;
}

const initialEyeState: EyeEncounterState = {
  currentUpload: null,
  history: [],
  activeJob: null,
  isUploading: false,
  isSubmitting: false,
  error: null,
  fileInputKey: 0,
};

export default function NewScreeningPage() {
  const router = useRouter();

  // Step state
  const [currentStep, setCurrentStep] = useState<1 | 2 | 3>(1);

  // Patient Find & Registration state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Patient[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null);
  const [showNewPatientForm, setShowNewPatientForm] = useState(false);
  const [isCreatingPatient, setIsCreatingPatient] = useState(false);
  const [patientForm, setPatientForm] = useState<PatientCreate>({
    first_name: '',
    last_name: '',
    gender: 'female',
    date_of_birth: '',
    phone: '',
    diabetes_type: 'Type 2',
    diabetes_duration_years: 5,
  });

  // Consent & Encounter state
  const [consentGranted, setConsentGranted] = useState(false);
  const [screenerName, setScreenerName] = useState('Staff Health Worker');
  const [isCreatingEncounter, setIsCreatingEncounter] = useState(false);
  const [activeScreening, setActiveScreening] = useState<Screening | null>(null);

  // Per-Eye Separation State
  const [activeTabEye, setActiveTabEye] = useState<'right' | 'left'>('right');
  const [odState, setOdState] = useState<EyeEncounterState>(initialEyeState);
  const [osState, setOsState] = useState<EyeEncounterState>(initialEyeState);

  // Polling timers
  const odPollingRef = useRef<NodeJS.Timeout | null>(null);
  const osPollingRef = useRef<NodeJS.Timeout | null>(null);

  // Search patients on query change
  useEffect(() => {
    if (!searchQuery.trim()) {
      setSearchResults([]);
      return;
    }
    const timer = setTimeout(async () => {
      setIsSearching(true);
      try {
        const res = await patientsApi.list({ search: searchQuery.trim(), limit: 8 });
        setSearchResults(res);
      } catch (err) {
        console.error('Patient search error:', err);
      } finally {
        setIsSearching(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Clean up polling intervals on unmount
  useEffect(() => {
    return () => {
      if (odPollingRef.current) clearInterval(odPollingRef.current);
      if (osPollingRef.current) clearInterval(osPollingRef.current);
    };
  }, []);

  // Handler: Register New Patient
  const handleRegisterPatient = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!patientForm.first_name.trim() || !patientForm.last_name.trim()) return;
    setIsCreatingPatient(true);
    try {
      const created = await patientsApi.create(patientForm);
      setSelectedPatient(created);
      setShowNewPatientForm(false);
      setSearchQuery('');
    } catch (err: any) {
      alert(`Failed to register patient: ${err.message}`);
    } finally {
      setIsCreatingPatient(false);
    }
  };

  // Handler: Start Screening Encounter
  const handleStartEncounter = async () => {
    if (!selectedPatient) return;
    if (!consentGranted) {
      alert('Patient informed consent must be recorded prior to screening under the DPDP Act 2023.');
      return;
    }
    setIsCreatingEncounter(true);
    try {
      // 1. Record Consent
      await consentApi.record({
        patient_id: selectedPatient.id,
        consent_type: 'screening',
        granted: true,
        obtained_by_name: screenerName,
      });

      // 2. Create Screening Record
      const encounter = await screeningsApi.create({
        patient_id: selectedPatient.id,
        eye: 'both',
        screener_name: screenerName,
      });

      setActiveScreening(encounter);
      setCurrentStep(2);
    } catch (err: any) {
      alert(`Could not start encounter: ${err.message}`);
    } finally {
      setIsCreatingEncounter(false);
    }
  };

  // Helper to get / set state for an eye
  const getEyeState = (eye: 'right' | 'left') => (eye === 'right' ? odState : osState);
  const setEyeState = (eye: 'right' | 'left', updater: (prev: EyeEncounterState) => EyeEncounterState) => {
    if (eye === 'right') setOdState(updater);
    else setOsState(updater);
  };

  // Handler: Upload Smartphone + 20D Condensing Lens Photo
  const handleFileUpload = async (eye: 'right' | 'left', file: File) => {
    if (!activeScreening) return;

    // Validate file type
    const validTypes = ['image/jpeg', 'image/png', 'image/tiff', 'image/jpg'];
    if (!validTypes.includes(file.type.toLowerCase())) {
      setEyeState(eye, (prev) => ({
        ...prev,
        error: `Unsupported file format (${file.type || 'unknown'}). Please upload a valid JPEG or PNG image.`,
      }));
      return;
    }

    setEyeState(eye, (prev) => ({ ...prev, isUploading: true, error: null }));

    try {
      const resp = await screeningsApi.uploadImage(
        activeScreening.id,
        eye,
        file,
        '20D_condensing',
        'Smartphone + 20D Condensing Lens'
      );

      setEyeState(eye, (prev) => {
        // If there was a prior upload, add it to history to preserve recapture history immutably
        const newHistory = prev.currentUpload ? [prev.currentUpload, ...prev.history] : prev.history;
        return {
          ...prev,
          currentUpload: resp,
          history: newHistory,
          isUploading: false,
          error: null,
          activeJob: null, // reset active job for new capture
        };
      });
    } catch (err: any) {
      setEyeState(eye, (prev) => ({
        ...prev,
        isUploading: false,
        error: err.message || 'Image upload failed. Ensure server connection is active.',
      }));
    }
  };

  // Handler: Acknowledge & Recapture (Preserves history)
  const handleAcknowledgeRecapture = (eye: 'right' | 'left') => {
    setEyeState(eye, (prev) => ({
      ...prev,
      history: prev.currentUpload ? [prev.currentUpload, ...prev.history] : prev.history,
      currentUpload: null,
      activeJob: null,
      error: null,
      fileInputKey: prev.fileInputKey + 1,
    }));
  };

  // Handler: Submit for Background Inference Job
  const handleSubmitJob = async (eye: 'right' | 'left') => {
    const state = getEyeState(eye);
    if (!activeScreening || !state.currentUpload) return;

    setEyeState(eye, (prev) => ({ ...prev, isSubmitting: true, error: null }));

    // Deterministic idempotency key per image upload
    const idempKey = `screening_${activeScreening.id}_${state.currentUpload.image_id}`;

    try {
      const job = await jobsApi.submit({
        screening_id: activeScreening.id,
        image_id: state.currentUpload.image_id,
        run_matlab: true,
        run_yolo: true,
        timeout_seconds: 240,
        idempotency_key: idempKey,
      });

      setEyeState(eye, (prev) => ({ ...prev, activeJob: job, isSubmitting: false }));
      startJobPolling(eye, job.id);
    } catch (err: any) {
      setEyeState(eye, (prev) => ({
        ...prev,
        isSubmitting: false,
        error: `Submission failed: ${err.message}`,
      }));
    }
  };

  // Start polling background job status
  const startJobPolling = (eye: 'right' | 'left', jobId: string) => {
    const ref = eye === 'right' ? odPollingRef : osPollingRef;
    if (ref.current) clearInterval(ref.current);

    ref.current = setInterval(async () => {
      try {
        const job = await jobsApi.get(jobId);
        setEyeState(eye, (prev) => ({ ...prev, activeJob: job }));

        if (job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled') {
          if (ref.current) {
            clearInterval(ref.current);
            ref.current = null;
          }
        }
      } catch (err: any) {
        console.error('Job polling error:', err);
      }
    }, 1500);
  };

  // Handler: Cancel Active Job
  const handleCancelJob = async (eye: 'right' | 'left') => {
    const state = getEyeState(eye);
    if (!state.activeJob) return;
    try {
      await jobsApi.cancel(state.activeJob.id);
      setEyeState(eye, (prev) => ({
        ...prev,
        activeJob: prev.activeJob ? { ...prev.activeJob, status: 'cancelled' } : null,
      }));
      const ref = eye === 'right' ? odPollingRef : osPollingRef;
      if (ref.current) {
        clearInterval(ref.current);
        ref.current = null;
      }
    } catch (err: any) {
      alert(`Could not cancel job: ${err.message}`);
    }
  };

  // Patient-Level Overall Referral Determination
  const calculatePatientReferral = () => {
    const odResult = odState.activeJob?.result;
    const osResult = osState.activeJob?.result;

    const odUrgency = odResult?.referral_recommendation?.urgency || 'none';
    const osUrgency = osResult?.referral_recommendation?.urgency || 'none';

    const urgencyRank: Record<string, number> = {
      urgent: 4,
      priority: 3,
      routine: 2,
      none: 1,
    };

    const maxRank = Math.max(urgencyRank[odUrgency] || 1, urgencyRank[osUrgency] || 1);
    const overallUrgency =
      Object.keys(urgencyRank).find((k) => urgencyRank[k] === maxRank) || 'none';

    return {
      urgency: overallUrgency,
      odUrgency,
      osUrgency,
      hasBoth: Boolean(odResult && osResult),
    };
  };

  const patientReferral = calculatePatientReferral();

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', paddingBottom: '60px' }}>
      {/* Header Banner */}
      <div style={{ marginBottom: '28px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h1 style={{ fontSize: '2rem', color: 'var(--rs-primary-dark)', margin: 0, fontWeight: 800 }}>
              Clinical DR Screening Encounter
            </h1>
            <p style={{ color: 'var(--rs-text-muted)', margin: '6px 0 0', fontSize: '0.95rem' }}>
              Tele-ophthalmology point-of-care workflow for primary healthcare workers.
            </p>
          </div>
          {/* Hardware Configuration Badge */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              background: '#f0fdf4',
              border: '1px solid #bbf7d0',
              padding: '8px 14px',
              borderRadius: '999px',
              fontSize: '0.85rem',
              color: '#166534',
              fontWeight: 600,
            }}
          >
            <span>📱 + 🔍</span>
            <span>Smartphone + 20D Condensing Lens (Validated Setup)</span>
          </div>
        </div>

        {/* Step Indicator */}
        <div style={{ display: 'flex', gap: '16px', marginTop: '20px' }}>
          <div
            style={{
              flex: 1,
              padding: '10px 16px',
              borderRadius: '8px',
              background: currentStep === 1 ? 'var(--rs-primary)' : '#f3f4f6',
              color: currentStep === 1 ? '#fff' : '#6b7280',
              fontWeight: 700,
              fontSize: '0.9rem',
              transition: 'all 0.2s',
            }}
          >
            1. Patient & Consent
          </div>
          <div
            style={{
              flex: 1,
              padding: '10px 16px',
              borderRadius: '8px',
              background: currentStep === 2 ? 'var(--rs-primary)' : '#f3f4f6',
              color: currentStep === 2 ? '#fff' : '#6b7280',
              fontWeight: 700,
              fontSize: '0.9rem',
              transition: 'all 0.2s',
            }}
          >
            2. Per-Eye 20D Imaging & IQA
          </div>
          <div
            style={{
              flex: 1,
              padding: '10px 16px',
              borderRadius: '8px',
              background: currentStep === 3 ? 'var(--rs-primary)' : '#f3f4f6',
              color: currentStep === 3 ? '#fff' : '#6b7280',
              fontWeight: 700,
              fontSize: '0.9rem',
              transition: 'all 0.2s',
            }}
          >
            3. Review & Patient Referral
          </div>
        </div>
      </div>

      {/* ===================================================================== */}
      {/* STEP 1: Patient Search, Registration & Consent */}
      {/* ===================================================================== */}
      {currentStep === 1 && (
        <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '24px' }}>
          <Card>
            <h2 style={{ fontSize: '1.25rem', marginBottom: '16px', color: 'var(--rs-primary-dark)' }}>
              1. Patient Identification
            </h2>

            {selectedPatient ? (
              <div
                style={{
                  background: '#f8fafc',
                  border: '1px solid #e2e8f0',
                  borderRadius: '10px',
                  padding: '18px',
                  marginBottom: '20px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <h3 style={{ margin: 0, fontSize: '1.15rem', color: '#0f172a' }}>
                      {selectedPatient.first_name} {selectedPatient.last_name}
                    </h3>
                    <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: '0.88rem' }}>
                      ID: {selectedPatient.id.substring(0, 8)}... | Gender: {selectedPatient.gender || 'Not recorded'} | Phone: {selectedPatient.phone || 'None'}
                    </p>
                    <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: '0.88rem' }}>
                      Diabetes: {selectedPatient.diabetes_type || 'Unknown'} ({selectedPatient.diabetes_duration_years || 0} yrs)
                    </p>
                  </div>
                  <Button variant="secondary" onClick={() => setSelectedPatient(null)} style={{ fontSize: '0.8rem' }}>
                    Change
                  </Button>
                </div>
              </div>
            ) : (
              <div>
                {!showNewPatientForm ? (
                  <>
                    <label className="form-label">Search Registered Patients</label>
                    <input
                      type="text"
                      className="form-input"
                      placeholder="Search by first or last name..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      style={{ marginBottom: '12px' }}
                    />

                    {isSearching && <p style={{ color: '#64748b', fontSize: '0.85rem' }}>Searching registry...</p>}

                    {searchResults.length > 0 && (
                      <div
                        style={{
                          border: '1px solid #e2e8f0',
                          borderRadius: '8px',
                          maxHeight: '220px',
                          overflowY: 'auto',
                          marginBottom: '16px',
                        }}
                      >
                        {searchResults.map((p) => (
                          <div
                            key={p.id}
                            onClick={() => setSelectedPatient(p)}
                            style={{
                              padding: '10px 14px',
                              borderBottom: '1px solid #f1f5f9',
                              cursor: 'pointer',
                              display: 'flex',
                              justifyContent: 'space-between',
                              alignItems: 'center',
                            }}
                            onMouseEnter={(e) => (e.currentTarget.style.background = '#f8fafc')}
                            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                          >
                            <div>
                              <strong>
                                {p.first_name} {p.last_name}
                              </strong>
                              <span style={{ marginLeft: '8px', fontSize: '0.8rem', color: '#64748b' }}>
                                {p.phone || 'No phone'}
                              </span>
                            </div>
                            <span style={{ fontSize: '0.8rem', color: 'var(--rs-primary)', fontWeight: 600 }}>Select →</span>
                          </div>
                        ))}
                      </div>
                    )}

                    <div style={{ textAlign: 'center', marginTop: '16px' }}>
                      <p style={{ fontSize: '0.85rem', color: '#64748b', marginBottom: '8px' }}>Not found in registry?</p>
                      <Button variant="secondary" onClick={() => setShowNewPatientForm(true)}>
                        + Register New Patient (Minimal DPDP Details)
                      </Button>
                    </div>
                  </>
                ) : (
                  <form onSubmit={handleRegisterPatient}>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '12px' }}>
                      <div>
                        <label className="form-label">First Name *</label>
                        <input
                          type="text"
                          required
                          className="form-input"
                          value={patientForm.first_name}
                          onChange={(e) => setPatientForm({ ...patientForm, first_name: e.target.value })}
                        />
                      </div>
                      <div>
                        <label className="form-label">Last Name *</label>
                        <input
                          type="text"
                          required
                          className="form-input"
                          value={patientForm.last_name}
                          onChange={(e) => setPatientForm({ ...patientForm, last_name: e.target.value })}
                        />
                      </div>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '12px' }}>
                      <div>
                        <label className="form-label">Gender</label>
                        <select
                          className="form-input"
                          value={patientForm.gender || 'female'}
                          onChange={(e) => setPatientForm({ ...patientForm, gender: e.target.value })}
                        >
                          <option value="female">Female</option>
                          <option value="male">Male</option>
                          <option value="other">Other</option>
                        </select>
                      </div>
                      <div>
                        <label className="form-label">Phone (Optional)</label>
                        <input
                          type="tel"
                          className="form-input"
                          placeholder="10-digit mobile"
                          value={patientForm.phone || ''}
                          onChange={(e) => setPatientForm({ ...patientForm, phone: e.target.value })}
                        />
                      </div>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '16px' }}>
                      <div>
                        <label className="form-label">Diabetes Type</label>
                        <select
                          className="form-input"
                          value={patientForm.diabetes_type || 'Type 2'}
                          onChange={(e) => setPatientForm({ ...patientForm, diabetes_type: e.target.value })}
                        >
                          <option value="Type 2">Type 2</option>
                          <option value="Type 1">Type 1</option>
                          <option value="Gestational">Gestational</option>
                          <option value="Pre-diabetes">Pre-diabetes</option>
                        </select>
                      </div>
                      <div>
                        <label className="form-label">Duration (Years)</label>
                        <input
                          type="number"
                          min="0"
                          max="80"
                          className="form-input"
                          value={patientForm.diabetes_duration_years || 0}
                          onChange={(e) =>
                            setPatientForm({ ...patientForm, diabetes_duration_years: parseInt(e.target.value) || 0 })
                          }
                        />
                      </div>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                      <Button variant="secondary" onClick={() => setShowNewPatientForm(false)}>
                        Cancel
                      </Button>
                      <Button type="submit" isLoading={isCreatingPatient}>
                        Save & Select
                      </Button>
                    </div>
                  </form>
                )}
              </div>
            )}
          </Card>

          {/* Consent & Screener Details */}
          <Card>
            <h2 style={{ fontSize: '1.25rem', marginBottom: '16px', color: 'var(--rs-primary-dark)' }}>
              2. Informed Consent & Operator
            </h2>

            <div style={{ marginBottom: '16px' }}>
              <label className="form-label">Screening Health Worker Name</label>
              <input
                type="text"
                className="form-input"
                value={screenerName}
                onChange={(e) => setScreenerName(e.target.value)}
              />
            </div>

            <div
              style={{
                background: '#f8fafc',
                border: '1px solid #e2e8f0',
                borderRadius: '8px',
                padding: '14px',
                marginBottom: '20px',
              }}
            >
              <label style={{ display: 'flex', gap: '12px', alignItems: 'flex-start', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={consentGranted}
                  onChange={(e) => setConsentGranted(e.target.checked)}
                  style={{ marginTop: '4px', width: '18px', height: '18px' }}
                />
                <span style={{ fontSize: '0.88rem', color: '#334155', lineHeight: '1.4' }}>
                  <strong>DPDP Act 2023 Informed Consent:</strong> The patient has been informed that retinal photographs
                  will be captured using a smartphone mounted to a 20D condensing lens for AI-assisted diabetic retinopathy
                  screening and review by a tele-ophthalmologist.
                </span>
              </label>
            </div>

            <Button
              onClick={handleStartEncounter}
              disabled={!selectedPatient || !consentGranted}
              isLoading={isCreatingEncounter}
              style={{ width: '100%', padding: '12px' }}
            >
              Proceed to 20D Lens Imaging →
            </Button>
          </Card>
        </div>
      )}

      {/* ===================================================================== */}
      {/* STEP 2: Per-Eye Smartphone + 20D Condensing Lens Ingestion & IQA */}
      {/* ===================================================================== */}
      {currentStep === 2 && activeScreening && (
        <div>
          {/* Patient Overview Bar */}
          <div
            style={{
              background: '#f8fafc',
              border: '1px solid #e2e8f0',
              borderRadius: '10px',
              padding: '12px 20px',
              marginBottom: '20px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <div>
              <span style={{ fontSize: '0.85rem', color: '#64748b' }}>Active Screening Encounter:</span>
              <strong style={{ marginLeft: '8px', color: '#0f172a' }}>
                {selectedPatient?.first_name} {selectedPatient?.last_name} (ID: {activeScreening.id.substring(0, 8)})
              </strong>
            </div>
            <div style={{ display: 'flex', gap: '10px' }}>
              <Button variant="secondary" onClick={() => setCurrentStep(1)} style={{ fontSize: '0.8rem' }}>
                ← Edit Patient
              </Button>
              <Button
                onClick={() => setCurrentStep(3)}
                disabled={!odState.activeJob?.result && !osState.activeJob?.result}
                style={{ fontSize: '0.8rem' }}
              >
                View Patient Summary →
              </Button>
            </div>
          </div>

          {/* Eye Selection Tabs */}
          <div style={{ display: 'flex', gap: '12px', marginBottom: '20px' }}>
            <button
              onClick={() => setActiveTabEye('right')}
              style={{
                flex: 1,
                padding: '14px',
                borderRadius: '10px',
                border: activeTabEye === 'right' ? '2px solid var(--rs-primary)' : '1px solid #e2e8f0',
                background: activeTabEye === 'right' ? '#eff6ff' : '#fff',
                cursor: 'pointer',
                textAlign: 'left',
                transition: 'all 0.2s',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 800, fontSize: '1.1rem', color: activeTabEye === 'right' ? 'var(--rs-primary)' : '#334155' }}>
                  Right Eye (OD)
                </span>
                <span
                  style={{
                    fontSize: '0.75rem',
                    padding: '2px 8px',
                    borderRadius: '999px',
                    background: odState.activeJob?.status === 'completed' ? '#dcfce7' : odState.currentUpload ? '#fef3c7' : '#f1f5f9',
                    color: odState.activeJob?.status === 'completed' ? '#166534' : odState.currentUpload ? '#92400e' : '#64748b',
                    fontWeight: 700,
                  }}
                >
                  {odState.activeJob?.status === 'completed'
                    ? `Grade ${odState.activeJob.result?.severity_classification?.predicted_grade ?? 'Done'}`
                    : odState.currentUpload
                    ? 'Image Captured'
                    : 'Awaiting Capture'}
                </span>
              </div>
              <p style={{ margin: '4px 0 0', fontSize: '0.82rem', color: '#64748b' }}>
                {odState.history.length > 0 ? `${odState.history.length} capture(s) in history` : 'No captures yet'}
              </p>
            </button>

            <button
              onClick={() => setActiveTabEye('left')}
              style={{
                flex: 1,
                padding: '14px',
                borderRadius: '10px',
                border: activeTabEye === 'left' ? '2px solid var(--rs-primary)' : '1px solid #e2e8f0',
                background: activeTabEye === 'left' ? '#eff6ff' : '#fff',
                cursor: 'pointer',
                textAlign: 'left',
                transition: 'all 0.2s',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 800, fontSize: '1.1rem', color: activeTabEye === 'left' ? 'var(--rs-primary)' : '#334155' }}>
                  Left Eye (OS)
                </span>
                <span
                  style={{
                    fontSize: '0.75rem',
                    padding: '2px 8px',
                    borderRadius: '999px',
                    background: osState.activeJob?.status === 'completed' ? '#dcfce7' : osState.currentUpload ? '#fef3c7' : '#f1f5f9',
                    color: osState.activeJob?.status === 'completed' ? '#166534' : osState.currentUpload ? '#92400e' : '#64748b',
                    fontWeight: 700,
                  }}
                >
                  {osState.activeJob?.status === 'completed'
                    ? `Grade ${osState.activeJob.result?.severity_classification?.predicted_grade ?? 'Done'}`
                    : osState.currentUpload
                    ? 'Image Captured'
                    : 'Awaiting Capture'}
                </span>
              </div>
              <p style={{ margin: '4px 0 0', fontSize: '0.82rem', color: '#64748b' }}>
                {osState.history.length > 0 ? `${osState.history.length} capture(s) in history` : 'No captures yet'}
              </p>
            </button>
          </div>

          {/* Active Eye Working Panel */}
          {(() => {
            const eye = activeTabEye;
            const eyeLabel = eye === 'right' ? 'Right Eye (OD)' : 'Left Eye (OS)';
            const state = getEyeState(eye);

            return (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
                {/* Left Panel: Camera Ingestion & Quality Feedback */}
                <div>
                  <Card>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
                      <h3 style={{ margin: 0, fontSize: '1.15rem', color: '#0f172a' }}>
                        {eyeLabel} Image Capture
                      </h3>
                      <span style={{ fontSize: '0.78rem', color: '#64748b' }}>
                        Rig: Smartphone + 20D Lens
                      </span>
                    </div>

                    {/* Upload / Capture Box */}
                    <div
                      style={{
                        border: '2px dashed #cbd5e1',
                        borderRadius: '12px',
                        padding: '28px 16px',
                        textAlign: 'center',
                        background: state.currentUpload ? '#f8fafc' : '#ffffff',
                        marginBottom: '18px',
                      }}
                    >
                      {state.currentUpload ? (
                        <div>
                          <span style={{ fontSize: '2.5rem' }}>📸</span>
                          <h4 style={{ margin: '8px 0 4px', fontSize: '1rem', color: '#0f172a' }}>
                            {state.currentUpload.original_filename}
                          </h4>
                          <p style={{ margin: 0, fontSize: '0.82rem', color: '#64748b' }}>
                            {state.currentUpload.width}×{state.currentUpload.height} px | Lens: {state.currentUpload.lens_type}
                          </p>
                          <div style={{ marginTop: '14px' }}>
                            <Button
                              variant="secondary"
                              onClick={() => handleAcknowledgeRecapture(eye)}
                              style={{ fontSize: '0.82rem' }}
                            >
                              🔄 Recapture New Image (Retains Prior in History)
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <div>
                          <span style={{ fontSize: '2.5rem', opacity: 0.7 }}>📱</span>
                          <p style={{ margin: '8px 0 2px', fontWeight: 600, color: '#334155', fontSize: '0.95rem' }}>
                            Upload Smartphone 20D Retinal Image
                          </p>
                          <p style={{ margin: '0 0 14px', fontSize: '0.82rem', color: '#64748b' }}>
                            Ensure phone camera is aligned through 20D condensing lens (~5 cm working distance)
                          </p>
                          <label className="btn-primary" style={{ display: 'inline-block', cursor: 'pointer', padding: '8px 18px', fontSize: '0.88rem' }}>
                            {state.isUploading ? 'Uploading & Analyzing IQA...' : 'Select 20D Fundus Photo'}
                            <input
                              key={state.fileInputKey}
                              type="file"
                              accept="image/jpeg,image/png,image/tiff"
                              style={{ display: 'none' }}
                              onChange={(e) => {
                                const file = e.target.files?.[0];
                                if (file) handleFileUpload(eye, file);
                              }}
                            />
                          </label>
                        </div>
                      )}
                    </div>

                    {state.error && (
                      <div style={{ background: '#fee2e2', color: '#991b1b', padding: '10px', borderRadius: '8px', marginBottom: '14px', fontSize: '0.85rem' }}>
                        {state.error}
                      </div>
                    )}

                    {/* Immediate 20D Optical Quality Assessment Card */}
                    {state.currentUpload && (
                      <RecaptureGuidance
                        quality={state.currentUpload.quality_assessment}
                        eyeLabel={eyeLabel}
                        onAcknowledgeRecapture={() => handleAcknowledgeRecapture(eye)}
                      />
                    )}

                    {/* Recapture History Integrity View */}
                    {state.history.length > 0 && (
                      <div style={{ marginTop: '16px', borderTop: '1px solid #e2e8f0', paddingTop: '12px' }}>
                        <h4 style={{ margin: '0 0 8px', fontSize: '0.85rem', color: '#64748b', fontWeight: 600 }}>
                          Preserved Recapture History for {eyeLabel} ({state.history.length}):
                        </h4>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                          {state.history.map((hist, idx) => (
                            <div
                              key={hist.image_id}
                              style={{
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                                padding: '6px 10px',
                                background: '#f1f5f9',
                                borderRadius: '6px',
                                fontSize: '0.8rem',
                                color: '#475569',
                              }}
                            >
                              <span>
                                Attempt #{state.history.length - idx}: {hist.original_filename} ({hist.width}×{hist.height})
                              </span>
                              <span style={{ fontWeight: 600, textTransform: 'capitalize' }}>
                                Quality: {hist.quality_assessment.overall_quality}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </Card>
                </div>

                {/* Right Panel: Inference Job & Provisional Findings */}
                <div>
                  <Card>
                    <h3 style={{ margin: '0 0 14px', fontSize: '1.15rem', color: '#0f172a' }}>
                      {eyeLabel} AI Inference & Findings
                    </h3>

                    {!state.activeJob ? (
                      <div style={{ textAlign: 'center', padding: '30px 16px' }}>
                        <p style={{ color: '#64748b', fontSize: '0.9rem', marginBottom: '18px' }}>
                          {state.currentUpload
                            ? 'Image is ready. Dispatch to the background MATLAB inference worker.'
                            : 'Upload a 20D condensing lens image first to enable AI analysis.'}
                        </p>
                        <Button
                          onClick={() => handleSubmitJob(eye)}
                          disabled={!state.currentUpload || state.isSubmitting}
                          isLoading={state.isSubmitting}
                        >
                          Submit {eyeLabel} for AI Analysis →
                        </Button>
                      </div>
                    ) : (
                      <div>
                        {/* Job Status Banner */}
                        <div
                          style={{
                            padding: '14px',
                            borderRadius: '8px',
                            background:
                              state.activeJob.status === 'completed'
                                ? '#f0fdf4'
                                : state.activeJob.status === 'running'
                                ? '#eff6ff'
                                : state.activeJob.status === 'failed'
                                ? '#fef2f2'
                                : '#fefce8',
                            border: `1px solid ${
                              state.activeJob.status === 'completed'
                                ? '#bbf7d0'
                                : state.activeJob.status === 'running'
                                ? '#bfdbfe'
                                : state.activeJob.status === 'failed'
                                ? '#fecaca'
                                : '#fef08a'
                            }`,
                            marginBottom: '18px',
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div>
                              <strong style={{ textTransform: 'capitalize', fontSize: '1rem' }}>
                                Status: {state.activeJob.status}
                              </strong>
                              <p style={{ margin: '2px 0 0', fontSize: '0.82rem', color: '#64748b' }}>
                                Job ID: {state.activeJob.id.substring(0, 8)}... | Retries: {state.activeJob.retry_count}/{state.activeJob.max_retries}
                              </p>
                            </div>
                            {state.activeJob.status === 'running' && (
                              <Button variant="secondary" onClick={() => handleCancelJob(eye)} style={{ fontSize: '0.8rem' }}>
                                Cancel
                              </Button>
                            )}
                            {state.activeJob.status === 'failed' && (
                              <Button onClick={() => handleSubmitJob(eye)} style={{ fontSize: '0.8rem' }}>
                                🔄 Retry Analysis
                              </Button>
                            )}
                          </div>

                          {state.activeJob.status === 'running' && (
                            <div style={{ marginTop: '10px' }}>
                              <p style={{ fontSize: '0.82rem', color: '#1e40af', margin: 0 }}>
                                ⏳ Executing MATLAB pipeline: IQA → Enhancement → Structure segmentation → EfficientNet classification...
                              </p>
                            </div>
                          )}

                          {state.activeJob.error_message && (
                            <p style={{ margin: '8px 0 0', fontSize: '0.85rem', color: '#b91c1c' }}>
                              Error: {state.activeJob.error_message}
                            </p>
                          )}
                        </div>

                        {/* Completed Provisional Findings */}
                        {state.activeJob.status === 'completed' && state.activeJob.result && (
                          <div>
                            <div
                              style={{
                                background: '#f8fafc',
                                border: '1px solid #e2e8f0',
                                borderRadius: '10px',
                                padding: '16px',
                                marginBottom: '16px',
                              }}
                            >
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                                <span style={{ fontSize: '0.85rem', color: '#64748b' }}>Provisional DR Severity Grade:</span>
                                <span
                                  style={{
                                    fontSize: '1rem',
                                    fontWeight: 800,
                                    color:
                                      state.activeJob.result.severity_classification?.predicted_grade === 0
                                        ? '#15803d'
                                        : state.activeJob.result.severity_classification?.predicted_grade &&
                                          state.activeJob.result.severity_classification.predicted_grade >= 2
                                        ? '#b91c1c'
                                        : '#b45309',
                                  }}
                                >
                                  Grade {state.activeJob.result.severity_classification?.predicted_grade}:{' '}
                                  {state.activeJob.result.severity_classification?.grade_label || 'Unknown'}
                                </span>
                              </div>

                              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', fontSize: '0.85rem' }}>
                                <div>
                                  <span style={{ color: '#64748b' }}>Confidence:</span>{' '}
                                  <strong>
                                    {Math.round(
                                      (state.activeJob.result.severity_classification?.confidence || 0) * 100
                                    )}
                                    %
                                  </strong>
                                </div>
                                <div>
                                  <span style={{ color: '#64748b' }}>Referral:</span>{' '}
                                  <strong style={{ textTransform: 'uppercase' }}>
                                    {state.activeJob.result.referral_recommendation?.urgency || 'None'}
                                  </strong>
                                </div>
                                <div>
                                  <span style={{ color: '#64748b' }}>Consistency:</span>{' '}
                                  <strong>
                                    {state.activeJob.result.consistency_analysis?.finding_label || 'Concordant AI findings'}
                                  </strong>
                                </div>
                                <div>
                                  <span style={{ color: '#64748b' }}>Total Latency:</span>{' '}
                                  <strong>
                                    {state.activeJob.timings?.total_ms || state.activeJob.result.processing_time_seconds
                                      ? `${state.activeJob.timings?.total_ms || Math.round((state.activeJob.result.processing_time_seconds || 0) * 1000)}ms`
                                      : 'N/A'}
                                  </strong>
                                </div>
                              </div>
                            </div>

                            {/* Clinical Safety Notice */}
                            <div
                              style={{
                                background: '#fffbeb',
                                border: '1px solid #fef3c7',
                                padding: '10px 14px',
                                borderRadius: '8px',
                                fontSize: '0.8rem',
                                color: '#92400e',
                              }}
                            >
                              <strong>Review Status:</strong> Provisional AI Screening Result — Pending Tele-Ophthalmologist Review.
                              One acceptable eye must not clear the fellow eye or the patient.
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </Card>
                </div>
              </div>
            );
          })()}
        </div>
      )}

      {/* ===================================================================== */}
      {/* STEP 3: Combined Review & Overall Patient Referral */}
      {/* ===================================================================== */}
      {currentStep === 3 && activeScreening && (
        <Card>
          <div style={{ textAlign: 'center', marginBottom: '24px' }}>
            <h2 style={{ fontSize: '1.5rem', color: 'var(--rs-primary-dark)', margin: '0 0 6px' }}>
              Encounter Summary & Patient Referral Determination
            </h2>
            <p style={{ color: '#64748b', fontSize: '0.9rem', margin: 0 }}>
              Encounter ID: {activeScreening.id} | Patient: {selectedPatient?.first_name} {selectedPatient?.last_name}
            </p>
          </div>

          {/* Overall Patient Referral Banner (Determined by worse eye) */}
          <div
            style={{
              background:
                patientReferral.urgency === 'urgent'
                  ? '#fef2f2'
                  : patientReferral.urgency === 'priority'
                  ? '#fff7ed'
                  : patientReferral.urgency === 'routine'
                  ? '#fefce8'
                  : '#f0fdf4',
              border: `2px solid ${
                patientReferral.urgency === 'urgent'
                  ? '#ef4444'
                  : patientReferral.urgency === 'priority'
                  ? '#f97316'
                  : patientReferral.urgency === 'routine'
                  ? '#eab308'
                  : '#22c55e'
              }`,
              borderRadius: '12px',
              padding: '20px',
              marginBottom: '24px',
              textAlign: 'center',
            }}
          >
            <span style={{ fontSize: '2rem' }}>
              {patientReferral.urgency === 'urgent'
                ? '🚨'
                : patientReferral.urgency === 'priority'
                ? '⚠️'
                : patientReferral.urgency === 'routine'
                ? '📅'
                : '✅'}
            </span>
            <h3
              style={{
                margin: '8px 0 4px',
                fontSize: '1.3rem',
                color:
                  patientReferral.urgency === 'urgent'
                    ? '#b91c1c'
                    : patientReferral.urgency === 'priority'
                    ? '#c2410c'
                    : patientReferral.urgency === 'routine'
                    ? '#a16207'
                    : '#15803d',
                fontWeight: 800,
                textTransform: 'uppercase',
              }}
            >
              Overall Patient Referral Recommendation: {patientReferral.urgency}
            </h3>
            <p style={{ margin: '0 auto', maxWidth: '650px', fontSize: '0.9rem', color: '#475569' }}>
              <strong>Clinical Independence Rule:</strong> Per-eye findings are kept strictly independent. One normal eye
              does not clear the patient. Overall urgency reflects the worse eye findings.
            </p>
          </div>

          {/* Per-Eye Side-by-Side Comparison */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '28px' }}>
            {/* Right Eye (OD) */}
            <div style={{ border: '1px solid #e2e8f0', borderRadius: '10px', padding: '16px' }}>
              <h4 style={{ margin: '0 0 10px', fontSize: '1.1rem', color: 'var(--rs-primary-dark)' }}>
                Right Eye (OD) Summary
              </h4>
              {odState.activeJob?.result ? (
                <div>
                  <p style={{ margin: '4px 0', fontSize: '0.9rem' }}>
                    <strong>Grade:</strong> {odState.activeJob.result.severity_classification?.predicted_grade} (
                    {odState.activeJob.result.severity_classification?.grade_label})
                  </p>
                  <p style={{ margin: '4px 0', fontSize: '0.9rem' }}>
                    <strong>Confidence:</strong>{' '}
                    {Math.round((odState.activeJob.result.severity_classification?.confidence || 0) * 100)}%
                  </p>
                  <p style={{ margin: '4px 0', fontSize: '0.9rem' }}>
                    <strong>Urgency:</strong> {odState.activeJob.result.referral_recommendation?.urgency}
                  </p>
                  <p style={{ margin: '4px 0', fontSize: '0.85rem', color: '#64748b' }}>
                    Captures in history: {odState.history.length + (odState.currentUpload ? 1 : 0)}
                  </p>
                </div>
              ) : (
                <p style={{ color: '#94a3b8', fontStyle: 'italic', fontSize: '0.9rem' }}>
                  Awaiting completion or not analyzed.
                </p>
              )}
            </div>

            {/* Left Eye (OS) */}
            <div style={{ border: '1px solid #e2e8f0', borderRadius: '10px', padding: '16px' }}>
              <h4 style={{ margin: '0 0 10px', fontSize: '1.1rem', color: 'var(--rs-primary-dark)' }}>
                Left Eye (OS) Summary
              </h4>
              {osState.activeJob?.result ? (
                <div>
                  <p style={{ margin: '4px 0', fontSize: '0.9rem' }}>
                    <strong>Grade:</strong> {osState.activeJob.result.severity_classification?.predicted_grade} (
                    {osState.activeJob.result.severity_classification?.grade_label})
                  </p>
                  <p style={{ margin: '4px 0', fontSize: '0.9rem' }}>
                    <strong>Confidence:</strong>{' '}
                    {Math.round((osState.activeJob.result.severity_classification?.confidence || 0) * 100)}%
                  </p>
                  <p style={{ margin: '4px 0', fontSize: '0.9rem' }}>
                    <strong>Urgency:</strong> {osState.activeJob.result.referral_recommendation?.urgency}
                  </p>
                  <p style={{ margin: '4px 0', fontSize: '0.85rem', color: '#64748b' }}>
                    Captures in history: {osState.history.length + (osState.currentUpload ? 1 : 0)}
                  </p>
                </div>
              ) : (
                <p style={{ color: '#94a3b8', fontStyle: 'italic', fontSize: '0.9rem' }}>
                  Awaiting completion or not analyzed.
                </p>
              )}
            </div>
          </div>

          {/* Action Bar */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Button variant="secondary" onClick={() => setCurrentStep(2)}>
              ← Back to Imaging
            </Button>
            <div style={{ display: 'flex', gap: '12px' }}>
              <Button variant="secondary" onClick={() => router.push('/')}>
                Return to Dashboard
              </Button>
              <Button onClick={() => router.push(`/screening/results/${activeScreening.id}`)}>
                Open Full Diagnostic Report →
              </Button>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
