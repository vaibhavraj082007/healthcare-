function result = detect_lesion_candidates(imageInput, options)
% DETECT_LESION_CANDIDATES Transparent classical baseline for lesion candidate proposals.
%
% Generates heuristic proposals for:
%   1. Microaneurysms (MA)           - small focal dark dots (vessel-excluded)
%   2. Hemorrhages (HE)              - blot/flame dark patches (vessel-excluded)
%   3. Hard Exudates (EX)            - sharp bright lipid deposits (disc-excluded)
%   4. Cotton-Wool Spots (CWS / SE)  - diffuse cloudy patches (disc-excluded)
%
% SAFEGUARD:
%   All outputs are explicitly flagged as 'is_validated = false' and
%   'candidate_type = heuristic_proposal'. These heuristic candidates must
%   NEVER masquerade as certified deep learning detections.
%
% USAGE:
%   result = detect_lesion_candidates('path/to/fundus.jpg')
%   result = detect_lesion_candidates(img, 'opticDiscMask', odMask, 'vesselMask', vascMask)
%
% INPUTS:
%   imageInput - (string or uint8 matrix) Image path or RGB matrix
%   options    - Name-value pairs:
%       'opticDiscMask'  - (logical matrix) Optic disc mask to suppress false exudates
%       'vesselMask'     - (logical matrix) Vessel tree mask to suppress vessel false MAs
%       'fovMask'        - (logical matrix) Retinal FOV mask
%       'minConfidence'  - (double) Acceptance threshold (default: 0.25)
%
% OUTPUT:
%   result - (struct):
%     .status                - 'heuristic_only'
%     .is_validated          - false
%     .candidates            - Array of candidate structs with bbox, extent, score
%     .model_estimated_count - Struct with count per lesion type
%     .algorithm_version     - Version string
%     .disclaimer            - Clinical disclaimer
%
% Copyright (c) 2026 RetinaShield Research Project

    arguments
        imageInput
        options.opticDiscMask = []
        options.vesselMask = []
        options.fovMask = []
        options.minConfidence (1,1) double = 0.25
    end

    algVersion = '0.2.0-heuristic-morphology';

    % 1. Load image
    if ischar(imageInput) || isstring(imageInput)
        imagePath = string(imageInput);
        if ~isfile(imagePath)
            error('detect_lesion_candidates:fileNotFound', 'Image file not found: %s', imagePath);
        end
        img = imread(imagePath);
    elseif isnumeric(imageInput)
        img = imageInput;
    else
        error('detect_lesion_candidates:invalidInput', 'Input must be file path or image matrix.');
    end

    if size(img, 3) ~= 3
        img = repmat(img, [1 1 3]);
    end

    [rows, cols, ~] = size(img);

    % 2. Retrieve or compute structural masks if not supplied
    if isempty(options.fovMask)
        fovResult = segment_fov(img);
        fovMask = fovResult.mask;
    else
        fovMask = logical(options.fovMask);
        if size(fovMask, 1) ~= rows || size(fovMask, 2) ~= cols
            fovMask = imresize(fovMask, [rows, cols], 'nearest');
        end
    end

    % Safe FOV margin
    safeFov = imerode(fovMask, strel('disk', max(8, round(min(rows, cols) * 0.02))));

    % Vessel mask for microaneurysm/hemorrhage vessel-exclusion
    if isempty(options.vesselMask)
        vascResult = segment_vessels(img, 'fovMask', fovMask);
        vesselMask = vascResult.mask;
    else
        vesselMask = logical(options.vesselMask);
    end
    dilatedVessels = imdilate(vesselMask, strel('disk', 3));

    % Optic disc mask for exudate disc-exclusion
    if isempty(options.opticDiscMask)
        odResult = segment_optic_disc(img, 'fovMask', fovMask, 'vesselMask', vesselMask);
        odMask = odResult.mask;
    else
        odMask = logical(options.opticDiscMask);
    end
    dilatedOd = imdilate(odMask, strel('disk', max(12, round(min(rows, cols) * 0.03))));

    % Extract color channels
    redCh = double(img(:, :, 1));
    greenCh = double(img(:, :, 2));
    blueCh = double(img(:, :, 3));

    % CLAHE on green channel (high vessel/hemorrhage contrast)
    greenClahe = double(adapthisteq(uint8(greenCh), 'NumTiles', [8 8], 'ClipLimit', 0.02));
    greenComp = 255.0 - greenClahe;

    candidates = [];
    counts = struct('microaneurysm', 0, 'hemorrhage', 0, 'hard_exudate', 0, 'soft_exudate', 0);

    % -------------------------------------------------------------------
    % 1. Microaneurysms (MA) Candidate Extraction
    %    Focal dark circular spots (< 15 px area), isolated from vessels
    % -------------------------------------------------------------------
    try
        maTophat = double(imtophat(uint8(greenComp), strel('disk', 3)));
        maTophat(~safeFov | dilatedVessels) = 0;

        maThresh = prctile(maTophat(safeFov), 97.5);
        maBw = (maTophat > maThresh) & (maTophat > 15);
        maCc = bwconncomp(maBw, 8);

        if maCc.NumObjects > 0
            maStats = regionprops(maCc, 'BoundingBox', 'Area', 'Centroid', 'EquivDiameter');
            for k = 1:numel(maStats)
                a = maStats(k).Area;
                if a >= 2 && a <= 30
                    bx = maStats(k).BoundingBox;
                    score = min(0.85, 0.30 + (a / 30.0) * 0.40);
                    if score >= options.minConfidence
                        c = struct();
                        c.lesion_type = 'microaneurysm';
                        c.bbox = [bx(1), bx(2), bx(1) + bx(3), bx(2) + bx(4)];
                        c.centroid = maStats(k).Centroid;
                        c.confidence = round(score, 3);
                        c.approximate_extent = struct(...
                            'area_pixels', a, ...
                            'equivalent_diameter', round(maStats(k).EquivDiameter, 1), ...
                            'width', bx(3), ...
                            'height', bx(4) ...
                        );
                        c.is_validated = false;
                        c.candidate_type = 'heuristic_proposal';
                        candidates = [candidates; c];
                        counts.microaneurysm = counts.microaneurysm + 1;
                    end
                end
            end
        end
    catch ME
        warning('detect_lesion_candidates:maFailed', 'MA extraction failed: %s', ME.message);
    end

    % -------------------------------------------------------------------
    % 2. Hemorrhages (HE) Candidate Extraction
    %    Medium/large dark blot patches, excluded from primary vessels
    % -------------------------------------------------------------------
    try
        heMed = medfilt2(greenComp, [5 5]);
        heTophat = double(imtophat(uint8(heMed), strel('disk', 10)));
        heTophat(~safeFov | dilatedVessels) = 0;

        heThresh = prctile(heTophat(safeFov), 96.0);
        heBw = (heTophat > heThresh) & (heTophat > 20);
        heCc = bwconncomp(heBw, 8);

        if heCc.NumObjects > 0
            heStats = regionprops(heCc, 'BoundingBox', 'Area', 'Centroid', 'EquivDiameter');
            for k = 1:numel(heStats)
                a = heStats(k).Area;
                if a >= 25 && a <= 500
                    bx = heStats(k).BoundingBox;
                    score = min(0.88, 0.40 + (a / 500.0) * 0.45);
                    if score >= options.minConfidence
                        c = struct();
                        c.lesion_type = 'hemorrhage';
                        c.bbox = [bx(1), bx(2), bx(1) + bx(3), bx(2) + bx(4)];
                        c.centroid = heStats(k).Centroid;
                        c.confidence = round(score, 3);
                        c.approximate_extent = struct(...
                            'area_pixels', a, ...
                            'equivalent_diameter', round(heStats(k).EquivDiameter, 1), ...
                            'width', bx(3), ...
                            'height', bx(4) ...
                        );
                        c.is_validated = false;
                        c.candidate_type = 'heuristic_proposal';
                        candidates = [candidates; c];
                        counts.hemorrhage = counts.hemorrhage + 1;
                    end
                end
            end
        end
    catch ME
        warning('detect_lesion_candidates:heFailed', 'HE extraction failed: %s', ME.message);
    end

    % -------------------------------------------------------------------
    % 3. Hard Exudates (EX) Candidate Extraction
    %    Sharp bright yellowish deposits, excluded from optic disc rim
    % -------------------------------------------------------------------
    try
        % Bright in red and green, lower in blue
        exIntensity = (0.5 * redCh + 0.5 * greenCh) - (0.4 * blueCh);
        exTophat = double(imtophat(uint8(max(0, exIntensity)), strel('disk', 8)));
        exTophat(~safeFov | dilatedOd) = 0;

        exThresh = prctile(exTophat(safeFov), 97.0);
        exBw = (exTophat > exThresh) & (exTophat > 22);
        exCc = bwconncomp(exBw, 8);

        if exCc.NumObjects > 0
            exStats = regionprops(exCc, 'BoundingBox', 'Area', 'Centroid', 'EquivDiameter');
            for k = 1:numel(exStats)
                a = exStats(k).Area;
                if a >= 5 && a <= 350
                    bx = exStats(k).BoundingBox;
                    score = min(0.90, 0.45 + (a / 350.0) * 0.40);
                    if score >= options.minConfidence
                        c = struct();
                        c.lesion_type = 'hard_exudate';
                        c.bbox = [bx(1), bx(2), bx(1) + bx(3), bx(2) + bx(4)];
                        c.centroid = exStats(k).Centroid;
                        c.confidence = round(score, 3);
                        c.approximate_extent = struct(...
                            'area_pixels', a, ...
                            'equivalent_diameter', round(exStats(k).EquivDiameter, 1), ...
                            'width', bx(3), ...
                            'height', bx(4) ...
                        );
                        c.is_validated = false;
                        c.candidate_type = 'heuristic_proposal';
                        candidates = [candidates; c];
                        counts.hard_exudate = counts.hard_exudate + 1;
                    end
                end
            end
        end
    catch ME
        warning('detect_lesion_candidates:exFailed', 'EX extraction failed: %s', ME.message);
    end

    % -------------------------------------------------------------------
    % 4. Cotton-Wool Spots / Soft Exudates (CWS / SE)
    %    Diffuse, cloudy bright patches with unsharp borders, excluded from OD
    % -------------------------------------------------------------------
    try
        seBlur = imgaussfilt(greenCh, 5);
        seTophat = double(imtophat(uint8(seBlur), strel('disk', 18)));
        seTophat(~safeFov | dilatedOd) = 0;

        seThresh = prctile(seTophat(safeFov), 98.0);
        seBw = (seTophat > seThresh) & (seTophat > 25);
        seCc = bwconncomp(seBw, 8);

        if seCc.NumObjects > 0
            seStats = regionprops(seCc, 'BoundingBox', 'Area', 'Centroid', 'EquivDiameter');
            for k = 1:numel(seStats)
                a = seStats(k).Area;
                if a >= 35 && a <= 800
                    bx = seStats(k).BoundingBox;
                    score = min(0.85, 0.40 + (a / 800.0) * 0.40);
                    if score >= options.minConfidence
                        c = struct();
                        c.lesion_type = 'soft_exudate';
                        c.bbox = [bx(1), bx(2), bx(1) + bx(3), bx(2) + bx(4)];
                        c.centroid = seStats(k).Centroid;
                        c.confidence = round(score, 3);
                        c.approximate_extent = struct(...
                            'area_pixels', a, ...
                            'equivalent_diameter', round(seStats(k).EquivDiameter, 1), ...
                            'width', bx(3), ...
                            'height', bx(4) ...
                        );
                        c.is_validated = false;
                        c.candidate_type = 'heuristic_proposal';
                        candidates = [candidates; c];
                        counts.soft_exudate = counts.soft_exudate + 1;
                    end
                end
            end
        end
    catch ME
        warning('detect_lesion_candidates:cwsFailed', 'CWS extraction failed: %s', ME.message);
    end

    % Build output struct
    result = struct();
    result.status = 'heuristic_only';
    result.is_validated = false;
    result.candidates = candidates;
    result.model_estimated_count = counts;
    result.algorithm_version = algVersion;
    result.disclaimer = 'HEURISTIC CANDIDATE — Unvalidated candidate proposals for research screening. Not certified clinical lesion detections.';

    fprintf('[RetinaShield Candidates] Total proposals: %d (MA: %d, HE: %d, EX: %d, CWS: %d) [UNVALIDATED]\n', ...
        numel(candidates), counts.microaneurysm, counts.hemorrhage, counts.hard_exudate, counts.soft_exudate);
end
