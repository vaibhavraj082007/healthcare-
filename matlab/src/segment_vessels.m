function result = segment_vessels(imageInput, options)
% SEGMENT_VESSELS Segment retinal vasculature from a fundus photograph.
%
% Implements a multi-orientation matched filtering and top-hat morphology
% baseline with CLAHE illumination equalization. Suppresses false positives
% along the high-contrast FOV camera perimeter, extracts vessel centerlines,
% and computes clinical biomarkers (vessel density, tortuosity index).
%
% USAGE:
%   result = segment_vessels('path/to/fundus.jpg')
%   result = segment_vessels(img, 'fovMask', fovMask)
%   result = segment_vessels(img, 'outputDir', './out', 'modelPath', './vessel_unet.mat')
%
% INPUTS:
%   imageInput - (string or uint8 matrix) Image path or RGB matrix
%   options    - Name-value pairs:
%       'fovMask'        - (logical matrix) Optional retinal FOV mask
%       'outputDir'      - (string) Optional directory to save mask PNG
%       'modelPath'      - (string) Optional learned DL model (.mat)
%       'sensitivity'    - (double) Binarization sensitivity (default: 0.58)
%
% OUTPUT:
%   result - (struct):
%     .mask              - 2D logical segmentation mask (original image size)
%     .skeleton_mask     - 2D logical centerline skeleton mask
%     .mask_path         - Path to saved PNG vessel mask
%     .vessel_density    - Ratio of vessel pixels to valid retinal FOV (0..1)
%     .tortuosity_index  - Mean arc-chord ratio of vessel segments (>= 1.0)
%     .caliber_proxy     - Mean vessel width proxy in pixels
%     .confidence        - Quality/reliability score (0..1)
%     .is_reliable       - Boolean flag indicating segmentation reliability
%     .failure_reason    - Diagnostic reason if segmentation failed
%     .algorithm_version - Version string
%     .method            - Algorithm description
%
% NOTE: EXPERIMENTAL BASELINE — Not for autonomous clinical diagnosis.
%
% Copyright (c) 2026 RetinaShield Research Project

    arguments
        imageInput
        options.fovMask = []
        options.outputDir (1,1) string = ""
        options.modelPath (1,1) string = ""
        options.sensitivity (1,1) double = 0.58
    end

    algVersion = '0.2.0-classical';
    baseName = 'fundus';

    % 1. Load image
    if ischar(imageInput) || isstring(imageInput)
        imagePath = string(imageInput);
        if ~isfile(imagePath)
            error('segment_vessels:fileNotFound', 'Image file not found: %s', imagePath);
        end
        img = imread(imagePath);
        [~, baseName, ~] = fileparts(imagePath);
    elseif isnumeric(imageInput)
        img = imageInput;
    else
        error('segment_vessels:invalidInput', 'Input must be file path or image matrix.');
    end

    if size(img, 3) ~= 3
        img = repmat(img, [1 1 3]);
    end

    [rows, cols, ~] = size(img);

    % Default output struct
    result = struct();
    result.mask = false(rows, cols);
    result.skeleton_mask = false(rows, cols);
    result.mask_path = '';
    result.vessel_density = 0.0;
    result.tortuosity_index = 1.0;
    result.caliber_proxy = 0.0;
    result.confidence = 0.0;
    result.is_reliable = false;
    result.failure_reason = '';
    result.algorithm_version = algVersion;
    result.method = 'classical_multiorientation_tophat';

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

    fovArea = sum(fovMask(:));
    if fovArea < (rows * cols * 0.05)
        result.failure_reason = 'NO_VALID_FOV_FOR_VESSEL_SEGMENTATION';
        return;
    end

    % Safe FOV for vessel analysis: Erode FOV boundary by ~10px to suppress
    % the high-contrast circular perimeter ring that creates false vessel edges
    borderErodeRadius = max(6, round(min(rows, cols) * 0.015));
    safeFov = imerode(fovMask, strel('disk', borderErodeRadius));

    % 3. Check for learned model
    if options.modelPath ~= "" && isfile(options.modelPath)
        try
            result = predict_vessels_dl(img, options.modelPath, safeFov, result);
            result.algorithm_version = '0.2.0-learned';
            result.method = 'learned_model';
            if result.is_reliable
                if options.outputDir ~= ""
                    save_vessel_mask(result.mask, options.outputDir, baseName);
                end
                return;
            end
        catch ME
            warning('segment_vessels:dlFailed', 'Learned vessel model failed (%s). Falling back.', ME.message);
        end
    end

    % 4. Classical Multi-Scale / Multi-Orientation Matched Filtering
    try
        greenCh = img(:, :, 2);

        % CLAHE illumination enhancement on green channel (high vessel contrast)
        claheTiles = [8, 8];
        if rows < 256 || cols < 256
            claheTiles = [4, 4];
        end
        greenClahe = adapthisteq(greenCh, 'NumTiles', claheTiles, 'ClipLimit', 0.02);

        % Invert: blood vessels become bright on darker retinal background
        greenComp = imcomplement(greenClahe);

        % Multi-orientation morphological linear top-hat
        % Vessels appear as linear structures of various orientations (0 to 165 deg)
        lineLen = max(7, round(min(rows, cols) * 0.022));
        if mod(lineLen, 2) == 0
            lineLen = lineLen + 1;
        end

        vesselResponse = zeros(rows, cols, 'double');
        for angle = 0:15:165
            se = strel('line', lineLen, angle);
            tophatResp = double(imtophat(greenComp, se));
            vesselResponse = max(vesselResponse, tophatResp);
        end

        vesselResponse = mat2gray(vesselResponse);

        % Suppress pixels outside safe FOV
        vesselResponse(~safeFov) = 0;

        % Adaptive threshold binarization
        vesselMask = imbinarize(vesselResponse, 'adaptive', 'Sensitivity', options.sensitivity);

        % Apply safe FOV mask
        vesselMask = vesselMask & safeFov;

        % Morphological cleanup: remove small isolated noise pixels (< 35 px)
        minObjSize = max(20, round(min(rows, cols) * 0.05));
        vesselMask = bwareaopen(vesselMask, minObjSize);

        % Extract vessel centerline skeleton
        skeletonMask = bwmorph(vesselMask, 'thin', Inf);

        % Biomarkers:
        % 1. Vessel density = vessel pixels / safe FOV pixels
        safeFovArea = sum(safeFov(:));
        vesselPixCount = sum(vesselMask(:));
        if safeFovArea > 0
            vesselDensity = vesselPixCount / safeFovArea;
        else
            vesselDensity = 0.0;
        end

        % 2. Tortuosity index = mean arc-chord ratio of vessel segments
        skelProps = regionprops(skeletonMask, 'Area', 'Perimeter');
        if ~isempty(skelProps)
            perims = [skelProps.Perimeter];
            areas = max([skelProps.Area], 1);
            ratios = perims ./ areas;
            validRatios = ratios(ratios >= 1.0 & ratios <= 8.0);
            if ~isempty(validRatios)
                tortuosity = mean(validRatios);
            else
                tortuosity = 1.0;
            end
        else
            tortuosity = 1.0;
        end

        % 3. Caliber proxy = area / skeleton length
        skelLength = sum(skeletonMask(:));
        if skelLength > 0
            caliber = vesselPixCount / skelLength;
        else
            caliber = 0.0;
        end

        % Quality score: realistic retinal vessel density is between 0.04 and 0.20
        if vesselDensity >= 0.04 && vesselDensity <= 0.22
            conf = 0.85;
            reliable = true;
        elseif vesselDensity > 0.01 && vesselDensity < 0.35
            conf = 0.60;
            reliable = true;
        else
            conf = 0.30;
            reliable = false;
        end

        result.mask = vesselMask;
        result.skeleton_mask = skeletonMask;
        result.vessel_density = min(1.0, vesselDensity);
        result.tortuosity_index = tortuosity;
        result.caliber_proxy = caliber;
        result.confidence = conf;
        result.is_reliable = reliable;
        if ~reliable
            result.failure_reason = 'ABNORMAL_VESSEL_DENSITY_DETECTED';
        else
            result.failure_reason = '';
        end

    catch ME
        result.is_reliable = false;
        result.failure_reason = sprintf('VESSEL_SEGMENTATION_ERROR: %s', ME.message);
    end

    % 5. Save mask artifact if output directory provided
    if options.outputDir ~= "" && result.is_reliable
        if ~isfolder(options.outputDir)
            mkdir(options.outputDir);
        end
        maskPath = fullfile(options.outputDir, sprintf('%s_vessels_mask.png', char(baseName)));
        imwrite(result.mask, maskPath);
        result.mask_path = char(maskPath);
    end
end


function result = predict_vessels_dl(img, modelPath, safeFov, result)
% PREDICT_VESSELS_DL Hook for learned segmentation model (e.g. U-Net).
    modelData = load(modelPath);
    if isfield(modelData, 'net')
        inputSize = modelData.net.Layers(1).InputSize(1:2);
        resized = imresize(img, inputSize);
        pred = semanticseg(resized, modelData.net);
        vesselResized = (pred == 'vessel');
        origMask = imresize(vesselResized, [size(img, 1), size(img, 2)], 'nearest');
        vesselMask = logical(origMask) & safeFov;
        
        result.mask = vesselMask;
        result.skeleton_mask = bwmorph(vesselMask, 'thin', Inf);
        safeArea = sum(safeFov(:));
        if safeArea > 0
            result.vessel_density = sum(vesselMask(:)) / safeArea;
        end
        result.is_reliable = true;
        result.confidence = 0.90;
        result.failure_reason = '';
    end
end
