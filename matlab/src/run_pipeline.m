function result = run_pipeline(imagePath, outputDir, modelPath)
% RUN_PIPELINE Orchestrate the full RetinaShield MATLAB analysis pipeline.
%
% Executes all stages in order:
%   1. Quality Assessment  → Reject poor-quality images early
%   2. Image Enhancement   → CLAHE + green channel + vessel enhancement
%   3. Structure Analysis  → Optic disc, macula, vessel segmentation
%   4. DR Classification   → EfficientNet-B0 severity grading (0-4)
%   5. Grad-CAM Generation → Explainability heatmap
%
% USAGE:
%   result = run_pipeline('path/to/fundus.jpg', './output/')
%   result = run_pipeline('path/to/fundus.jpg', './output/', 'path/to/model.mat')
%
% INPUTS:
%   imagePath - (string) Full path to the fundus image
%   outputDir - (string) Directory for all output artifacts
%   modelPath - (string, optional) Path to trained EfficientNet-B0 .mat file
%
% OUTPUT:
%   result - (struct) Complete analysis result matching the RetinaShield
%            analysis_result_schema.json (minus lesion_detection which is
%            handled by the Python YOLOv8 service).
%
% NOTE: RESEARCH SCREENING RESULT — Not a clinical diagnosis.
%       Must be reviewed by a qualified ophthalmologist.
%
% Copyright (c) 2026 RetinaShield Research Project

    arguments
        imagePath (1,1) string {mustBeFile}
        outputDir (1,1) string
        modelPath (1,1) string = ""
    end

    pipelineVersion = '0.1.0-dev';
    startTime = tic;

    fprintf('==========================================================\n');
    fprintf(' RetinaShield MATLAB Analysis Pipeline v%s\n', pipelineVersion);
    fprintf(' RESEARCH SCREENING — NOT a clinical diagnosis\n');
    fprintf('==========================================================\n');
    fprintf(' Image: %s\n', imagePath);
    fprintf(' Output: %s\n', outputDir);
    fprintf('==========================================================\n\n');

    if ~isfolder(outputDir)
        mkdir(outputDir);
    end

    % Default model path
    if modelPath == ""
        modelPath = fullfile(fileparts(mfilename('fullpath')), '..', 'models', 'efficientnet_b0_dr.mat');
    end

    % Initialize result structure
    result = struct();
    result.analysis_id = char(java.util.UUID.randomUUID().toString());
    result.pipeline_version = pipelineVersion;
    result.timestamp = char(datetime('now', 'Format', 'yyyy-MM-dd''T''HH:mm:ss.SSSXXX'));
    result.disclaimer = 'RESEARCH SCREENING RESULT — Not a clinical diagnosis. Must be reviewed by a qualified ophthalmologist.';

    % ===================================================================
    % Stage 1: Quality Assessment
    % ===================================================================
    fprintf('[1/5] Quality Assessment...\n');
    try
        result.quality_assessment = quality_assessment(imagePath);
    catch ME
        warning('run_pipeline:iqaFailed', 'Quality assessment failed: %s', ME.message);
        result.quality_assessment = struct('status', 'ungradeable', ...
            'reason_codes', {{'ERR_EXCEPTION'}}, ...
            'recapture_guidance', {{'An error occurred during assessment. Please recapture.'}}, ...
            'measurements', struct(), ...
            'is_heuristic', true, ...
            'validation_required', true);
    end

    % Check if image should be rejected
    if strcmp(result.quality_assessment.status, 'ungradeable')
        fprintf('\n*** IMAGE UNGRADEABLE — quality too low for reliable analysis ***\n');
        fprintf('*** Please recapture the fundus image. ***\n\n');
        result.enhancement = struct();
        result.structure_analysis = struct();
        result.severity_classification = struct('model', 'EfficientNet-B0', ...
            'model_trained', false, 'predicted_grade', -1, ...
            'grade_label', 'UNGRADEABLE — Must never be reported as No DR');
        result.referral_recommendation = struct('urgency', 'none', ...
            'reason', 'Image quality insufficient for analysis. Please recapture.');
        result.processing_time_seconds = toc(startTime);
        return;
    end
    fprintf('\n');

    % ===================================================================
    % Stage 2: Image Enhancement
    % ===================================================================
    fprintf('[2/5] Image Enhancement...\n');
    enhanceDir = fullfile(outputDir, 'enhanced');
    try
        result.enhancement = enhance_fundus(imagePath, enhanceDir, result.quality_assessment);
        
        % Update quality_assessment with post-enhancement results
        if isfield(result.enhancement, 'post_enhancement_iqa')
            result.quality_assessment = result.enhancement.post_enhancement_iqa;
        end
    catch ME
        warning('run_pipeline:enhanceFailed', 'Enhancement failed: %s', ME.message);
        result.enhancement = struct('method', 'failed', ...
            'enhanced_image_path', '', 'high_res_tiles', {{}}, ...
            'geometry', struct(), 'parameters', struct());
    end
    fprintf('\n');

    % ===================================================================
    % Stage 3: Structure Analysis
    % ===================================================================
    fprintf('[3/5] Retinal Structure Analysis...\n');
    segmentDir = fullfile(outputDir, 'segmentation');
    try
        result.structure_analysis = segment_structures(imagePath, segmentDir);
    catch ME
        warning('run_pipeline:segmentFailed', 'Structure analysis failed: %s', ME.message);
        result.structure_analysis = struct(...
            'optic_disc', struct('detected', false), ...
            'macula', struct('detected', false), ...
            'vasculature', struct('segmentation_mask_path', '', ...
                'vessel_density', 0, 'tortuosity_index', 0));
    end
    fprintf('\n');

    % ===================================================================
    % Stage 4: DR Severity Classification
    % ===================================================================
    fprintf('[4/5] DR Severity Classification (EfficientNet-B0)...\n');
    try
        result.severity_classification = classify_dr(imagePath, modelPath);
    catch ME
        warning('run_pipeline:classifyFailed', 'Classification failed: %s', ME.message);
        result.severity_classification = struct('model', 'EfficientNet-B0', ...
            'model_trained', false, 'predicted_grade', -1, ...
            'grade_label', 'Classification failed', 'confidence', 0, ...
            'class_probabilities', [0.2, 0.2, 0.2, 0.2, 0.2]);
    end
    fprintf('\n');

    % ===================================================================
    % Stage 5: Grad-CAM Explainability
    % ===================================================================
    fprintf('[5/5] Grad-CAM Explainability Heatmap...\n');
    gradcamDir = fullfile(outputDir, 'gradcam');
    try
        gradcamResult = generate_gradcam(imagePath, modelPath, gradcamDir);
        if isfield(result.severity_classification, 'gradcam_heatmap_path') || true
            result.severity_classification.gradcam_heatmap_path = gradcamResult.gradcam_heatmap_path;
        end
    catch ME
        warning('run_pipeline:gradcamFailed', 'Grad-CAM failed: %s', ME.message);
        result.severity_classification.gradcam_heatmap_path = '';
    end
    fprintf('\n');

    % ===================================================================
    % Referral Recommendation (rule-based)
    % ===================================================================
    result.referral_recommendation = compute_referral(result);

    % Processing time
    result.processing_time_seconds = toc(startTime);

    % ===================================================================
    % Save result as JSON
    % ===================================================================
    resultPath = fullfile(outputDir, 'analysis_result.json');
    jsonText = jsonencode(result, 'PrettyPrint', true);
    fid = fopen(resultPath, 'w');
    fprintf(fid, '%s', jsonText);
    fclose(fid);

    fprintf('==========================================================\n');
    fprintf(' Pipeline complete in %.2f seconds\n', result.processing_time_seconds);
    fprintf(' Result saved to: %s\n', resultPath);
    fprintf(' RESEARCH SCREENING — NOT a clinical diagnosis\n');
    fprintf('==========================================================\n');
