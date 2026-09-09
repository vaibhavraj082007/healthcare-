function result = quality_assessment(imagePath)
% QUALITY_ASSESSMENT Assess fundus image quality for DR screening suitability.
%
% This function evaluates a retinal fundus image using configurable heuristic
% quality metrics to determine if it is suitable for automated DR screening.
%
% USAGE:
%   result = quality_assessment('path/to/fundus_image.jpg')
%
% INPUT:
%   imagePath - (string) Full path to the fundus image file.
%
% OUTPUT:
%   result - (struct) Quality assessment results:
%     .status             - 'acceptable' | 'borderline' | 'ungradeable'
%     .reason_codes       - Cell array of strings (e.g., 'ERR_UNDEREXPOSED')
%     .recapture_guidance - Cell array of actionable strings for the health worker
%     .measurements       - Struct of raw numerical values
%     .is_heuristic       - Boolean true (since not clinically validated)
%     .validation_required - Boolean true
%
% REQUIRES:
%   - Image Processing Toolbox
%
% Copyright (c) 2026 RetinaShield Research Project

    arguments
        imagePath (1,1) string {mustBeFile}
    end

    % 1. Load Heuristic Configuration
    [fileDir, ~, ~] = fileparts(mfilename('fullpath'));
    configPath = fullfile(fileDir, 'iqa_config_v1.0.json');
    if exist(configPath, 'file')
        fid = fopen(configPath, 'r');
        rawJson = fread(fid, '*char')';
        fclose(fid);
        config = jsondecode(rawJson);
    else
        error('quality_assessment:missingConfig', 'Could not find iqa_config_v1.0.json');
    end
    
    % Initialize output variables
    reasons = {};
    guidance = {};
    meas = struct();
    status = 'acceptable'; % Start optimistic, downgrade on failure
    
    % Helper to downgrade status
    function downgrade_to(newStatus)
        if strcmp(newStatus, 'ungradeable')
            status = 'ungradeable';
        elseif strcmp(newStatus, 'borderline') && strcmp(status, 'acceptable')
            status = 'borderline';
        end
    end

    % 2. Read Image
    try
        img = imread(imagePath);
    catch
        status = 'ungradeable';
        reasons{end+1} = 'ERR_INVALID_FILE';
        guidance{end+1} = 'The image file could not be read. Please recapture.';
        result = build_output(status, reasons, guidance, meas);
        return;
    end
    
    if size(img, 3) ~= 3
        status = 'ungradeable';
        reasons{end+1} = 'ERR_NOT_RGB';
        guidance{end+1} = 'Camera output is not in color. Check camera settings.';
        result = build_output(status, reasons, guidance, meas);
        return;
    end
    
    [rows, cols, ~] = size(img);
    meas.width = cols;
    meas.height = rows;
    
    % Resolution Check
    if cols < config.resolution.min_width || rows < config.resolution.min_height
        downgrade_to('ungradeable');
        reasons{end+1} = 'ERR_LOW_RESOLUTION';
        guidance{end+1} = 'Image is too small. Use a higher resolution setting on the camera.';
    end
    
    % 3. Extract Fundus Region (Plausibility & Clipping)
    grayImg = im2gray(img);
    % Simple threshold to find non-background
    bwMask = grayImg > 15;
    % Clean up noise
    bwMask = imopen(bwMask, strel('disk', 10));
    
    fundusRatio = sum(bwMask, 'all') / numel(bwMask);
    meas.fundus_ratio = fundusRatio;
    
    if fundusRatio < config.plausibility.min_fundus_ratio
        downgrade_to('ungradeable');
        reasons{end+1} = 'ERR_NON_FUNDUS_OR_TINY';
        guidance{end+1} = 'Retinal area is too small or this is not a fundus image. Recapture with proper alignment.';
    elseif fundusRatio > config.plausibility.max_fundus_ratio
        % Might be a cropped image or non-fundus
        downgrade_to('borderline');
        reasons{end+1} = 'WARN_NO_BACKGROUND';
        guidance{end+1} = 'No dark background detected. Ensure the full retinal field is visible.';
    end
    
    % Clipping: check if the fundus touches the image borders heavily
    edgePad = round(min(rows, cols) * config.clipping.edge_padding_ratio);
    topEdge = sum(bwMask(1:edgePad, :), 'all');
    botEdge = sum(bwMask(end-edgePad+1:end, :), 'all');
    leftEdge = sum(bwMask(:, 1:edgePad), 'all');
    rightEdge = sum(bwMask(:, end-edgePad+1:end), 'all');
    
    if topEdge > 0 || botEdge > 0 || leftEdge > 0 || rightEdge > 0
        meas.clipped = true;
        downgrade_to('borderline');
        reasons{end+1} = 'WARN_CLIPPED_EDGES';
        guidance{end+1} = 'Retina is cut off at the edges. Adjust camera distance or patient position.';
    else
        meas.clipped = false;
    end

    % 4. Exposure Check (Too dark / Too bright)
    % Only consider pixels within the fundus mask
    fundusPixels = grayImg(bwMask);
    if isempty(fundusPixels)
        meanIntensity = 0;
    else
        meanIntensity = mean(fundusPixels);
    end
    meas.mean_intensity = meanIntensity;
    
    if meanIntensity < config.exposure.underexposure_mean_intensity_limit
        downgrade_to('ungradeable');
        reasons{end+1} = 'ERR_UNDEREXPOSED';
        guidance{end+1} = 'Image is too dark. Increase flash intensity or reduce room lighting.';
    elseif meanIntensity > config.exposure.overexposure_mean_intensity_limit
        downgrade_to('ungradeable');
        reasons{end+1} = 'ERR_OVEREXPOSED';
        guidance{end+1} = 'Image is too bright. Decrease flash intensity.';
    end

    % 5. Glare / Saturation
    if ~isempty(fundusPixels)
        satRatio = sum(fundusPixels > 250) / numel(fundusPixels);
    else
        satRatio = 0;
    end
    meas.saturation_ratio = satRatio;
    
    if satRatio > config.glare.max_saturated_pixels_ratio
        downgrade_to('ungradeable');
        reasons{end+1} = 'ERR_SEVERE_GLARE';
        guidance{end+1} = 'Severe glare detected. Clean the lens and ensure proper pupil dilation.';
    end

    % 6. Focus (Laplacian Variance on the fundus area)
    laplacian = fspecial('laplacian', 0.2);
    lapFiltered = imfilter(double(grayImg), laplacian, 'symmetric');
    
    if ~isempty(fundusPixels)
        % Variance of laplacian inside the fundus mask
        lapFundus = lapFiltered(bwMask);
        lapVar = var(lapFundus);
    else
        lapVar = 0;
    end
    meas.laplacian_variance = lapVar;
    
    if lapVar < config.focus.min_laplacian_variance_borderline
        downgrade_to('ungradeable');
        reasons{end+1} = 'ERR_OUT_OF_FOCUS';
        guidance{end+1} = 'Image is extremely blurry. Refocus the camera and ask patient to keep still.';
    elseif lapVar < config.focus.min_laplacian_variance_acceptable
        downgrade_to('borderline');
        reasons{end+1} = 'WARN_SOFT_FOCUS';
        guidance{end+1} = 'Focus is soft. Consider recapturing for better detail.';
    end
    
    % 7. Illumination Uniformity
    % Divide into grid, measure CoV
    gridSize = 4;
    blockH = floor(rows / gridSize);
    blockW = floor(cols / gridSize);
    blockMeans = [];
    
    for r = 1:gridSize
        for c = 1:gridSize
            rowStart = (r-1)*blockH + 1;
            colStart = (c-1)*blockW + 1;
            maskBlock = bwMask(rowStart:rowStart+blockH-1, colStart:colStart+blockW-1);
            if sum(maskBlock, 'all') > (blockH * blockW * 0.5) % Only consider blocks mostly inside fundus
                block = grayImg(rowStart:rowStart+blockH-1, colStart:colStart+blockW-1);
                blockMeans(end+1) = mean(block(:));
            end
        end
    end
    
    if numel(blockMeans) > 2
        cv = std(blockMeans) / mean(blockMeans);
        meas.illumination_cv = cv;
        
        if cv > config.illumination.max_cv_borderline
            downgrade_to('ungradeable');
            reasons{end+1} = 'ERR_UNEVEN_ILLUMINATION';
            guidance{end+1} = 'Extreme shadows or bright spots. Check optical alignment.';
        elseif cv > config.illumination.max_cv_acceptable
            downgrade_to('borderline');
            reasons{end+1} = 'WARN_UNEVEN_ILLUMINATION';
            guidance{end+1} = 'Lighting is uneven. May obscure some lesions.';
        end
    else
        meas.illumination_cv = NaN;
    end

    % Final Result
    result = build_output(status, reasons, guidance, meas);

end

function out = build_output(status, reasons, guidance, meas)
    out = struct();
    out.status = status;
    out.reason_codes = reasons;
    out.recapture_guidance = guidance;
    out.measurements = meas;
    out.is_heuristic = true;
    out.validation_required = true;
end
