function result = generate_gradcam(imagePath, modelPath, outputDir, targetLayer)
% GENERATE_GRADCAM Generate Grad-CAM explainability heatmap for DR classification.
%
% Produces a Gradient-weighted Class Activation Mapping (Grad-CAM) overlay
% that highlights regions of the fundus image most influential to the
% EfficientNet-B0 classification decision.
%
% USAGE:
%   result = generate_gradcam('fundus.jpg', 'model.mat', './output/')
%   result = generate_gradcam('fundus.jpg', 'model.mat', './output/', 'top_conv')
%
% INPUTS:
%   imagePath   - (string) Path to the fundus image
%   modelPath   - (string) Path to the trained .mat model file
%   outputDir   - (string) Directory to save the heatmap overlay
%   targetLayer - (string, optional) Name of the convolutional layer to
%                 use for Grad-CAM. Defaults to the last conv layer.
%
% OUTPUT:
%   result - (struct):
%     .gradcam_heatmap_path - Path to saved heatmap overlay image
%     .target_layer         - Layer used for activation mapping
%     .predicted_class      - The class the heatmap explains
%
% REQUIRES:
%   - Deep Learning Toolbox
%   - A trained EfficientNet-B0 model (.mat file with 'net' variable)
%
% NOTE: RESEARCH SCREENING tool — not for autonomous diagnosis.
%
% Copyright (c) 2026 RetinaShield Research Project

    arguments
        imagePath   (1,1) string {mustBeFile}
        modelPath   (1,1) string
        outputDir   (1,1) string
        targetLayer (1,1) string = ""
    end

    if ~isfolder(outputDir)
        mkdir(outputDir);
    end

    [~, baseName, ~] = fileparts(imagePath);
    inputSize = [224, 224, 3];

    result = struct();
    result.gradcam_heatmap_path = '';
    result.target_layer = '';
    result.predicted_class = '';

    % -----------------------------------------------------------------------
    % 1. Check model availability
    % -----------------------------------------------------------------------
    if ~isfile(modelPath)
        warning('generate_gradcam:noModel', ...
                'No trained model at: %s. Cannot generate Grad-CAM.', modelPath);
        return;
    end

    % -----------------------------------------------------------------------
    % 2. Load model
    % -----------------------------------------------------------------------
    modelData = load(modelPath);
    if ~isfield(modelData, 'net')
        error('generate_gradcam:invalidModel', 'Model file must contain a "net" variable.');
    end
    net = modelData.net;

    % -----------------------------------------------------------------------
    % 3. Determine target layer
    %    For EfficientNet-B0, the last convolutional layer is typically
    %    'top_conv' or the last layer before global average pooling.
    % -----------------------------------------------------------------------
    if targetLayer == ""
        % Auto-detect: find the last convolutional layer
        lgraph = layerGraph(net);
        layers = lgraph.Layers;
        convLayers = layers(arrayfun(@(l) isa(l, 'nnet.cnn.layer.Convolution2DLayer'), layers));
        if isempty(convLayers)
            error('generate_gradcam:noConvLayer', 'No convolutional layers found in model.');
        end
        targetLayer = convLayers(end).Name;
    end
    result.target_layer = char(targetLayer);

    % -----------------------------------------------------------------------
    % 4. Preprocess image
    % -----------------------------------------------------------------------
    img = imread(imagePath);
    imgResized = imresize(img, inputSize(1:2));
    imgInput = im2single(imgResized);

    % -----------------------------------------------------------------------
    % 5. Generate Grad-CAM
    %    Uses MATLAB's built-in gradCAM function (R2021a+)
    % -----------------------------------------------------------------------
    try
        % Classify to get the predicted label
        [predictedLabel, ~] = classify(net, imgInput);
        result.predicted_class = char(predictedLabel);

        % Generate Grad-CAM map
        gradcamMap = gradCAM(net, imgInput, predictedLabel, ...
            'FeatureLayer', targetLayer);

        % -----------------------------------------------------------------------
        % 6. Create overlay visualization
        % -----------------------------------------------------------------------
        % Resize heatmap to original image size
        heatmapResized = imresize(gradcamMap, [size(img, 1), size(img, 2)]);

        % Apply colormap
        heatmapColor = ind2rgb(im2uint8(heatmapResized), jet(256));
        heatmapColor = im2uint8(heatmapColor);

        % Blend with original image (alpha = 0.5)
        alpha = 0.5;
        overlay = im2uint8(double(img) * (1 - alpha) + double(heatmapColor) * alpha);

        % Add text annotation
        overlayAnnotated = insertText(overlay, [10, 10], ...
            sprintf('Grad-CAM: %s (RESEARCH ONLY)', char(predictedLabel)), ...
            'FontSize', 18, 'TextColor', 'white', 'BoxColor', 'black', ...
            'BoxOpacity', 0.6);

        % Save
        heatmapPath = fullfile(outputDir, [char(baseName) '_gradcam.png']);
        imwrite(overlayAnnotated, heatmapPath);
        result.gradcam_heatmap_path = char(heatmapPath);

        fprintf('[RetinaShield GradCAM] Heatmap saved: %s | Class: %s\n', ...
                heatmapPath, char(predictedLabel));

    catch ME
        warning('generate_gradcam:failed', 'Grad-CAM generation failed: %s', ME.message);
    end
end
