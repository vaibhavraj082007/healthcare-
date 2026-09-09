function result = classify_dr(imagePath, modelPath)
% CLASSIFY_DR Classify diabetic retinopathy severity using EfficientNet-B0.
%
% Uses a fine-tuned EfficientNet-B0 network to classify fundus images into
% one of five DR severity grades (International Clinical DR Scale):
%   0 = No DR
%   1 = Mild NPDR (Non-Proliferative Diabetic Retinopathy)
%   2 = Moderate NPDR
%   3 = Severe NPDR
%   4 = Proliferative DR (PDR)
%
% USAGE:
%   result = classify_dr('path/to/fundus.jpg', 'path/to/model.mat')
%   result = classify_dr('path/to/fundus.jpg')  % Uses default model path
%
% INPUTS:
%   imagePath - (string) Full path to the input fundus image
%   modelPath - (string, optional) Path to trained .mat weights file
%
% OUTPUT:
%   result - (struct) Classification results:
%     .model             - 'EfficientNet-B0'
%     .predicted_grade   - Integer 0-4
%     .grade_label       - Human-readable grade label
%     .confidence        - Confidence of predicted class
%     .class_probabilities - [1x5] softmax probability vector
%     .model_trained     - true if using real trained weights
%
% REQUIRES:
%   - Deep Learning Toolbox
%   - Deep Learning Toolbox Model for EfficientNet-B0 Network (support package)
%
% NOTE: RESEARCH SCREENING tool — not for autonomous diagnosis.
% WARNING: If no trained model is found, this returns a placeholder result
%          clearly marked as UNTRAINED. Never fabricate predictions.
%
% Copyright (c) 2026 RetinaShield Research Project

    arguments
        imagePath (1,1) string {mustBeFile}
        modelPath (1,1) string = ""
        iqaStatus (1,1) string = ""
    end

    if iqaStatus == ""
        % Run quality assessment if not provided
        iqaResult = quality_assessment(imagePath);
        iqaStatus = iqaResult.status;
    end
    
    gradeLabels = {'No DR', 'Mild NPDR', 'Moderate NPDR', 'Severe NPDR', 'Proliferative DR'};
    inputSize = [224, 224, 3];
    
    result = struct();
    result.model = 'EfficientNet-B0';
    result.predicted_grade = -1;
    result.grade_label = 'Unknown';
    result.confidence = 0;
    result.class_probabilities = zeros(1, 5);
    result.model_trained = false;

    if strcmp(iqaStatus, 'ungradeable')
        warning('classify_dr:ungradeable', 'Image is ungradeable. Refusing to classify.');
        result.grade_label = 'UNGRADEABLE — Must never be reported as No DR';
        fprintf('[RetinaShield Classify] Image ungradeable. Returning safe placeholder.\n');
        return;
    end
    
    % -----------------------------------------------------------------------
    % 1. Check for trained model
    % -----------------------------------------------------------------------
    if modelPath == ""
        % Default model location
        modelPath = fullfile(fileparts(mfilename('fullpath')), '..', 'models', 'efficientnet_b0_dr.mat');
    end
    
    hasTrainedModel = isfile(modelPath);
    
    if ~hasTrainedModel
        warning('classify_dr:noModel', ...
                ['No trained model found at: %s\n' ...
                 'Returning UNTRAINED placeholder result.\n' ...
                 'Train the model using a DR dataset (e.g., APTOS 2019) before clinical use.'], ...
                modelPath);
        
        result.model_trained = false;
        result.predicted_grade = -1;
        result.grade_label = 'UNTRAINED — No prediction available';
        result.confidence = 0;
        result.class_probabilities = [0.2, 0.2, 0.2, 0.2, 0.2];  % Uniform = no information
        
        fprintf('[RetinaShield Classify] WARNING: No trained model. Returning placeholder.\n');
        return;
    end
    
    % -----------------------------------------------------------------------
    % 2. Load trained model
    % -----------------------------------------------------------------------
    fprintf('[RetinaShield Classify] Loading model from: %s\n', modelPath);
    modelData = load(modelPath);
    
    % Expect the .mat file to contain a 'net' variable (SeriesNetwork or DAGNetwork)
    if isfield(modelData, 'net')
        net = modelData.net;
    else
        fieldNames = fieldnames(modelData);
        error('classify_dr:invalidModel', ...
              'Model file does not contain a "net" variable. Found: %s', ...
              strjoin(fieldNames, ', '));
    end
    
    % -----------------------------------------------------------------------
    % 3. Preprocess input image
    %    Resize to EfficientNet-B0 input size and normalize
    % -----------------------------------------------------------------------
    img = imread(imagePath);
    img = imresize(img, inputSize(1:2));
    
    % Normalize to [0, 1] (standard for EfficientNet)
    img = im2single(img);
    
    % -----------------------------------------------------------------------
    % 4. Classify
    % -----------------------------------------------------------------------
    [predictedLabel, scores] = classify(net, img);
    
    % Convert categorical to grade index
    gradeIdx = find(strcmp(gradeLabels, char(predictedLabel)));
    if isempty(gradeIdx)
        gradeIdx = double(predictedLabel);  % If labels are numeric
    end
    predictedGrade = gradeIdx - 1;  % 0-indexed
    
    % -----------------------------------------------------------------------
    % 5. Build result
    % -----------------------------------------------------------------------
    result.predicted_grade = predictedGrade;
    result.grade_label = gradeLabels{predictedGrade + 1};
    result.confidence = max(scores);
    result.class_probabilities = double(scores);
    result.model_trained = true;
    
    fprintf('[RetinaShield Classify] Grade: %d (%s) | Confidence: %.3f\n', ...
            predictedGrade, result.grade_label, result.confidence);
end
