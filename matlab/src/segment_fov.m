function result = segment_fov(imageInput, options)
% SEGMENT_FOV Segment retinal field-of-view (FOV) from a fundus photograph.
%
% Accurately delineates the retinal aperture from dark camera background,
% vignetting borders, and instrument artifacts. Supports circular apertures
% and rectangular/cropped fundus images.
%
% USAGE:
%   result = segment_fov('path/to/fundus.jpg')
%   result = segment_fov(imgMatrix)
%   result = segment_fov(imageInput, 'outputDir', './out', 'modelPath', './fov_unet.mat')
%
% INPUTS:
%   imageInput - (string or uint8 matrix) File path or RGB image matrix
%   options    - Name-value pairs:
%       'outputDir'  - (string) Optional directory to save FOV mask PNG
%       'modelPath'  - (string) Optional path to learned segmentation model (.mat)
%       'threshold'  - (double) Luminance threshold multiplier (default: 0.15)
%
% OUTPUT:
%   result - (struct):
%     .mask              - 2D logical array (same dimensions as input image)
%     .mask_path         - Path to saved PNG mask (empty if outputDir omitted)
%     .bounding_box      - [x, y, width, height] in 1-based pixel coords
%     .center            - [x, y] center of fitted aperture
%     .radius            - Equivalent radius of retinal field (pixels)
%     .area_pixels       - Total pixel area of the retinal field
%     .area_ratio        - Fraction of total image area covered by retina (0..1)
%     .is_reliable       - Boolean flag indicating segmentation reliability
%     .failure_reason    - Empty if reliable, or failure diagnostic string
%     .algorithm_version - Semantic version identifier
%     .method            - 'classical_otsu_morphology' or 'learned_model'
%
% NOTE: EXPERIMENTAL BASELINE — Structural segmentation for research screening.
%       Not certified for autonomous clinical diagnostic decisions.
%
% Copyright (c) 2026 RetinaShield Research Project

    arguments
        imageInput
        options.outputDir (1,1) string = ""
        options.modelPath (1,1) string = ""
        options.threshold (1,1) double = 0.15
    end

    algVersion = '0.2.0-classical';
    baseName = 'fundus';

    % 1. Load image
    if ischar(imageInput) || isstring(imageInput)
        imagePath = string(imageInput);
        if ~isfile(imagePath)
            error('segment_fov:fileNotFound', 'Image file not found: %s', imagePath);
        end
        img = imread(imagePath);
        [~, baseName, ~] = fileparts(imagePath);
    elseif isnumeric(imageInput)
        img = imageInput;
    else
        error('segment_fov:invalidInput', 'Input must be a file path string or image matrix.');
    end

    if size(img, 3) ~= 3
        % Convert grayscale to 3-channel if needed
        img = repmat(img, [1 1 3]);
    end

    [rows, cols, ~] = size(img);
    totalPixels = rows * cols;

    % Initialize default return structure
    result = struct();
    result.mask = false(rows, cols);
    result.mask_path = '';
    result.bounding_box = [1, 1, cols, rows];
    result.center = [cols / 2, rows / 2];
    result.radius = min(rows, cols) / 2;
    result.area_pixels = 0;
    result.area_ratio = 0.0;
    result.is_reliable = false;
    result.failure_reason = '';
    result.algorithm_version = algVersion;
    result.method = 'classical_otsu_morphology';

    % 2. Check for learned model if specified and available
    if options.modelPath ~= "" && isfile(options.modelPath)
        try
            result = predict_fov_dl(img, options.modelPath, result);
            result.algorithm_version = '0.2.0-learned';
            result.method = 'learned_model';
        catch ME
            warning('segment_fov:dlFallback', 'Learned model failed (%s), falling back to classical baseline.', ME.message);
        end
    end

    % 3. Classical Baseline Execution (if not populated by learned model)
    if ~result.is_reliable
        try
            % Use red channel and luminance for robust dark background separation
            redCh = double(img(:, :, 1));
            greenCh = double(img(:, :, 2));
            grayImg = 0.2989 * redCh + 0.5870 * greenCh + 0.1140 * double(img(:, :, 3));

            % Fundus tissue reflects primarily red/amber light
            % Background camera mask is near 0 in all channels
            otsuLvl = graythresh(mat2gray(grayImg));
            adaptiveThresh = max(10, otsuLvl * 255 * options.threshold);

            % Primary binary thresholding
            initialMask = (grayImg > adaptiveThresh) | (redCh > (adaptiveThresh * 1.1));

            % Check if this is a pre-cropped rectangular fundus (e.g. >95% non-zero)
            nonZeroRatio = sum(initialMask(:)) / totalPixels;
            if nonZeroRatio > 0.95
                % Rectangular fundus image with no dark circular camera mask
                fovMask = true(rows, cols);
            else
                % Circular aperture cleanup
                % Morphological closing to bridge vessel gaps and fill small holes
                diskSize = max(5, round(min(rows, cols) * 0.02));
                closedMask = imclose(initialMask, strel('disk', diskSize));
                filledMask = imfill(closedMask, 'holes');

                % Remove small noise specks outside the aperture
                minApertureArea = round(totalPixels * 0.10);
                cleanedMask = bwareaopen(filledMask, minApertureArea);

                % Retain the single largest connected component (the retinal aperture)
                cc = bwconncomp(cleanedMask);
                if cc.NumObjects > 0
                    stats = regionprops(cc, 'Area', 'PixelIdxList');
                    [~, maxIdx] = max([stats.Area]);
                    fovMask = false(rows, cols);
                    fovMask(cc.PixelIdxList{maxIdx}) = true;

                    % Smooth outer perimeter using morphological opening
                    fovMask = imopen(fovMask, strel('disk', max(3, round(diskSize / 2))));
                    fovMask = imfill(fovMask, 'holes');
                else
                    fovMask = initialMask;
                end
            end

            areaPix = sum(fovMask(:));
            areaRatio = areaPix / totalPixels;

            % Reliability validation
            if areaRatio < 0.15
                result.is_reliable = false;
                result.failure_reason = 'NO_VALID_RETINAL_FIELD_FOUND';
            elseif areaRatio > 0.98
                % Pre-cropped rectangular image, valid full-frame
                result.mask = fovMask;
                result.area_pixels = areaPix;
                result.area_ratio = areaRatio;
                result.bounding_box = [1, 1, cols, rows];
                result.center = [cols / 2, rows / 2];
                result.radius = min(rows, cols) / 2;
                result.is_reliable = true;
                result.failure_reason = '';
            else
                % Normal circular / elliptical aperture
                props = regionprops(fovMask, 'BoundingBox', 'Centroid', 'EquivDiameter');
                result.mask = fovMask;
                result.area_pixels = areaPix;
                result.area_ratio = areaRatio;
                result.bounding_box = props(1).BoundingBox;
                result.center = props(1).Centroid;
                result.radius = props(1).EquivDiameter / 2;
                result.is_reliable = true;
                result.failure_reason = '';
            end

        catch ME
            result.is_reliable = false;
            result.failure_reason = sprintf('FOV_SEGMENTATION_ERROR: %s', ME.message);
        end
    end

    % 4. Save mask artifact if output directory provided
    if options.outputDir ~= "" && result.is_reliable
        if ~isfolder(options.outputDir)
            mkdir(options.outputDir);
        end
        maskPath = fullfile(options.outputDir, sprintf('%s_fov_mask.png', char(baseName)));
        imwrite(result.mask, maskPath);
        result.mask_path = char(maskPath);
    end
end


function result = predict_fov_dl(img, modelPath, result)
% PREDICT_FOV_DL Hook for learned semantic segmentation network.
    modelData = load(modelPath);
    if isfield(modelData, 'net')
        inputSize = modelData.net.Layers(1).InputSize(1:2);
        resized = imresize(img, inputSize);
        pred = semanticseg(resized, modelData.net);
        maskResized = (pred == 'fov') | (pred == 'retina');
        origMask = imresize(maskResized, [size(img, 1), size(img, 2)], 'nearest');
        
        result.mask = logical(origMask);
        result.area_pixels = sum(result.mask(:));
        result.area_ratio = result.area_pixels / numel(result.mask);
        props = regionprops(result.mask, 'BoundingBox', 'Centroid', 'EquivDiameter');
        if ~isempty(props)
            result.bounding_box = props(1).BoundingBox;
            result.center = props(1).Centroid;
            result.radius = props(1).EquivDiameter / 2;
            result.is_reliable = true;
            result.failure_reason = '';
        end
    end
end
