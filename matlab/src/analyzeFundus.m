function result = analyzeFundus(imagePath, outputDir, options)
% ANALYZEFUNDUS Versioned entry point for RetinaShield fundus analysis.
%
% Integrates the entire RetinaShield inference pipeline:
%   1. Quality Assessment (IQA) -> early rejection of ungradeable images
%   2. Permitted Enhancement -> CLAHE + green channel + vessel enhancement
%   3. Structure Analysis    -> Optic disc, macula, fovea, vasculature
%   4. Classification        -> EfficientNet-B0 DR grading (0-4) + Calibration
%   5. Lesion-Adapter        -> Microaneurysms, hemorrhages, exudates candidates
%   6. Grad-CAM              -> Explainability heatmap
%   7. Consistency Checks    -> Dual-engine concordance & referral recommendation
%
% USAGE:
%   result = analyzeFundus(imagePath, outputDir)
%   result = analyzeFundus(imagePath, outputDir, optionsJsonOrStruct)
%
% INPUTS:
%   imagePath - (char or string) Path to the raw fundus image file
%   outputDir - (char or string) Directory for all output artifacts
%   options   - (optional) struct or JSON string / path specifying options:
%                 .model_path (string) - custom classifier weights path
%                 .run_gradcam (bool)  - default true
%                 .run_lesions (bool)  - default true
%
% OUTPUT:
%   result - (struct) Complete analysis bundle including:
%              .entry_point_version
%              .pipeline_version
%              .preprocessing_version
%              .model_hashes
%              .component_availability
%              .timings_ms
%              .quality_assessment
%              .enhancement
%              .structure_analysis
%              .severity_classification
%              .confidence_calibration
%              .lesion_detection
%              .gradcam_explanation
%              .consistency_analysis
%              .referral_recommendation
%
% NOTE: RESEARCH SCREENING RESULT — Not a clinical diagnosis.
%       Must be reviewed by a qualified ophthalmologist.
%
% Copyright (c) 2026 RetinaShield Research Project

    imagePath = char(imagePath);
    outputDir = char(outputDir);

    if nargin < 3 || isempty(options)
        opts = struct();
    elseif ischar(options) || isstring(options)
        optStr = char(options);
        if isfile(optStr)
            opts = jsondecode(fileread(optStr));
        else
            try
                opts = jsondecode(optStr);
            catch
                opts = struct();
            end
        end
    elseif isstruct(options)
        opts = options;
    else
        opts = struct();
    end

    entryPointVersion = '1.0.0';
    pipelineVersion = '1.0.0';
    preprocessingVersion = '1.0';

    totalTic = tic;
    timings = struct();

    % Ensure output directory exists
    if ~exist(outputDir, 'dir')
        mkdir(outputDir);
    end

    % Locate model weights
    defaultModelPath = fullfile(fileparts(mfilename('fullpath')), '..', 'models', 'efficientnet_b0_dr.mat');
    if isfield(opts, 'model_path') && ~isempty(opts.model_path)
        modelPath = char(opts.model_path);
    else
        modelPath = defaultModelPath;
    end

    % Compute model hash if exists
    modelHashes = struct('classifier', 'none', 'lesion_detector', 'none');
    if isfile(modelPath)
        try
            modelHashes.classifier = compute_file_sha256(modelPath);
        catch
            modelHashes.classifier = 'hash_failed';
        end
    end

    % Component availability tracking
    availability = struct(...
        'quality_assessment', false, ...
        'enhancement', false, ...
        'structure_analysis', false, ...
        'severity_classification', false, ...
        'confidence_calibration', false, ...
        'lesion_detection', false, ...
        'gradcam_explanation', false, ...
        'consistency_analysis', false ...
    );

    result = struct();
    result.entry_point_version = entryPointVersion;
    result.pipeline_version = pipelineVersion;
    result.preprocessing_version = preprocessingVersion;
    result.analysis_id = char(java.util.UUID.randomUUID().toString());
    result.timestamp = char(datetime('now', 'Format', 'yyyy-MM-dd''T''HH:mm:ss.SSSXXX'));
    result.disclaimer = 'RESEARCH SCREENING RESULT — Not a clinical diagnosis. Must be reviewed by a qualified ophthalmologist.';
    result.model_hashes = modelHashes;

    % Validate input image
    if ~isfile(imagePath)
        error('analyzeFundus:FileNotFound', 'Input image file not found: %s', imagePath);
    end

    % =========================================================================
    % Stage 1: Quality Assessment
    % =========================================================================
    stageTic = tic;
    try
        result.quality_assessment = quality_assessment(imagePath);
        availability.quality_assessment = true;
    catch ME
        warning('analyzeFundus:iqaFailed', 'Quality assessment failed: %s', ME.message);
        result.quality_assessment = struct(...
            'status', 'ungradeable', ...
            'reason_codes', {{'ERR_EXCEPTION'}}, ...
            'recapture_guidance', {{'An error occurred during assessment. Please recapture.'}}, ...
            'measurements', struct(), ...
            'is_heuristic', true, ...
            'validation_required', true ...
        );
        availability.quality_assessment = false;
    end
    timings.quality_assessment_ms = round(toc(stageTic) * 1000);

    % If image is rejected as ungradeable, abstain safely:
    if strcmp(result.quality_assessment.status, 'ungradeable')
        result.enhancement = struct('method', 'skipped', 'reason', 'image_ungradeable');
        result.structure_analysis = struct('status', 'skipped', 'reason', 'image_ungradeable');
        result.severity_classification = struct(...
            'model', 'EfficientNet-B0', ...
            'model_trained', false, ...
            'predicted_grade', -1, ...
            'grade_label', 'UNGRADEABLE — Must never be reported as No DR', ...
            'confidence', 0.0, ...
            'class_probabilities', [0.2, 0.2, 0.2, 0.2, 0.2] ...
        );
        result.confidence_calibration = struct(...
            'status', 'ungradeable_abstention', ...
            'calibrated_probabilities', [0.2, 0.2, 0.2, 0.2, 0.2], ...
            'is_uncertain', true ...
        );
        result.lesion_detection = struct('status', 'skipped', 'reason', 'image_ungradeable', 'detections', []);
        result.gradcam_explanation = struct('status', 'skipped', 'reason', 'image_ungradeable');
        result.consistency_analysis = struct(...
            'concordant', false, ...
            'finding_label', 'Ungradeable Image — Abstain', ...
            'dual_engine_status', 'ungradeable', ...
            'action_required', 'Recapture required' ...
        );
        result.referral_recommendation = struct(...
            'urgency', 'routine', ...
            'reason', 'Image quality insufficient for automated assessment. Please recapture.', ...
            'suggested_followup_weeks', 2 ...
        );

        timings.total_ms = round(toc(totalTic) * 1000);
        result.timings_ms = timings;
        result.component_availability = availability;

        % Write JSON
        write_result_json(result, outputDir);
        return;
    end

    % =========================================================================
    % Stage 2: Permitted Enhancement
    % =========================================================================
    stageTic = tic;
    enhanceDir = fullfile(outputDir, 'enhanced');
    try
        result.enhancement = enhance_fundus(imagePath, enhanceDir, result.quality_assessment);
        if isfield(result.enhancement, 'post_enhancement_iqa')
            result.quality_assessment = result.enhancement.post_enhancement_iqa;
        end
        availability.enhancement = true;
    catch ME
        warning('analyzeFundus:enhanceFailed', 'Enhancement failed: %s', ME.message);
        result.enhancement = struct('method', 'failed', 'error', ME.message);
        availability.enhancement = false;
    end
    timings.enhancement_ms = round(toc(stageTic) * 1000);

    % =========================================================================
    % Stage 3: Structure Analysis
    % =========================================================================
    stageTic = tic;
    segmentDir = fullfile(outputDir, 'segmentation');
    try
        result.structure_analysis = segment_structures(imagePath, segmentDir);
        availability.structure_analysis = true;
    catch ME
        warning('analyzeFundus:segmentFailed', 'Structure analysis failed: %s', ME.message);
        result.structure_analysis = struct('status', 'failed', 'error', ME.message, 'is_experimental', true);
        availability.structure_analysis = false;
    end
    timings.structure_analysis_ms = round(toc(stageTic) * 1000);

    % =========================================================================
    % Stage 4: DR Severity Classification & Confidence Calibration
    % =========================================================================
    stageTic = tic;
    try
        if isfile(modelPath)
            result.severity_classification = classify_dr(imagePath, modelPath, result.quality_assessment.status);
            rawProbs = result.severity_classification.class_probabilities;
            result.confidence_calibration = calibrate_probabilities(rawProbs);
            availability.severity_classification = true;
            availability.confidence_calibration = true;
        else
            % Model weights missing: explicit failure, do NOT substitute predictions
            result.severity_classification = struct(...
                'model', 'EfficientNet-B0', ...
                'model_trained', false, ...
                'predicted_grade', -1, ...
                'grade_label', 'UNAVAILABLE — Model weights not found', ...
                'confidence', 0.0, ...
                'class_probabilities', [0.2, 0.2, 0.2, 0.2, 0.2], ...
                'error', sprintf('Model file missing at: %s', modelPath) ...
            );
            result.confidence_calibration = struct(...
                'status', 'unavailable', ...
                'calibrated_probabilities', [0.2, 0.2, 0.2, 0.2, 0.2], ...
                'is_uncertain', true ...
            );
            availability.severity_classification = false;
            availability.confidence_calibration = false;
        end
    catch ME
        warning('analyzeFundus:classifyFailed', 'Classification failed: %s', ME.message);
        result.severity_classification = struct(...
            'model', 'EfficientNet-B0', ...
            'model_trained', false, ...
            'predicted_grade', -1, ...
            'grade_label', 'Classification Failed', ...
            'confidence', 0.0, ...
            'class_probabilities', [0.2, 0.2, 0.2, 0.2, 0.2], ...
            'error', ME.message ...
        );
        result.confidence_calibration = struct(...
            'status', 'failed', ...
            'calibrated_probabilities', [0.2, 0.2, 0.2, 0.2, 0.2], ...
            'is_uncertain', true ...
        );
        availability.severity_classification = false;
        availability.confidence_calibration = false;
    end
    timings.classification_ms = round(toc(stageTic) * 1000);

    % =========================================================================
    % Stage 5: Lesion-Adapter Detection Results
    % =========================================================================
    stageTic = tic;
    try
        lesionRes = detect_lesion_candidates(imagePath);
        result.lesion_detection = struct(...
            'model', 'MATLAB-Morphology-Candidates-v1.0', ...
            'status', 'heuristic_baseline', ...
            'message', 'Morphological candidate proposals (unvalidated heuristic baseline)', ...
            'detections', lesionRes.candidates, ...
            'model_estimated_count', lesionRes.model_estimated_count, ...
            'model_trained', false ...
        );
        availability.lesion_detection = true;
    catch ME
        warning('analyzeFundus:lesionsFailed', 'Lesion detection failed: %s', ME.message);
        result.lesion_detection = struct(...
            'model', 'MATLAB-Morphology', ...
            'status', 'failed', ...
            'error', ME.message, ...
            'detections', [], ...
            'model_estimated_count', struct(), ...
            'model_trained', false ...
        );
        availability.lesion_detection = false;
    end
    timings.lesion_detection_ms = round(toc(stageTic) * 1000);

    % =========================================================================
    % Stage 6: Grad-CAM Explainability Heatmap
    % =========================================================================
    stageTic = tic;
    gradcamDir = fullfile(outputDir, 'gradcam');
    try
        if isfile(modelPath) && availability.severity_classification
            gradcamResult = generate_gradcam(imagePath, modelPath, gradcamDir);
            result.gradcam_explanation = gradcamResult;
            result.severity_classification.gradcam_heatmap_path = gradcamResult.gradcam_heatmap_path;
            availability.gradcam_explanation = true;
        else
            result.gradcam_explanation = struct(...
                'status', 'unavailable', ...
                'reason', 'Requires trained classifier weights to generate activations', ...
                'gradcam_heatmap_path', '', ...
                'gradcam_overlay_path', '' ...
            );
            availability.gradcam_explanation = false;
        end
    catch ME
        warning('analyzeFundus:gradcamFailed', 'Grad-CAM failed: %s', ME.message);
        result.gradcam_explanation = struct(...
            'status', 'failed', ...
            'error', ME.message, ...
            'gradcam_heatmap_path', '', ...
            'gradcam_overlay_path', '' ...
        );
        availability.gradcam_explanation = false;
    end
    timings.gradcam_ms = round(toc(stageTic) * 1000);

    % =========================================================================
    % Stage 7: Conservative Consistency Evaluation & Referral Suggestion
    % =========================================================================
    stageTic = tic;
    try
        [result.consistency_analysis, result.referral_recommendation] = evaluate_consistency(result);
        availability.consistency_analysis = true;
    catch ME
        warning('analyzeFundus:consistencyFailed', 'Consistency check failed: %s', ME.message);
        result.consistency_analysis = struct(...
            'status', 'failed', ...
            'error', ME.message, ...
            'finding_label', 'Consistency check unavailable' ...
        );
        result.referral_recommendation = struct(...
            'urgency', 'priority', ...
            'reason', 'Pipeline evaluation incomplete. Human specialist review required.' ...
        );
        availability.consistency_analysis = false;
    end
    timings.consistency_ms = round(toc(stageTic) * 1000);

    % Final timings and availability summary
    timings.total_ms = round(toc(totalTic) * 1000);
    result.timings_ms = timings;
    result.component_availability = availability;

    % Persist JSON result
    write_result_json(result, outputDir);
