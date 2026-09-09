function result = segment_structures(imagePath, outputDir)
% SEGMENT_STRUCTURES Segment key retinal structures from a fundus image.
%
% Detects and segments:
%   1. Optic Disc — bright circular region where the optic nerve enters
%   2. Macula — dark region near image center, critical for vision
%   3. Vasculature — retinal blood vessel tree
%
% USAGE:
%   result = segment_structures('path/to/fundus.jpg', 'path/to/output/')
%
% INPUTS:
%   imagePath - (string) Full path to the input fundus image
%   outputDir - (string) Directory to save segmentation outputs
%
% OUTPUT:
%   result - (struct) Segmentation results:
%     .optic_disc   - struct with detected, center_x, center_y, radius, confidence
%     .macula       - struct with detected, center_x, center_y, confidence
%     .vasculature  - struct with segmentation_mask_path, vessel_density, tortuosity_index
%
% REQUIRES:
%   - Image Processing Toolbox
%   - Computer Vision Toolbox
%
% NOTE: RESEARCH SCREENING tool — not for autonomous diagnosis.
%
% Copyright (c) 2026 RetinaShield Research Project

    arguments
        imagePath (1,1) string {mustBeFile}
        outputDir (1,1) string
    end

    if ~isfolder(outputDir)
        mkdir(outputDir);
    end

    img = imread(imagePath);
    [rows, cols, ~] = size(img);
    [~, baseName, ~] = fileparts(imagePath);
    
    grayImg = im2gray(img);
    greenCh = img(:, :, 2);
    
    % -----------------------------------------------------------------------
    % 1. Optic Disc Detection
    %    The optic disc is the brightest roughly circular region.
    %    Method: Intensity thresholding + morphological filtering + Hough circle
    % -----------------------------------------------------------------------
    opticDisc = struct('detected', false, 'center_x', 0, 'center_y', 0, ...
                       'radius', 0, 'confidence', 0);
    
    try
        % Use the red channel (OD appears brightest in red)
        redCh = img(:, :, 1);
        
        % Apply median filter to reduce noise
        redFiltered = medfilt2(redCh, [5 5]);
        
        % Threshold for bright regions (top 5% intensity)
        brightThresh = prctile(redFiltered(:), 95);
        brightMask = redFiltered > brightThresh;
        
        % Morphological cleanup
        brightMask = imclose(brightMask, strel('disk', 15));
        brightMask = imfill(brightMask, 'holes');
        brightMask = bwareaopen(brightMask, 500);
        
        % Find the largest connected component as OD candidate
        cc = bwconncomp(brightMask);
        if cc.NumObjects > 0
            stats = regionprops(cc, 'Centroid', 'EquivDiameter', 'Area');
            [~, maxIdx] = max([stats.Area]);
            
            opticDisc.detected = true;
            opticDisc.center_x = stats(maxIdx).Centroid(1);
            opticDisc.center_y = stats(maxIdx).Centroid(2);
            opticDisc.radius = stats(maxIdx).EquivDiameter / 2;
            
            % Confidence based on circularity
            regionMask = false(size(brightMask));
            regionMask(cc.PixelIdxList{maxIdx}) = true;
            perim = regionprops(regionMask, 'Perimeter');
            circularity = 4 * pi * stats(maxIdx).Area / (perim.Perimeter^2);
            opticDisc.confidence = min(1.0, circularity);
        end
    catch ME
        warning('segment_structures:odFailed', 'OD detection failed: %s', ME.message);
    end
    
    % -----------------------------------------------------------------------
    % 2. Macula Detection
    %    The macula is the darkest region roughly 2.5 OD diameters temporal
    %    to the optic disc center.
    % -----------------------------------------------------------------------
    macula = struct('detected', false, 'center_x', 0, 'center_y', 0, ...
                    'confidence', 0);
    
    try
        % Apply Gaussian blur to smooth
        greenSmooth = imgaussfilt(greenCh, 10);
        
        % Search in the central region of the image
        marginH = round(rows * 0.2);
        marginW = round(cols * 0.2);
        searchRegion = greenSmooth(marginH:rows-marginH, marginW:cols-marginW);
        
        % Find the darkest region (macula is dark in green channel)
        [~, minIdx] = min(searchRegion(:));
        [minR, minC] = ind2sub(size(searchRegion), minIdx);
        
        macula.detected = true;
        macula.center_x = minC + marginW - 1;
        macula.center_y = minR + marginH - 1;
        
        % Confidence: lower if too close to OD (likely misdetection)
        if opticDisc.detected
            dist = sqrt((macula.center_x - opticDisc.center_x)^2 + ...
                        (macula.center_y - opticDisc.center_y)^2);
            expectedDist = opticDisc.radius * 5;  % ~2.5 OD diameters
            macula.confidence = min(1.0, max(0.1, 1 - abs(dist - expectedDist) / expectedDist));
        else
            macula.confidence = 0.5;  % Moderate confidence without OD reference
        end
    catch ME
        warning('segment_structures:maculaFailed', 'Macula detection failed: %s', ME.message);
    end
    
    % -----------------------------------------------------------------------
    % 3. Vessel Segmentation
    %    Multi-scale matched filtering + adaptive thresholding
    % -----------------------------------------------------------------------
    vasculature = struct('segmentation_mask_path', '', 'vessel_density', 0, ...
                         'tortuosity_index', 0);
    
    try
        % CLAHE on green channel for better vessel contrast
        greenClahe = adapthisteq(greenCh, 'NumTiles', [8 8], 'ClipLimit', 0.02);
        
        % Complement (vessels become bright)
        greenComp = imcomplement(greenClahe);
        
        % Multi-orientation matched filtering
        vesselResponse = zeros(size(greenComp), 'double');
        for angle = 0:15:165
            se = strel('line', 11, angle);
            vesselResponse = max(vesselResponse, double(imtophat(greenComp, se)));
        end
        vesselResponse = mat2gray(vesselResponse);
        
        % Adaptive threshold for vessel segmentation
        vesselMask = imbinarize(vesselResponse, 'adaptive', 'Sensitivity', 0.6);
        
        % Clean up: remove small objects, thin the mask
        vesselMask = bwareaopen(vesselMask, 50);
        vesselThin = bwmorph(vesselMask, 'thin', Inf);
        
        % Create a fundus mask (non-black region)
        fundusMask = imbinarize(grayImg, 'adaptive', 'Sensitivity', 0.3);
        fundusMask = imopen(fundusMask, strel('disk', 20));
        fundusMask = imfill(fundusMask, 'holes');
        
        % Vessel density = vessel pixels / fundus pixels
        fundusArea = sum(fundusMask(:));
        if fundusArea > 0
            vasculature.vessel_density = sum(vesselMask(:) & fundusMask(:)) / fundusArea;
        end
        
        % Tortuosity: simplified as mean arc-chord ratio of vessel segments
        % (Full implementation would trace individual vessels)
        skelProps = regionprops(vesselThin, 'Area', 'Perimeter');
        if ~isempty(skelProps)
            arcChords = [skelProps.Perimeter] ./ max([skelProps.Area], 1);
            vasculature.tortuosity_index = mean(arcChords(arcChords > 1 & arcChords < 10));
            if isnan(vasculature.tortuosity_index)
                vasculature.tortuosity_index = 1.0;
            end
        end
        
        % Save vessel segmentation mask
        maskPath = fullfile(outputDir, [char(baseName) '_vessels_mask.png']);
        imwrite(vesselMask, maskPath);
        vasculature.segmentation_mask_path = char(maskPath);
        
    catch ME
        warning('segment_structures:vesselFailed', 'Vessel segmentation failed: %s', ME.message);
    end
    
    % -----------------------------------------------------------------------
    % Build result struct
    % -----------------------------------------------------------------------
    result = struct();
    result.optic_disc = opticDisc;
    result.macula = macula;
    result.vasculature = vasculature;
    
    fprintf('[RetinaShield Segment] OD: %s (conf=%.2f) | Macula: %s (conf=%.2f) | VesselDensity: %.3f\n', ...
            mat2str(opticDisc.detected), opticDisc.confidence, ...
            mat2str(macula.detected), macula.confidence, ...
            vasculature.vessel_density);
end
