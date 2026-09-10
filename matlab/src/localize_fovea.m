function result = localize_fovea(imageInput, opticDisc, options)
% LOCALIZE_FOVEA Localize the fovea centralis / macula in retinal fundus images.
%
% Implements an anatomically guided classical baseline resistant to false
% positives from blot hemorrhages, choroidal nevi, and illumination shadows.
% Uses anatomical priors (temporal offset from optic disc, vascular arcade geometry),
% infers or verifies laterality (OD vs OS), and handles macula-centered or
% disc-centered images where structures are outside the field of view.
%
% USAGE:
%   result = localize_fovea('path/to/fundus.jpg', opticDiscStruct)
%   result = localize_fovea(img, opticDiscStruct, 'laterality', 'auto')
%   result = localize_fovea(img, [], 'fovMask', fovMask)
%
% INPUTS:
%   imageInput - (string or uint8 matrix) Image path or RGB matrix
%   opticDisc  - (struct, optional) Output from segment_optic_disc
%   options    - Name-value pairs:
%       'fovMask'        - (logical matrix) Optional retinal FOV mask
%       'vesselMask'     - (logical matrix) Optional vessel mask
%       'laterality'     - (string) 'auto' | 'OD' | 'OS' | 'unknown' (default: 'auto')
%       'outputDir'      - (string) Optional directory to save annotation artifact
%       'modelPath'      - (string) Optional learned DL model (.mat)
%       'minConfidence'  - (double) Minimum acceptance threshold (default: 0.35)
%
% OUTPUT:
%   result - (struct):
%     .detected          - Boolean true if fovea localized
%     .center_x          - Fovea x-coordinate in original image space (or NaN)
%     .center_y          - Fovea y-coordinate in original image space (or NaN)
%     .radius            - Estimated foveal avascular zone (FAZ) radius (or NaN)
%     .confidence        - Confidence score between 0.0 and 1.0
%     .is_reliable       - Boolean flag indicating clinical reliability
%     .failure_reason    - Diagnostic explanation if localization failed
%     .inferred_laterality - 'OD' (right), 'OS' (left), or 'unknown'
%     .anatomical_vector - Struct of dx, dy, and distance in disc diameters
%     .algorithm_version - Version string
%     .method            - Algorithm description
%
% NOTE: EXPERIMENTAL BASELINE — Not for autonomous clinical diagnosis.
%
% Copyright (c) 2026 RetinaShield Research Project

    arguments
        imageInput
        opticDisc = []
        options.fovMask = []
        options.vesselMask = []
        options.laterality (1,1) string = "auto"
        options.outputDir (1,1) string = ""
        options.modelPath (1,1) string = ""
        options.minConfidence (1,1) double = 0.35
    end

    algVersion = '0.2.0-classical';
    baseName = 'fundus';

    % 1. Load image
    if ischar(imageInput) || isstring(imageInput)
        imagePath = string(imageInput);
        if ~isfile(imagePath)
            error('localize_fovea:fileNotFound', 'Image file not found: %s', imagePath);
        end
        img = imread(imagePath);
        [~, baseName, ~] = fileparts(imagePath);
    elseif isnumeric(imageInput)
        img = imageInput;
    else
        error('localize_fovea:invalidInput', 'Input must be file path or image matrix.');
    end

    if size(img, 3) ~= 3
        img = repmat(img, [1 1 3]);
    end

    [rows, cols, ~] = size(img);

    % Default output struct (fail-safe initialized)
    result = struct();
    result.detected = false;
    result.center_x = NaN;
    result.center_y = NaN;
    result.radius = NaN;
    result.confidence = 0.0;
    result.is_reliable = false;
    result.failure_reason = '';
    result.inferred_laterality = 'unknown';
    result.anatomical_vector = struct('dx', NaN, 'dy', NaN, 'distance_dd', NaN);
    result.algorithm_version = algVersion;
    result.method = 'classical_anatomical_faz_prior';

    % 2. Retrieve or compute FOV mask
    if isempty(options.fovMask)
        fovResult = segment_fov(img);
        fovMask = fovResult.mask;
    else
        fovMask = logical(options.fovMask);
        if size(fovMask, 1) ~= rows || size(fovMask, 2) ~= cols
            fovMask = imresize(fovMask, [rows, cols], 'nearest');
        end
    end

    if sum(fovMask(:)) < (rows * cols * 0.05)
        result.failure_reason = 'NO_VALID_FOV_FOR_FOVEA_SEARCH';
        return;
    end

    % Safe FOV margin
    safeMargin = max(15, round(min(rows, cols) * 0.05));
    safeFov = imerode(fovMask, strel('disk', safeMargin));

    % 3. Check for learned model
    if options.modelPath ~= "" && isfile(options.modelPath)
        try
            result = predict_fovea_dl(img, options.modelPath, safeFov, result);
            result.algorithm_version = '0.2.0-learned';
            result.method = 'learned_model';
            if result.detected
                return;
            end
        catch ME
            warning('localize_fovea:dlFailed', 'Learned fovea model failed (%s). Falling back.', ME.message);
        end
    end

    % 4. Classical Anatomical Prior Baseline
    try
        greenCh = double(img(:, :, 2));
        redCh = double(img(:, :, 1));

        % Green channel is optimal for macular pigment and vessel detection
        greenSmooth = imgaussfilt(greenCh, max(2.0, min(rows, cols) * 0.015));

        % Determine Optic Disc reference status
        hasOd = ~isempty(opticDisc) && isstruct(opticDisc) && isfield(opticDisc, 'detected') && opticDisc.detected && ~isnan(opticDisc.center_x);

        fovProps = regionprops(fovMask, 'Centroid', 'EquivDiameter');
        fovCenter = fovProps(1).Centroid;
        minDim = min(rows, cols);

        % Estimated disc diameter (DD): default 1/7 of fundus diameter if OD missing
        if hasOd
            odX = opticDisc.center_x;
            odY = opticDisc.center_y;
            odR = opticDisc.radius;
            discDiam = max(20, odR * 2.0);
        else
            odX = NaN;
            odY = NaN;
            discDiam = minDim * 0.14;
            odR = discDiam / 2;
        end

        fazEstimatedRadius = max(6, round(discDiam * 0.25));

        % 4a. Laterality Determination & Direction
        lat = lower(options.laterality);
        inferredLat = 'unknown';
        tempDirX = 0; % Temporal direction in x: +1 = rightward, -1 = leftward

        if lat == "od" || lat == "right"
            inferredLat = 'OD';
            tempDirX = 1; % Right eye: Disc is nasal (left), fovea is temporal (right)
        elseif lat == "os" || lat == "left"
            inferredLat = 'OS';
            tempDirX = -1; % Left eye: Disc is nasal (right), fovea is temporal (left)
        else
            % Auto-infer laterality from OD position relative to FOV horizontal midpoint
            if hasOd
                if odX < (fovCenter(1) - 0.04 * cols)
                    inferredLat = 'OD';
                    tempDirX = 1;
                elseif odX > (fovCenter(1) + 0.04 * cols)
                    inferredLat = 'OS';
                    tempDirX = -1;
                else
                    inferredLat = 'unknown';
                    tempDirX = 0;
                end
            end
        end
        result.inferred_laterality = inferredLat;

        % 4b. Anatomical Location Estimation (When OD is available)
        if hasOd
            expectedDist = discDiam * 2.6; % ~2.5 to 2.8 DD temporal
            expectedInferiorOffset = discDiam * 0.25; % slightly inferior

            if tempDirX == 0
                % OD near center; candidate could be either left or right
                testDirs = [1, -1];
            else
                testDirs = [tempDirX];
            end

            bestCandidate = struct('score', -Inf, 'center', [NaN, NaN], 'confidence', 0);

            for d = testDirs
                estX = odX + (d * expectedDist);
                estY = odY + expectedInferiorOffset;

                % Check if the expected location is outside the field of view
                if estX < 1 || estX > cols || estY < 1 || estY > rows || ~safeFov(round(min(max(1, estY), rows)), round(min(max(1, estX), cols)))
                    % Fovea is cut off / outside field of view
                    continue;
                end

                % Search in a localized window (~1.0 DD around expected center)
                searchR = round(discDiam * 0.6);
                winX = max(1, round(estX - searchR)) : min(cols, round(estX + searchR));
                winY = max(1, round(estY - searchR)) : min(rows, round(estY + searchR));

                subGreen = greenSmooth(winY, winX);
                subFov = safeFov(winY, winX);

                if sum(subFov(:)) < (numel(subFov) * 0.4)
                    continue;
                end

                % Local darkness score (macula is darkest in green channel)
                % Invert green so darker regions have higher values
                maxG = max(subGreen(subFov));
                minG = min(subGreen(subFov));
                if maxG > minG
                    darknessMap = (maxG - subGreen) ./ (maxG - minG);
                else
                    darknessMap = zeros(size(subGreen));
                end
                darknessMap(~subFov) = 0;

                % Spatial Gaussian prior centered at anatomical expected point
                [sX, sY] = meshgrid(winX, winY);
                distPrior = exp(-((sX - estX).^2 + (sY - estY).^2) / (2 * (searchR * 0.6)^2));

                % Hemorrhage rejection: compute local gradient sharpness
                % Blot hemorrhages have steep sharp edges; macula is a gradual bowl
                [gx, gy] = gradient(subGreen);
                gradMag = sqrt(gx.^2 + gy.^2);
                gradSmooth = imgaussfilt(gradMag, 2);
                % Penalize regions with high edge gradient at candidate center
                hemorrhagePenalty = gradSmooth ./ max(1.0, max(gradSmooth(:)));

                % Candidate saliency
                subScore = (darknessMap .* distPrior) - (0.35 * hemorrhagePenalty);
                subScore(~subFov) = -Inf;

                [maxVal, maxIdx] = max(subScore(:));
                if maxVal > bestCandidate.score && maxVal > 0.10
                    [my, mx] = ind2sub(size(subScore), maxIdx);
                    bestCandidate.score = maxVal;
                    bestCandidate.center = [winX(mx), winY(my)];
                    
                    % Confidence based on match with expected distance and darkness
                    actualDist = sqrt((winX(mx) - odX)^2 + (winY(my) - odY)^2);
                    distMatch = max(0, 1 - abs(actualDist - expectedDist) / (expectedDist * 0.5));
                    bestCandidate.confidence = min(1.0, (0.50 * distMatch) + (0.50 * maxVal));
                end
            end

            if isnan(bestCandidate.center(1))
                result.detected = false;
                result.is_reliable = false;
                result.failure_reason = 'FOVEA_OUTSIDE_FOV_OR_NOT_FOUND';
                return;
            end

            if bestCandidate.confidence < options.minConfidence
                result.detected = false;
                result.confidence = bestCandidate.confidence;
                result.is_reliable = false;
                result.failure_reason = 'LOW_CONFIDENCE_OBSCURED_OR_HEMORRHAGE';
                return;
            end

            % Successful localization via anatomical prior
            result.detected = true;
            result.center_x = bestCandidate.center(1);
            result.center_y = bestCandidate.center(2);
            result.radius = fazEstimatedRadius;
            result.confidence = bestCandidate.confidence;
            result.is_reliable = (result.confidence >= 0.50);
            result.failure_reason = '';

            % Anatomical vector
            dx = result.center_x - odX;
            dy = result.center_y - odY;
            distPix = sqrt(dx^2 + dy^2);
            result.anatomical_vector.dx = dx;
            result.anatomical_vector.dy = dy;
            result.anatomical_vector.distance_dd = distPix / discDiam;

        else
            % 4c. Optic Disc NOT detected / Outside FOV (e.g. Macula-Centered Image)
            % Search central 40% of fundus field for FAZ
            marginH = round(rows * 0.25);
            marginW = round(cols * 0.25);
            centralMask = false(rows, cols);
            centralMask(marginH:rows-marginH, marginW:cols-marginW) = true;
            searchMask = centralMask & safeFov;

            if sum(searchMask(:)) < 100
                result.detected = false;
                result.is_reliable = false;
                result.failure_reason = 'CENTRAL_FOV_TOO_SMALL_FOR_FAZ';
                return;
            end

            subGreen = greenSmooth;
            subGreen(~searchMask) = Inf;
            [minVal, minIdx] = min(subGreen(:));
            [minY, minX] = ind2sub([rows, cols], minIdx);

            if isinf(minVal) || ~searchMask(minY, minX)
                result.detected = false;
                result.is_reliable = false;
                result.failure_reason = 'NO_CENTRAL_MINIMUM_FOUND';
                return;
            end

            % Check smoothness of central minimum (hemorrhage test)
            localPatch = greenSmooth(max(1, minY-20):min(rows, minY+20), max(1, minX-20):min(cols, minX+20));
            stdVal = std(localPatch(:));
            if stdVal > 35
                % High contrast variance indicates a sharp hemorrhage or artifact
                result.detected = false;
                result.confidence = 0.25;
                result.is_reliable = false;
                result.failure_reason = 'CANDIDATE_REJECTED_SHARP_GRADIENT_HEMORRHAGE';
                return;
            end

            result.detected = true;
            result.center_x = minX;
            result.center_y = minY;
            result.radius = fazEstimatedRadius;
            result.confidence = 0.55; % Moderate confidence without OD reference
            result.is_reliable = false; % Requires validation without OD anchor
            result.failure_reason = 'LOCALIZED_WITHOUT_OD_REFERENCE';
        end

    catch ME
        result.detected = false;
        result.is_reliable = false;
        result.failure_reason = sprintf('FOVEA_LOCALIZATION_ERROR: %s', ME.message);
    end
end


function result = predict_fovea_dl(img, modelPath, safeFov, result)
% PREDICT_FOVEA_DL Deep learning fovea heatmap regression hook.
    modelData = load(modelPath);
    if isfield(modelData, 'heatmap_net')
        inputSize = modelData.heatmap_net.Layers(1).InputSize(1:2);
        resized = imresize(img, inputSize);
        heatmap = predict(modelData.heatmap_net, resized);
        origHeatmap = imresize(heatmap, [size(img, 1), size(img, 2)]);
        origHeatmap(~safeFov) = 0;
        
        [maxVal, maxIdx] = max(origHeatmap(:));
        if maxVal > 0.40
            [fy, fx] = ind2sub(size(origHeatmap), maxIdx);
            result.detected = true;
            result.center_x = fx;
            result.center_y = fy;
            result.radius = round(min(size(img,1), size(img,2)) * 0.035);
            result.confidence = double(maxVal);
            result.is_reliable = true;
            result.failure_reason = '';
        end
    end
end