end

% -----------------------------------------------------------------------------
% Helper: Compute SHA-256 of file in pure MATLAB (using java.security.MessageDigest)
% -----------------------------------------------------------------------------
function hashStr = compute_file_sha256(filePath)
    md = java.security.MessageDigest.getInstance('SHA-256');
    fid = fopen(filePath, 'r');
    if fid == -1
        hashStr = 'unable_to_open';
        return;
    end
    cleanup = onCleanup(@() fclose(fid));
    bufferSize = 65536;
    while ~feof(fid)
        bytes = fread(fid, bufferSize, '*uint8');
        if ~isempty(bytes)
            md.update(bytes);
        end
    end
    hashBytes = typecast(md.digest(), 'uint8');
    hashStr = lower(reshape(dec2hex(hashBytes)', 1, []));
end

% -----------------------------------------------------------------------------
% Helper: Write result struct to analysis_result.json safely
% -----------------------------------------------------------------------------
function write_result_json(resultStruct, outputDir)
    try
        resultPath = fullfile(outputDir, 'analysis_result.json');
        jsonText = jsonencode(resultStruct, 'PrettyPrint', true);
        fid = fopen(resultPath, 'w');
        if fid ~= -1
            cleanup = onCleanup(@() fclose(fid));
            fprintf(fid, '%s', jsonText);
        end
    catch ME
        warning('analyzeFundus:jsonWriteFailed', 'Could not write analysis_result.json: %s', ME.message);
    end
end
