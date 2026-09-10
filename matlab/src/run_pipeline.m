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
            'field_of_view', struct('mask_path', '', 'is_reliable', false, 'failure_reason', ME.message), ...
            'optic_disc', struct('detected', false, 'confidence', 0.0, 'is_reliable', false, 'failure_reason', ME.message), ...
            'macula', struct('detected', false, 'confidence', 0.0, 'is_reliable', false, 'failure_reason', ME.message), ...
            'fovea', struct('detected', false, 'confidence', 0.0, 'is_reliable', false, 'failure_reason', ME.message), ...
            'vasculature', struct('segmentation_mask_path', '', ...
                'vessel_density', 0, 'tortuosity_index', 0, 'is_reliable', false, 'failure_reason', ME.message), ...
            'is_experimental', true);
    end
    fprintf('\n');

    % ===================================================================
    % Stage 4: DR Severity Classification & Confidence Calibration
    % ===================================================================
    fprintf('[4/6] DR Severity Classification & Confidence Calibration...\n');
    try
        result.severity_classification = classify_dr(imagePath, modelPath);
        rawProbs = result.severity_classification.class_probabilities;
        result.confidence_calibration = calibrate_probabilities(rawProbs);
    catch ME
        warning('run_pipeline:classifyFailed', 'Classification failed: %s', ME.message);
        result.severity_classification = struct('model', 'EfficientNet-B0', ...
            'model_trained', false, 'predicted_grade', -1, ...
            'grade_label', 'Classification failed', 'confidence', 0, ...
            'class_probabilities', [0.2, 0.2, 0.2, 0.2, 0.2]);
        result.confidence_calibration = struct('status', 'fallback_uniform', ...
            'temperature', NaN, 'calibrated_probabilities', [0.2, 0.2, 0.2, 0.2, 0.2], ...
            'max_calibrated_probability', 0.2, 'confidence_margin', 0.0, ...
            'shannon_entropy', 1.0, 'is_uncertain', true);
    end
    fprintf('\n');

    % ===================================================================
    % Stage 5: Lesion Candidate Detection Baseline
    % ===================================================================
    fprintf('[5/6] Lesion Candidate Detection Baseline...\n');
    try
        lesionRes = detect_lesion_candidates(imagePath);
        result.lesion_detection = struct(...
            'model', 'MATLAB-Morphology-Candidates-v1.0', ...
            'status', 'heuristic_only', ...
            'message', 'Morphological candidate proposals (unvalidated heuristic baseline)', ...
            'detections', lesionRes.candidates, ...
            'model_estimated_count', lesionRes.model_estimated_count, ...
            'model_trained', false);
    catch ME
        warning('run_pipeline:lesionsFailed', 'Lesion detection failed: %s', ME.message);
        result.lesion_detection = struct('model', 'MATLAB-Morphology', ...
            'status', 'unavailable', 'message', ME.message, ...
            'detections', [], 'model_estimated_count', struct(), 'model_trained', false);
    end
    fprintf('\n');

    % ===================================================================
    % Stage 6: Grad-CAM Explainability Heatmap
    % ===================================================================
    fprintf('[6/6] Grad-CAM Explainability Heatmap...\n');
    gradcamDir = fullfile(outputDir, 'gradcam');
    try
        gradcamResult = generate_gradcam(imagePath, modelPath, gradcamDir);
        result.gradcam_explanation = gradcamResult;
        result.severity_classification.gradcam_heatmap_path = gradcamResult.gradcam_heatmap_path;
    catch ME
        warning('run_pipeline:gradcamFailed', 'Grad-CAM failed: %s', ME.message);
        result.gradcam_explanation = struct('status', 'error', 'reason', ME.message, ...
            'gradcam_heatmap_path', '', 'gradcam_overlay_path', '', 'gradcam_raw_path', '', ...
            'target_layer', '', 'target_class', '', 'predicted_class', '', ...
            'preprocessing_transform', struct(), 'algorithm_version', '1.0.0-gradcam', ...
            'disclaimer', 'Grad-CAM shows model-influential regions, not confirmed lesions or proof that a prediction is correct.', ...
            'pointing_game_hit', [], 'expert_iou', [], 'energy_pointing_game', []);
        result.severity_classification.gradcam_heatmap_path = '';
    end
    fprintf('\n');

    % ===================================================================
    % Conservative Dual-Engine Consistency Evaluation & Referral Suggestion
    % ===================================================================
    [result.consistency_analysis, result.referral_recommendation] = evaluate_consistency(result);

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
    fprintf(' Consistency Finding: %s\n', result.consistency_analysis.finding_label);
    fprintf(' Referral Urgency:    %s\n', result.referral_recommendation.urgency);
    fprintf(' Result saved to: %s\n', resultPath);
    fprintf(' RESEARCH SCREENING — NOT a clinical diagnosis\n');
    fprintf('==========================================================\n');
end
