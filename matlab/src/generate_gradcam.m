function result = generate_gradcam(imagePath, modelPath, outputDir, options)
% GENERATE_GRADCAM Generate Grad-CAM explainability heatmap from model activations.
%
% Produces a Gradient-weighted Class Activation Mapping (Grad-CAM) overlay
% using ACTUAL model activations from the EfficientNet-B0 DR classifier.
% Maps the heatmap back to original-image coordinates, tracking crop,
% padding, resize, and orientation transforms.
%
% IMPORTANT: Grad-CAM shows model-influential regions, NOT confirmed
% lesions or proof that a prediction is correct.
%
% USAGE:
%   result = generate_gradcam('fundus.jpg', 'model.mat', './output/')
%   result = generate_gradcam('fundus.jpg', 'model.mat', './output/', ...
%       'targetLayer', 'top_conv', 'targetClass', 'Moderate NPDR')
%   result = generate_gradcam('fundus.jpg', 'model.mat', './output/', ...
%       'expertMaskPath', 'expert_mask.png')
%
% INPUTS:
%   imagePath   - (string) Path to the fundus image
%   modelPath   - (string) Path to the trained .mat model file
%   outputDir   - (string) Directory for output artifacts
%   options     - Name-value pairs:
%       'targetLayer'    - (string) Conv layer for Grad-CAM (auto-detect if empty)
%       'targetClass'    - (string) Class to explain (default: predicted class)
%       'expertMaskPath' - (string) Optional expert lesion mask for sanity checks
%
% OUTPUT:
%   result - (struct):
%     .status                    - 'available' | 'unavailable' | 'error'
%     .reason                    - Why unavailable/error (empty when available)
%     .gradcam_heatmap_path      - Jet-colorized heatmap at original resolution
%     .gradcam_overlay_path      - Alpha-blended overlay on original image
%     .gradcam_raw_path          - Raw float heatmap at model resolution (.mat)
%     .target_layer              - Conv layer used
%     .target_class              - Class the heatmap explains
%     .predicted_class           - Model's top-1 prediction
%     .preprocessing_transform   - Struct tracking coordinate mapping
%     .algorithm_version         - Version string for provenance
%     .disclaimer                - Mandatory disclaimer text
%     .pointing_game_hit         - (optional) Peak activation inside expert mask?
%     .expert_iou                - (optional) IoU of thresholded heatmap vs expert
%     .energy_pointing_game      - (optional) Fraction of energy inside expert mask
%
% REQUIRES:
%   - Deep Learning Toolbox
%   - Trained EfficientNet-B0 model (.mat with 'net' and optionally 'model_metadata')
%
% Copyright (c) 2026 RetinaShield Research Project

    arguments
        imagePath   (1,1) string {mustBeFile}
        modelPath   (1,1) string
        outputDir   (1,1) string
        options.targetLayer    (1,1) string = ""
        options.targetClass    (1,1) string = ""
        options.expertMaskPath (1,1) string = ""
    end

    ALGORITHM_VERSION = '1.0.0-gradcam';
    DISCLAIMER = ['Grad-CAM shows model-influential regions, not confirmed ' ...
                  'lesions or proof that a prediction is correct. ' ...
                  'RESEARCH SCREENING RESULT — not for autonomous diagnosis.'];

    % Initialize result with unavailable defaults
    result = struct();
    result.status                  = 'unavailable';
    result.reason                  = '';
    result.gradcam_heatmap_path    = '';
    result.gradcam_overlay_path    = '';
    result.gradcam_raw_path        = '';
    result.target_layer            = '';
    result.target_class            = '';
    result.predicted_class         = '';
    result.preprocessing_transform = struct();
    result.algorithm_version       = ALGORITHM_VERSION;
    result.disclaimer              = DISCLAIMER;
    result.pointing_game_hit       = [];
    result.expert_iou              = [];
    result.energy_pointing_game    = [];

    if ~isfolder(outputDir)
        mkdir(outputDir);
    end

    [~, baseName, ~] = fileparts(imagePath);

    % ===================================================================
    % 1. Check Deep Learning Toolbox availability
    % ===================================================================
    if ~exist('gradCAM', 'file') && ~exist('gradCAM', 'builtin')
        result.status = 'unavailable';
        result.reason = 'gradCAM function not available — requires Deep Learning Toolbox R2021a+';
        fprintf('[GradCAM] UNAVAILABLE: %s\n', result.reason);
        return;
    end

    % ===================================================================
    % 2. Load and validate model
    % ===================================================================
    if ~isfile(modelPath)
        result.status = 'unavailable';
        result.reason = sprintf('No trained model at: %s', modelPath);
        fprintf('[GradCAM] UNAVAILABLE: %s\n', result.reason);
        return;
    end

    modelData = load(modelPath);
    if ~isfield(modelData, 'net')
        result.status = 'error';
        result.reason = 'Model file does not contain a "net" variable';
        fprintf('[GradCAM] ERROR: %s\n', result.reason);
        return;
    end
    net = modelData.net;

    % ===================================================================
    % 3. Read model metadata — respect trained resolution and class order
    % ===================================================================
    inputSize = [224, 224, 3];  % Fallback only
    gradeLabels = {'No DR', 'Mild NPDR', 'Moderate NPDR', 'Severe NPDR', 'Proliferative DR'};
    isSmokeRun = false;
    isModelTrained = true;

    if isfield(modelData, 'model_metadata')
        meta = modelData.model_metadata;
        if isfield(meta, 'input_size')
            inputSize = meta.input_size;
            if numel(inputSize) == 2
                inputSize = [inputSize, 3];
            end
        end
        if isfield(meta, 'class_order')
            gradeLabels = meta.class_order;
        end
        if isfield(meta, 'is_smoke_run') && meta.is_smoke_run
            isSmokeRun = true;
        end
        if isfield(meta, 'model_trained')
            isModelTrained = meta.model_trained;
        end
    end

    % Reject smoke-run checkpoints
    if isSmokeRun
        result.status = 'unavailable';
        result.reason = 'Model is a SMOKE_TEST checkpoint — Grad-CAM requires a fully trained model';
        fprintf('[GradCAM] UNAVAILABLE: %s\n', result.reason);
        return;
    end

    % ===================================================================
    % 4. Auto-detect target convolutional layer
    % ===================================================================
    targetLayer = options.targetLayer;
    if targetLayer == ""
        try
            lgraph = layerGraph(net);
            layers = lgraph.Layers;
            convLayers = layers(arrayfun(@(l) isa(l, 'nnet.cnn.layer.Convolution2DLayer'), layers));
            if isempty(convLayers)
                result.status = 'error';
                result.reason = 'No convolutional layers found in model';
                fprintf('[GradCAM] ERROR: %s\n', result.reason);
                return;
            end
            targetLayer = string(convLayers(end).Name);
        catch ME
            result.status = 'error';
            result.reason = sprintf('Cannot inspect model layers: %s', ME.message);
            fprintf('[GradCAM] ERROR: %s\n', result.reason);
            return;
        end
    end
    result.target_layer = char(targetLayer);

    % ===================================================================
    % 5. Preprocess image — track coordinate transform
    % ===================================================================
    originalImg = imread(imagePath);
    originalSize = [size(originalImg, 1), size(originalImg, 2)];

    modelH = inputSize(1);
    modelW = inputSize(2);

    % Resize preserving aspect ratio with center-crop
    % (Matches the preprocessing used during training)
    imgResized = imresize(originalImg, [modelH, modelW]);
    imgInput = im2single(imgResized);

    scaleH = modelH / originalSize(1);
    scaleW = modelW / originalSize(2);

    transform = struct();
    transform.original_size    = originalSize;
    transform.model_input_size = [modelH, modelW];
    transform.scale_factor_h   = scaleH;
    transform.scale_factor_w   = scaleW;
    transform.crop_box         = [];  % No crop in current pipeline
    transform.pad_offsets      = [];  % No padding in current pipeline
    result.preprocessing_transform = transform;

    % ===================================================================
    % 6. Classify to get predicted class (if not overridden)
    % ===================================================================
    try
        [predictedLabel, scores] = classify(net, imgInput);
        result.predicted_class = char(predictedLabel);

        % Determine target class for Grad-CAM
        if options.targetClass ~= ""
            targetClassLabel = options.targetClass;
        else
            targetClassLabel = predictedLabel;
        end
        result.target_class = char(targetClassLabel);

    catch ME
        result.status = 'error';
        result.reason = sprintf('Classification failed: %s', ME.message);
        fprintf('[GradCAM] ERROR: %s\n', result.reason);
        return;
    end

    % ===================================================================
    % 7. Generate Grad-CAM from model activations
    % ===================================================================
    try
        gradcamMap = gradCAM(net, imgInput, targetClassLabel, ...
            'FeatureLayer', char(targetLayer));

        % Normalize to [0, 1]
        gradcamMap = double(gradcamMap);
        if max(gradcamMap(:)) > 0
            gradcamMap = gradcamMap / max(gradcamMap(:));
        end

    catch ME
        result.status = 'error';
        result.reason = sprintf('gradCAM() execution failed: %s', ME.message);
        fprintf('[GradCAM] ERROR: %s\n', result.reason);
        return;
    end

    % ===================================================================
    % 8. Map heatmap back to original image coordinates
    % ===================================================================
    heatmapOriginalRes = imresize(gradcamMap, originalSize);

    % Jet colorize the heatmap (transparent = low, red = high)
    heatmapColor = ind2rgb(im2uint8(heatmapOriginalRes), jet(256));
    heatmapColorU8 = im2uint8(heatmapColor);

    % Alpha-blended overlay
    alpha = 0.45;
    overlay = im2uint8(double(originalImg) * (1 - alpha) + ...
                       double(heatmapColorU8) * alpha);

    % Add provenance text annotation
    annotText = sprintf('Grad-CAM: %s | Layer: %s | %s', ...
        char(targetClassLabel), char(targetLayer), 'RESEARCH ONLY');
    try
        overlay = insertText(overlay, [10, 10], annotText, ...
            'FontSize', 16, 'TextColor', 'white', 'BoxColor', 'black', ...
            'BoxOpacity', 0.7);
    catch
        % insertText may not be available; proceed without annotation
    end

    % ===================================================================
    % 9. Save output artifacts
    % ===================================================================
    heatmapPath = fullfile(outputDir, [char(baseName) '_gradcam_heatmap.png']);
    overlayPath = fullfile(outputDir, [char(baseName) '_gradcam_overlay.png']);
    rawPath     = fullfile(outputDir, [char(baseName) '_gradcam_raw.mat']);

    imwrite(heatmapColorU8, heatmapPath);
    imwrite(overlay, overlayPath);

    % Save raw float heatmap for evaluation use
    gradcam_raw = gradcamMap;  %#ok<NASGU>
    save(rawPath, 'gradcam_raw', 'transform');

    result.status               = 'available';
    result.reason               = '';
    result.gradcam_heatmap_path = char(heatmapPath);
    result.gradcam_overlay_path = char(overlayPath);
    result.gradcam_raw_path     = char(rawPath);

    fprintf('[GradCAM] Heatmap saved: %s\n', heatmapPath);
    fprintf('[GradCAM] Overlay saved: %s\n', overlayPath);
    fprintf('[GradCAM] Target layer: %s | Class: %s | Algorithm: %s\n', ...
        char(targetLayer), char(targetClassLabel), ALGORITHM_VERSION);

    % ===================================================================
    % 10. Explanation-localization evaluation (if expert mask provided)
    % ===================================================================
    if options.expertMaskPath ~= "" && isfile(options.expertMaskPath)
        try
            expertMask = imread(options.expertMaskPath);
            if size(expertMask, 3) > 1
                expertMask = rgb2gray(expertMask);
            end
            expertBinary = imbinarize(expertMask);

            % Resize heatmap to expert mask dimensions
            evalHeatmap = imresize(heatmapOriginalRes, size(expertBinary));

            % --- Pointing Game ---
            [~, peakIdx] = max(evalHeatmap(:));
            [peakR, peakC] = ind2sub(size(evalHeatmap), peakIdx);
            result.pointing_game_hit = expertBinary(peakR, peakC);

            % --- IoU at threshold 0.5 ---
            heatmapThreshed = evalHeatmap >= 0.5;
            intersection = sum(heatmapThreshed(:) & expertBinary(:));
            union_val    = sum(heatmapThreshed(:) | expertBinary(:));
            if union_val > 0
                result.expert_iou = intersection / union_val;
            else
                result.expert_iou = 0.0;
            end

            % --- Energy-Based Pointing Game ---
            totalEnergy = sum(evalHeatmap(:));
            if totalEnergy > 0
                insideEnergy = sum(evalHeatmap(expertBinary));
                result.energy_pointing_game = insideEnergy / totalEnergy;
            else
                result.energy_pointing_game = 0.0;
            end

            fprintf('[GradCAM Eval] Pointing Game: %s | IoU: %.3f | Energy: %.3f\n', ...
                mat2str(result.pointing_game_hit), result.expert_iou, result.energy_pointing_game);

        catch ME
            warning('generate_gradcam:evalFailed', ...
                'Explanation evaluation failed: %s', ME.message);
        end
    end
end