end


function referral = compute_referral(result)
% COMPUTE_REFERRAL Derive referral recommendation from analysis results.
%   Rule-based logic per International Clinical DR Severity Scale.

    referral = struct('urgency', 'none', 'reason', '', 'suggested_followup_weeks', 52);

    if ~isfield(result, 'severity_classification') || ...
       ~result.severity_classification.model_trained
        referral.urgency = 'none';
        referral.reason = 'Model not trained — no referral recommendation possible. Clinical evaluation required.';
        referral.suggested_followup_weeks = 0;
        return;
    end

    grade = result.severity_classification.predicted_grade;

    switch grade
        case 0
            referral.urgency = 'none';
            referral.reason = 'No apparent diabetic retinopathy detected. Routine annual screening recommended.';
            referral.suggested_followup_weeks = 52;
        case 1
            referral.urgency = 'routine';
            referral.reason = 'Mild NPDR detected. Referral for ophthalmological evaluation within 6 months.';
            referral.suggested_followup_weeks = 26;
        case 2
            referral.urgency = 'priority';
            referral.reason = 'Moderate NPDR detected. Priority referral for ophthalmological evaluation within 3 months.';
            referral.suggested_followup_weeks = 13;
        case 3
            referral.urgency = 'priority';
            referral.reason = 'Severe NPDR detected. Urgent referral to retina specialist within 2-4 weeks.';
            referral.suggested_followup_weeks = 4;
        case 4
            referral.urgency = 'urgent';
            referral.reason = 'Proliferative DR detected. URGENT referral to retina specialist within 1 week.';
            referral.suggested_followup_weeks = 1;
        otherwise
            referral.urgency = 'none';
            referral.reason = 'Classification result invalid. Clinical evaluation required.';
            referral.suggested_followup_weeks = 0;
    end

    % Escalate if macula involved (simplified check)
    if isfield(result, 'structure_analysis') && isfield(result.structure_analysis, 'macula')
        if result.structure_analysis.macula.detected && grade >= 2
            referral.reason = [referral.reason ' Macular involvement suspected — consider OCT evaluation.'];
            if strcmp(referral.urgency, 'priority')
                referral.urgency = 'urgent';
            end
        end
    end
end
