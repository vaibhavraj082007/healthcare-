function result = enhance_fundus(imagePath, outputDir, initialIqaResult)
% ENHANCE_FUNDUS Preprocess retinal fundus image for DR screening analysis.
%
% Applies multiple enhancement techniques prioritizing clinical fidelity:
%   1. Retinal-region masking
%   2. Illumination normalization
%   3. Conservative denoising
%   4. Conditional CLAHE (only if uneven illumination detected)
%   5. Aspect-ratio-preserving resize with zero-padding
%   6. High-resolution tile extraction (macula-focused)
%
% The original image remains immutable. All parameters and geometric
% transformations mapping back to the original image are tracked.
%
% USAGE:
%   result = enhance_fundus('path/to/img.jpg', 'path/to/out/', iqaResult)
%
% INPUTS:
%   imagePath        - (string) Full path to the input fundus image
%   outputDir        - (string) Directory to save enhanced images
%   initialIqaResult - (struct) Output from quality_assessment.m
%
% OUTPUT:
%   result - (struct) Enhancement results with geometry tracking and
%            post-enhancement IQA checking.
%
% Copyright (c) 2026 RetinaShield Research Project

    arguments
        imagePath (1,1) string {mustBeFile}
        outputDir (1,1) string
        initialIqaResult (1,1) struct
    end

    if ~isfolder(outputDir)
        mkdir(outputDir);
    end
    
    [~, baseName, ~] = fileparts(imagePath);
    
    % 1. Load Configuration
    [fileDir, ~, ~] = fileparts(mfilename('fullpath'));
    configPath = fullfile(fileDir, 'preprocessing_config_v1.0.json');
    if exist(configPath, 'file')
        fid = fopen(configPath, 'r');
        rawJson = fread(fid, '*char')';
        fclose(fid);
        config = jsondecode(rawJson);
    else
        error('enhance_fundus:missingConfig', 'Could not find preprocessing_config_v1.0.json');
    end

    % Read original image (IMMUTABLE)
    origImg = imread(imagePath);
    [origH, origW, ~] = size(origImg);
    
    % Tracking struct
    geometry = struct('original_size', [origH, origW], ...
                      'pad_top', 0, 'pad_bottom', 0, ...
                      'pad_left', 0, 'pad_right', 0, ...
                      'scale_factor', 1.0, ...
                      'transform_to_original', eye(3));
                      
    params = struct('config_version', config.version, ...
                    'clahe_applied', false, ...
                    'denoising_applied', true, ...
                    'illumination_normalized', true);

    % Working copy
    img = origImg;
    grayImg = im2gray(img);
    
    % 2. Retinal-Region Masking
    % Find circular fundus mask
    bwMask = grayImg > 15;
    bwMask = imopen(bwMask, strel('disk', 10));
    bwMask = imfill(bwMask, 'holes');
    
    % Find bounding box of the retina to crop unnecessary black space first
    [rows, cols] = find(bwMask);
    if isempty(rows)
        cropBox = [1, 1, origW, origH];
    else
        minR = min(rows); maxR = max(rows);
        minC = min(cols); maxC = max(cols);
        cropBox = [minC, minR, maxC - minC + 1, maxR - minR + 1];
    end
    
    % We won't crop yet to preserve full geometry easily, but we apply mask
    imgMasked = img;
    for c = 1:3
        channel = imgMasked(:,:,c);
        channel(~bwMask) = 0;
        imgMasked(:,:,c) = channel;
    end
    img = imgMasked;

    % 3. Illumination Normalization
    % Subtract heavy Gaussian blur of background to equalize illumination
    blurSigma = config.illumination_normalization.sigma;
    h = fspecial('gaussian', max(1, round(blurSigma*6)), blurSigma);
    bg = imfilter(im2double(img), h, 'replicate');
    
    % To avoid color shift, work in Lab space
    labImg = rgb2lab(img);
    bgLab = rgb2lab(bg);
    
    % Normalize L channel
    L = labImg(:,:,1);
    L_bg = bgLab(:,:,1);
    L_norm = L - L_bg + mean(L(bwMask));
    L_norm = max(0, min(100, L_norm)); % clip
    
    labImg(:,:,1) = L_norm;
    img = im2uint8(lab2rgb(labImg));
    
    % Apply mask again
    for c = 1:3
        channel = img(:,:,c);
        channel(~bwMask) = 0;
        img(:,:,c) = channel;
    end

    % 4. Conservative Denoising
    if strcmp(config.denoising.method, 'median')
        for c = 1:3
            img(:,:,c) = medfilt2(img(:,:,c), config.denoising.kernel_size);
        end
    end

    % 5. Conditional CLAHE
    % Trigger if IQA shows uneven illumination, avoiding noise amplification if perfect
    needsClahe = false;
    if isfield(initialIqaResult, 'measurements') && isfield(initialIqaResult.measurements, 'illumination_cv')
        cv = initialIqaResult.measurements.illumination_cv;
        if ~isnan(cv) && cv > config.clahe.conditional_trigger.threshold
            needsClahe = true;
        end
    end
    
    if needsClahe
        params.clahe_applied = true;
        labImg = rgb2lab(img);
        L = labImg(:, :, 1) / 100;
        L_clahe = adapthisteq(L, ...
            'NumTiles', config.clahe.num_tiles, ...
            'ClipLimit', config.clahe.clip_limit, ...
            'Distribution', config.clahe.distribution);
        labImg(:, :, 1) = L_clahe * 100;
        img = im2uint8(lab2rgb(labImg));
        
        for c = 1:3
            channel = img(:,:,c);
            channel(~bwMask) = 0;
            img(:,:,c) = channel;
        end
    end

    % 6. High-Resolution Tile Extraction
    % Extract overlapping tiles from the center (macula/fovea region roughly)
    tilesPaths = {};
    if config.tiling.extract_tiles
        tileSize = config.tiling.tile_size;
        overlap = config.tiling.overlap_ratio;
        step = round(tileSize(1) * (1 - overlap));
        
        tileDir = fullfile(outputDir, 'tiles');
        if ~isfolder(tileDir), mkdir(tileDir); end
        
        % Generate a grid of tiles covering the bounding box
        tileIdx = 1;
        for r = cropBox(2):step:(cropBox(2)+cropBox(4)-tileSize(2))
            for c = cropBox(1):step:(cropBox(1)+cropBox(3)-tileSize(1))
                tile = origImg(r:r+tileSize(2)-1, c:c+tileSize(1)-1, :);
                tPath = fullfile(tileDir, sprintf('%s_tile_%03d.png', baseName, tileIdx));
                imwrite(tile, tPath);
                tilesPaths{end+1} = char(tPath);
                tileIdx = tileIdx + 1;
            end
        end
    end

    % 7. Aspect-Ratio-Preserving Resize
    targetH = config.resize.target_size(1);
    targetW = config.resize.target_size(2);
    
    scale = min(targetH / origH, targetW / origW);
    geometry.scale_factor = scale;
    
    newH = round(origH * scale);
    newW = round(origW * scale);
    
    imgResized = imresize(img, [newH, newW], 'bicubic');
    
    % Zero-pad to target size
    padTop = floor((targetH - newH) / 2);
    padBottom = targetH - newH - padTop;
    padLeft = floor((targetW - newW) / 2);
    padRight = targetW - newW - padLeft;
    
    geometry.pad_top = padTop;
    geometry.pad_bottom = padBottom;
    geometry.pad_left = padLeft;
    geometry.pad_right = padRight;
    
    imgFinal = padarray(imgResized, [padTop, padLeft], 0, 'pre');
    imgFinal = padarray(imgFinal, [padBottom, padRight], 0, 'post');
    
    % Compute inverse affine transformation matrix (target -> original)
    % Point in target (xt, yt).
    % xt = x_res + padLeft = x_orig * scale + padLeft
    % x_orig = (xt - padLeft) / scale
    T_pad = [1 0 -padLeft; 0 1 -padTop; 0 0 1];
    T_scale = [1/scale 0 0; 0 1/scale 0; 0 0 1];
    geometry.transform_to_original = T_scale * T_pad;
    
    % Save enhanced full image
    enhancedPath = fullfile(outputDir, [char(baseName) '_enhanced.png']);
    imwrite(imgFinal, enhancedPath);

    % 8. Post-enhancement IQA
    postIqa = quality_assessment(enhancedPath);
    
    % Merge rejection reasons (enhancement cannot restore clipping or blur)
    finalIqa = initialIqaResult;
    finalIqa.status = postIqa.status;
    
    % Retain original reasons that aren't fixable by enhancement
    unfixable = {'ERR_OUT_OF_FOCUS', 'ERR_LOW_RESOLUTION', 'WARN_CLIPPED_EDGES', 'ERR_NON_FUNDUS_OR_TINY'};
    for i = 1:length(unfixable)
        code = unfixable{i};
        if any(strcmp(initialIqaResult.reason_codes, code))
            if ~any(strcmp(postIqa.reason_codes, code))
                finalIqa.reason_codes{end+1} = code;
            end
            % Force ungradeable/borderline if it was originally
            if strncmp(code, 'ERR', 3)
                finalIqa.status = 'ungradeable';
            elseif strcmp(finalIqa.status, 'acceptable')
                finalIqa.status = 'borderline';
            end
        end
    end
    % Add any new post-enhancement reasons
    finalIqa.reason_codes = unique([finalIqa.reason_codes, postIqa.reason_codes]);

    % Build result struct
    result = struct();
    result.method = 'masked_norm_denoise_conditionalClahe';
    result.enhanced_image_path = char(enhancedPath);
    result.high_res_tiles = tilesPaths;
    result.geometry = geometry;
    result.parameters = params;
    result.post_enhancement_iqa = finalIqa;
    
    fprintf('[RetinaShield Enhance] Saved enhanced image to: %s\n', enhancedPath);
end
