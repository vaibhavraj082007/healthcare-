function result = segment_optic_disc(imageInput, options)
% SEGMENT_OPTIC_DISC Localize and segment the optic disc in fundus images.
%
% Implements a multi-cue classical baseline resistant to false positives from
% hard exudates, cotton wool spots, and camera flash reflections. Evaluates
% vessel convergence, scale filtering, and circularity. Fails explicitly
% with diagnostic reasons when the disc is outside the field of view or obscured.
%
% USAGE:
%   result = segment_optic_disc('path/to/fundus.jpg')
%   result = segment_optic_disc(img, 'fovMask', fovMask)
%   result = segment_optic_disc(img, 'outputDir', './out', 'modelPath', './od_model.mat')
%
% INPUTS:
%   imageInput - (string or uint8 matrix) Path to image file or RGB image
%   options    - Name-value pairs:
%       'fovMask'        - (logical matrix) Optional retinal field-of-view mask
%       'vesselMask'     - (logical matrix) Optional precomputed vessel mask
%       'outputDir'      - (string) Optional directory to save mask PNG
%       'modelPath'      - (string) Optional path to trained DL weights (.mat)
%       'minConfidence'  - (double) Minimum score threshold (default: 0.35)
%
% OUTPUT:
%   result - (struct):
%     .detected          - Boolean true if optic disc successfully localized
%     .center_x          - Centroid x-coordinate in original image space (or NaN)
%     .center_y          - Centroid y-coordinate in original image space (or NaN)
%     .radius            - Estimated disc radius in pixels (or NaN)
%     .mask              - 2D logical segmentation mask (original image size)
%     .mask_path         - Path to saved PNG mask
%     .confidence        - Confidence score between 0.0 and 1.0
%     .is_reliable       - Boolean flag indicating clinical reliability
%     .failure_reason    - Diagnostic reason if localization failed
%     .algorithm_version - Version string
%     .method            - Algorithm method description
%
% NOTE: EXPERIMENTAL BASELINE — Not for autonomous clinical diagnosis.
%
% Copyright (c) 2026 RetinaShield Research Project

    arguments
        imageInput
        options.fovMask = []
        options.vesselMask = []
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
            error('segment_optic_disc:fileNotFound', 'Image file not found: %s', imagePath);
        end
        img = imread(imagePath);
        [~, baseName, ~] = fileparts(imagePath);
    elseif isnumeric(imageInput)
        img = imageInput;
    else
        error('segment_optic_disc:invalidInput', 'Input must be file path or image matrix.');
    end

    if size(img, 3) ~= 3
        img = repmat(img, [1 1 3]);
    end

    [rows, cols, ~] = size(img);

    % Default output struct (fail-safe initialized with explicit NaN / false)
    result = struct();
    result.detected = false;
    result.center_x = NaN;
    result.center_y = NaN;
    result.radius = NaN;
    result.mask = false(rows, cols);
    result.mask_path = '';
    result.confidence = 0.0;
    result.is_reliable = false;
    result.failure_reason = '';
    result.algorithm_version = algVersion;
    result.method = 'classical_multicue_convergence';

    % 2. Get or compute FOV mask
    if isempty(options.fovMask)
        fovResult = segment_fov(img);
        fovMask = fovResult.mask;
    else
        fovMask = logical(options.fovMask);
        if size(fovMask, 1) ~= rows || size(fovMask, 2) ~= cols
            fovMask = imresize(fovMask, [rows, cols], 'nearest');
        end
    end

    % If FOV is degenerately small, fail early
    if sum(fovMask(:)) < (rows * cols * 0.05)
        result.failure_reason = 'NO_VALID_FOV_FOR_OD_SEARCH';
        return;
    end

    % 3. Check for learned model
    if options.modelPath ~= "" && isfile(options.modelPath)
        try
            result = predict_od_dl(img, options.modelPath, fovMask, result);
            result.algorithm_version = '0.2.0-learned';
            result.method = 'learned_model';
            if result.detected
                if options.outputDir ~= ""
                    save_mask(result.mask, options.outputDir, baseName);
                end
                return;
            end
        catch ME
            warning('segment_optic_disc:dlFailed', 'Learned OD model failed (%s). Falling back.', ME.message);
        end
    end

    % 4. Classical Multi-Cue Baseline
    try
        redCh = double(img(:, :, 1));
        greenCh = double(img(:, :, 2));
        blueCh = double(img(:, :, 3));

        % Estimated expected disc diameter ~ 1/7 to 1/10 of fundus diameter
        minDim = min(rows, cols);
        expectedRadius = round(minDim * 0.075);
        minRadius = max(8, round(expectedRadius * 0.5));
        maxRadius = round(expectedRadius * 1.8);

        % Erode FOV mask so we don't pick bright boundary reflections
        safeFov = imerode(fovMask, strel('disk', max(10, round(expectedRadius * 0.4))));

        % --- Cue A: Scale-filtered bright region (reject small exudates) ---
        % Opening with large disk removes punctate exudates while keeping the large disc
        scaleDisk = max(5, round(expectedRadius * 0.35));
        redOpened = imopen(redCh, strel('disk', scaleDisk));
        
        % Normalize within safe FOV
        fovPixels = redOpened(safeFov);
        if isempty(fovPixels)
            result.failure_reason = 'FOV_EMPTY_OR_COMPLETELY_ERODED';
            return;
        end

        p90 = prctile(fovPixels, 90);
        p10 = prctile(fovPixels, 10);
        redNorm = (redOpened - p10) ./ max(1.0, (p90 - p10));
        redNorm(~safeFov) = 0;
        redNorm = max(0, min(1, redNorm));

        % --- Cue B: Vessel Convergence / Vessel Density ---
        % The optic disc is the anatomical origin of retinal vessels.
        if isempty(options.vesselMask)
            % Quick vessel response: morphological top-hat on green channel
            greenClahe = adapthisteq(uint8(greenCh), 'NumTiles', [8 8], 'ClipLimit', 0.02);
            greenInv = 255 - double(greenClahe);
            vesselResponse = double(imtophat(uint8(greenInv), strel('disk', 4)));
            vesselThresh = prctile(vesselResponse(safeFov), 80);
            vesselBinary = (vesselResponse > vesselThresh) & safeFov;
        else
            vesselBinary = logical(options.vesselMask) & safeFov;
        end

        % Local vessel density map (box filter of vessel presence)
        vesselDensity = imfilter(double(vesselBinary), fspecial('disk', expectedRadius), 'replicate');
        maxVasc = max(vesselDensity(safeFov));
        if maxVasc > 0
            vesselDensityNorm = vesselDensity ./ maxVasc;
        else
            vesselDensityNorm = zeros(rows, cols);
        end

        % --- Cue C: Flash Reflection Penalization ---
        % Flash artifacts have saturated R, G, B with virtually zero vessel density
        saturatedMask = (redCh > 245) & (greenCh > 245) & (blueCh > 245);
        glarePenalty = imfilter(double(saturatedMask), fspecial('disk', expectedRadius), 'replicate');
        glarePenalty = max(0, min(1, glarePenalty / (pi * expectedRadius^2 * 0.3)));

        % --- Combined Saliency Map ---
        % Score = Red Brightness * 0.40 + Vessel Density * 0.50 - Glare Penalty * 0.35
        saliency = (0.40 * redNorm) + (0.50 * vesselDensityNorm) - (0.35 * glarePenalty);
        saliency(~safeFov) = 0;

        % Find candidate connected components in top 5% saliency
        saliencyValues = saliency(safeFov);
        threshScore = prctile(saliencyValues, 95);
        candMask = (saliency >= threshScore) & safeFov;
        candMask = imclose(candMask, strel('disk', round(scaleDisk / 2)));
        candMask = imfill(candMask, 'holes');

        cc = bwconncomp(candMask);
        if cc.NumObjects == 0
            result.failure_reason = 'NO_RELIABLE_DISC_CANDIDATE';
            return;
        end

        stats = regionprops(cc, 'Area', 'Centroid', 'EquivDiameter', 'PixelIdxList');

        bestCandidate = struct('score', -Inf, 'center', [NaN, NaN], 'radius', NaN, 'pixelList', []);

        for k = 1:numel(stats)
            area = stats(k).Area;
            radius = stats(k).EquivDiameter / 2;
            cx = stats(k).Centroid(1);
            cy = stats(k).Centroid(2);

            % Filter by size: must not be tiny noise or entire image
            if radius < (minRadius * 0.5) || radius > (maxRadius * 2.0)
                continue;
            end

            % Mean saliency in component
            meanSaliency = mean(saliency(stats(k).PixelIdxList));

            % Check circularity
            compMask = false(rows, cols);
            compMask(stats(k).PixelIdxList) = true;
            perim = regionprops(compMask, 'Perimeter');
            if isempty(perim) || perim(1).Perimeter == 0
                circularity = 0;
            else
                circularity = (4 * pi * area) / (perim(1).Perimeter^2);
                circularity = min(1.0, circularity);
            end

            % Check distance to FOV border
            distToBorder = min([cx, cols - cx, cy, rows - cy]);
            if ~safeFov(round(min(max(1, cy), rows)), round(min(max(1, cx), cols)))
                % Candidate center is outside safe FOV
                continue;
            end

            % Composite candidate score
            candScore = (0.55 * meanSaliency) + (0.35 * circularity) + (0.10 * (1 - abs(radius - expectedRadius)/expectedRadius));

            if candScore > bestCandidate.score
                bestCandidate.score = candScore;
                bestCandidate.center = [cx, cy];
                bestCandidate.radius = max(minRadius, min(maxRadius, radius));
                bestCandidate.pixelList = stats(k).PixelIdxList;
            end
        end

        % Validate candidate against minimum confidence
        if bestCandidate.score < options.minConfidence || isnan(bestCandidate.center(1))
            result.detected = false;
            result.confidence = max(0.0, bestCandidate.score);
            result.is_reliable = false;
            result.failure_reason = 'LOW_CONFIDENCE_NO_CONVERGENCE';
            return;
        end

        % Check if disc is cut off at the edge of FOV
        discCenterX = bestCandidate.center(1);
        discCenterY = bestCandidate.center(2);
        discRadius = bestCandidate.radius;

        % Create circular disc mask
        [X, Y] = meshgrid(1:cols, 1:rows);
        distMap = sqrt((X - discCenterX).^2 + (Y - discCenterY).^2);
        odMask = (distMap <= discRadius);

        % Portion of disc inside FOV
        discInFovRatio = sum(odMask(:) & fovMask(:)) / max(1, sum(odMask(:)));
        if discInFovRatio < 0.60
            % Disc is predominantly outside or cut off by the field of view
            result.detected = false;
            result.confidence = bestCandidate.score * discInFovRatio;
            result.is_reliable = false;
            result.failure_reason = 'DISC_OUTSIDE_OR_CLIPPED_BY_FOV';
            return;
        end

        % Refine segmentation boundary: intersect circular model with bright gradient region
        roiY = max(1, round(discCenterY - discRadius*1.3)) : min(rows, round(discCenterY + discRadius*1.3));
        roiX = max(1, round(discCenterX - discRadius*1.3)) : min(cols, round(discCenterX + discRadius*1.3));
        roiRed = redCh(roiY, roiX);
        roiThresh = prctile(roiRed(:), 60);
        refinedRoi = (roiRed >= roiThresh);
        refinedRoi = imfill(refinedRoi, 'holes');
        refinedMask = false(rows, cols);
        refinedMask(roiY, roiX) = refinedRoi;
        finalOdMask = (odMask & refinedMask) | (distMap <= (discRadius * 0.75));
        finalOdMask = finalOdMask & fovMask;

        % Success!
        result.detected = true;
        result.center_x = discCenterX;
        result.center_y = discCenterY;
        result.radius = discRadius;
        result.mask = finalOdMask;
        result.confidence = min(1.0, max(0.1, bestCandidate.score));
        result.is_reliable = (result.confidence >= 0.50);
        result.failure_reason = '';

    catch ME
        result.detected = false;
        result.is_reliable = false;
        result.failure_reason = sprintf('OD_DETECTION_ERROR: %s', ME.message);
    end

    % 5. Save mask artifact if output directory provided
    if options.outputDir ~= "" && result.detected
        maskPath = fullfile(options.outputDir, sprintf('%s_optic_disc_mask.png', char(baseName)));
        if ~isfolder(options.outputDir)
            mkdir(options.outputDir);
        end
        imwrite(result.mask, maskPath);
        result.mask_path = char(maskPath);
    end
end


function result = predict_od_dl(img, modelPath, fovMask, result)
% PREDICT_OD_DL Deep learning OD localization hook.
    modelData = load(modelPath);
    if isfield(modelData, 'detector')
        % Object detector hook (e.g. YOLO or R-CNN)
        [bboxes, scores] = detect(modelData.detector, img);
        if ~isempty(bboxes) && scores(1) > 0.40
            bbox = bboxes(1, :);
            cx = bbox(1) + bbox(3)/2;
            cy = bbox(2) + bbox(4)/2;
            r = min(bbox(3), bbox(4)) / 2;
            [X, Y] = meshgrid(1:size(img, 2), 1:size(img, 1));
            odMask = (sqrt((X - cx).^2 + (Y - cy).^2) <= r) & fovMask;
            
            result.detected = true;
            result.center_x = cx;
            result.center_y = cy;
            result.radius = r;
            result.mask = odMask;
            result.confidence = double(scores(1));
            result.is_reliable = true;
            result.failure_reason = '';
        end
    end
end
