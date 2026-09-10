function manifest = import_structure_dataset(datasetName, datasetRoot, options)
% IMPORT_STRUCTURE_DATASET Standardized adapter for retinal structure datasets.
%
% Imports and standardizes annotations from open/licensed retinal structure
% benchmarks (DRIVE, REFUGE, IDRiD, STARE).
%
% CRITICAL: Does NOT assume that diagnosis CSVs contain segmentation labels.
% Maps structure annotations (FOV, optic disc, fovea coordinates, vessel masks)
% from dataset-specific formats into a unified RetinaShield structure schema.
%
% USAGE:
%   manifest = import_structure_dataset('DRIVE', '/path/to/DRIVE')
%   manifest = import_structure_dataset('REFUGE', '/path/to/REFUGE', 'split', 'train')
%   manifest = import_structure_dataset('IDRiD', '/path/to/IDRiD')
%
% INPUTS:
%   datasetName - (string) 'DRIVE' | 'REFUGE' | 'IDRiD' | 'STARE'
%   datasetRoot - (string) Root directory of the downloaded benchmark dataset
%   options     - Name-value pairs:
%       'split'      - (string) 'all' | 'train' | 'test' (default: 'all')
%       'outputJson' - (string) Optional file path to export manifest JSON
%
% OUTPUT:
%   manifest - (struct array) Standardized records:
%     .dataset_name       - Dataset identifier
%     .image_id           - Image identifier
%     .image_path         - Path to original fundus image
%     .image_dimensions   - [height, width, channels]
%     .fov_mask_path      - Path to FOV mask (or empty string)
%     .optic_disc_mask_path - Path to OD mask (or empty string)
%     .optic_disc_center  - [x, y] or [NaN, NaN]
%     .optic_disc_radius  - Radius in px or NaN
%     .fovea_center       - [x, y] or [NaN, NaN]
%     .vessel_mask_path   - Path to vessel ground truth mask (or empty string)
%     .observer_id        - Observer ID (e.g. '1st_manual', 'expert1')
%     .split              - 'train' | 'test' | 'val'
%     .license            - License attribution
%
% Copyright (c) 2026 RetinaShield Research Project

    arguments
        datasetName (1,1) string
        datasetRoot (1,1) string {mustBeFolder}
        options.split (1,1) string = "all"
        options.outputJson (1,1) string = ""
    end

    dsUpper = upper(datasetName);

    switch dsUpper
        case "DRIVE"
            manifest = import_drive(datasetRoot, options.split);
        case "REFUGE"
            manifest = import_refuge(datasetRoot, options.split);
        case "IDRID"
            manifest = import_idrid(datasetRoot, options.split);
        case "STARE"
            manifest = import_stare(datasetRoot, options.split);
        otherwise
            error('import_structure_dataset:unknownDataset', ...
                'Unsupported dataset "%s". Supported: DRIVE, REFUGE, IDRiD, STARE.', datasetName);
    end

    fprintf('[RetinaShield Adapter] Imported %d records from %s dataset.\n', ...
        numel(manifest), datasetName);

    % Optional JSON export
    if options.outputJson ~= ""
        jsonText = jsonencode(manifest, 'PrettyPrint', true);
        fid = fopen(options.outputJson, 'w');
        if fid == -1
            warning('import_structure_dataset:ioError', 'Could not open %s for writing.', options.outputJson);
        else
            fprintf(fid, '%s', jsonText);
            fclose(fid);
            fprintf('  -> Exported manifest to: %s\n', options.outputJson);
        end
    end
end


% =========================================================================
% 1. DRIVE Adapter
% =========================================================================
function records = import_drive(rootPath, splitFilter)
    license = 'DRIVE Research License — Open access for non-commercial research (Niemeijer et al., IEEE TMI 2004)';
    records = [];
    splits = {'training', 'test'};

    for s = 1:numel(splits)
        splitName = splits{s};
        if splitFilter ~= "all" && splitFilter ~= "train" && splitName == "training"
            continue;
        end
        if splitFilter ~= "all" && splitFilter ~= "test" && splitName == "test"
            continue;
        end

        imgDir = fullfile(rootPath, splitName, 'images');
        manual1Dir = fullfile(rootPath, splitName, '1st_manual');
        maskDir = fullfile(rootPath, splitName, 'mask');

        if ~isfolder(imgDir)
            continue;
        end

        imgFiles = dir(fullfile(imgDir, '*.*'));
        imgFiles = imgFiles(~[imgFiles.isdir]);

        for k = 1:numel(imgFiles)
            baseFile = imgFiles(k).name;
            [~, stem, ext] = fileparts(baseFile);
            if ~ismember(lower(ext), {'.tif', '.png', '.jpg', '.jpeg'})
                continue;
            end

            % ID in DRIVE is usually '21_training' or '01_test'
            idParts = split(stem, '_');
            imgId = idParts{1};

            % Locate 1st manual vessel annotation
            vesselPath = '';
            vesselPattern = fullfile(manual1Dir, sprintf('%s_*manual1*.*', imgId));
            vHits = dir(vesselPattern);
            if ~isempty(vHits)
                vesselPath = fullfile(vHits(1).folder, vHits(1).name);
            end

            % Locate FOV mask
            fovPath = '';
            maskPattern = fullfile(maskDir, sprintf('%s_*mask*.*', imgId));
            mHits = dir(maskPattern);
            if ~isempty(mHits)
                fovPath = fullfile(mHits(1).folder, mHits(1).name);
            end

            rec = struct();
            rec.dataset_name = 'DRIVE';
            rec.image_id = char(stem);
            rec.image_path = fullfile(imgFiles(k).folder, imgFiles(k).name);
            rec.fov_mask_path = char(fovPath);
            rec.optic_disc_mask_path = '';
            rec.optic_disc_center = [NaN, NaN];
            rec.optic_disc_radius = NaN;
            rec.fovea_center = [NaN, NaN];
            rec.vessel_mask_path = char(vesselPath);
            rec.observer_id = '1st_manual';
            rec.split = char(splitName);
            rec.license = license;

            records = [records; rec];
        end
    end
end


% =========================================================================
% 2. REFUGE Adapter
% =========================================================================
function records = import_refuge(rootPath, splitFilter)
    license = 'Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) — REFUGE Challenge (Orlando et al., 2020)';
    records = [];

    % Check for REFUGE images directory
    imgDirs = {fullfile(rootPath, 'images'), fullfile(rootPath, 'Annotation-Training400', 'Images'), rootPath};
    foundImgDir = '';
    for d = 1:numel(imgDirs)
        if isfolder(imgDirs{d}) && ~isempty(dir(fullfile(imgDirs{d}, '*.jpg')))
            foundImgDir = imgDirs{d};
            break;
        end
    end

    if isempty(foundImgDir)
        warning('import_refuge:noImages', 'No REFUGE jpg images found under %s', rootPath);
        return;
    end

    % Check for Disc/Cup masks
    maskDirs = {fullfile(rootPath, 'Disc_Cup_Masks'), fullfile(rootPath, 'Annotation-Training400', 'Disc_Cup_Masks'), fullfile(rootPath, 'masks')};
    foundMaskDir = '';
    for d = 1:numel(maskDirs)
        if isfolder(maskDirs{d})
            foundMaskDir = maskDirs{d};
            break;
        end
    end

    % Check for Fovea Location CSV
    foveaMap = containers.Map();
    foveaCsvCandidates = {fullfile(rootPath, 'Fovea_Locations.csv'), fullfile(rootPath, 'Fovea_coordinates.csv')};
    for c = 1:numel(foveaCsvCandidates)
        if isfile(foveaCsvCandidates{c})
            try
                csvData = readtable(foveaCsvCandidates{c});
                varNames = lower(csvData.Properties.VariableNames);
                nameCol = find(contains(varNames, 'name') | contains(varNames, 'img'), 1);
                xCol = find(contains(varNames, 'x'), 1);
                yCol = find(contains(varNames, 'y'), 1);
                if ~isempty(nameCol) && ~isempty(xCol) && ~isempty(yCol)
                    for r = 1:height(csvData)
                        rowName = char(string(csvData{r, nameCol}));
                        foveaMap(rowName) = [double(csvData{r, xCol}), double(csvData{r, yCol})];
                    end
                end
            catch ME
                warning('import_refuge:csvParseError', 'Error reading fovea CSV: %s', ME.message);
            end
            break;
        end
    end

    imgFiles = dir(fullfile(foundImgDir, '*.jpg'));
    for k = 1:numel(imgFiles)
        [~, stem, ~] = fileparts(imgFiles(k).name);

        % Match mask
        odMaskPath = '';
        if ~isempty(foundMaskDir)
            maskFile = fullfile(foundMaskDir, [stem, '.png']);
            if isfile(maskFile)
                odMaskPath = maskFile;
            else
                maskFileBmp = fullfile(foundMaskDir, [stem, '.bmp']);
                if isfile(maskFileBmp)
                    odMaskPath = maskFileBmp;
                end
            end
        end

        % Match fovea
        foveaCoords = [NaN, NaN];
        if isKey(foveaMap, imgFiles(k).name)
            foveaCoords = foveaMap(imgFiles(k).name);
        elseif isKey(foveaMap, stem)
            foveaCoords = foveaMap(stem);
        end

        rec = struct();
        rec.dataset_name = 'REFUGE';
        rec.image_id = char(stem);
        rec.image_path = fullfile(imgFiles(k).folder, imgFiles(k).name);
        rec.fov_mask_path = '';
        rec.optic_disc_mask_path = char(odMaskPath);
        rec.optic_disc_center = [NaN, NaN];
        rec.optic_disc_radius = NaN;
        rec.fovea_center = foveaCoords;
        rec.vessel_mask_path = '';
        rec.observer_id = 'REFUGE_expert_consensus';
        rec.split = 'train';
        rec.license = license;

        records = [records; rec];
    end
end


% =========================================================================
% 3. IDRiD Structure Adapter
% =========================================================================
function records = import_idrid(rootPath, splitFilter)
    license = 'Creative Commons Attribution 4.0 International (CC BY 4.0) — IDRiD (Porwal et al., 2018)';
    records = [];

    % Optic disc mask directory search
    odDirs = {
        fullfile(rootPath, '1. Segmentation', 'b. Optic Disc'), ...
        fullfile(rootPath, 'OpticDisc_Masks'), ...
        fullfile(rootPath, 'OD_Masks')
    };
    foundOdDir = '';
    for d = 1:numel(odDirs)
        if isfolder(odDirs{d})
            foundOdDir = odDirs{d};
            break;
        end
    end

    % Images directory search
    imgDirs = {
        fullfile(rootPath, '1. Segmentation', 'a. Original Images'), ...
        fullfile(rootPath, 'Original_Images'), ...
        fullfile(rootPath, 'Images')
    };
    foundImgDir = '';
    for d = 1:numel(imgDirs)
        if isfolder(imgDirs{d})
            foundImgDir = imgDirs{d};
            break;
        end
    end

    if isempty(foundImgDir)
        imgFiles = dir(fullfile(rootPath, '*.jpg'));
        if ~isempty(imgFiles)
            foundImgDir = rootPath;
        end
    else
        imgFiles = dir(fullfile(foundImgDir, '*.jpg'));
    end

    if isempty(imgFiles)
        return;
    end

    % Fovea coordinates CSV
    foveaMap = containers.Map();
    foveaCsv = fullfile(rootPath, '2. Fovea Center', 'IDRiD_Fovea_Center.csv');
    if isfile(foveaCsv)
        try
            fData = readtable(foveaCsv);
            for r = 1:height(fData)
                imgName = char(string(fData{r, 1}));
                foveaMap(imgName) = [double(fData{r, 2}), double(fData{r, 3})];
            end
        catch
        end
    end

    for k = 1:numel(imgFiles)
        [~, stem, ~] = fileparts(imgFiles(k).name);

        odMaskPath = '';
        if ~isempty(foundOdDir)
            candTif = fullfile(foundOdDir, [stem, '_OD.tif']);
            candPng = fullfile(foundOdDir, [stem, '.png']);
            if isfile(candTif)
                odMaskPath = candTif;
            elseif isfile(candPng)
                odMaskPath = candPng;
            end
        end

        fCoords = [NaN, NaN];
        if isKey(foveaMap, imgFiles(k).name)
            fCoords = foveaMap(imgFiles(k).name);
        elseif isKey(foveaMap, stem)
            fCoords = foveaMap(stem);
        end

        rec = struct();
        rec.dataset_name = 'IDRiD';
        rec.image_id = char(stem);
        rec.image_path = fullfile(imgFiles(k).folder, imgFiles(k).name);
        rec.fov_mask_path = '';
        rec.optic_disc_mask_path = char(odMaskPath);
        rec.optic_disc_center = [NaN, NaN];
        rec.optic_disc_radius = NaN;
        rec.fovea_center = fCoords;
        rec.vessel_mask_path = '';
        rec.observer_id = 'IDRiD_expert_mask';
        rec.split = 'train';
        rec.license = license;

        records = [records; rec];
    end
end


% =========================================================================
% 4. STARE Adapter
% =========================================================================
function records = import_stare(rootPath, splitFilter)
    license = 'Open Access Academic Research — STARE Project (Hoover et al., IEEE TMI 2000)';
    records = [];

    imgDir = fullfile(rootPath, 'stare-images');
    if ~isfolder(imgDir)
        imgDir = rootPath;
    end

    labelsAhDir = fullfile(rootPath, 'labels-ah');
    labelsVkDir = fullfile(rootPath, 'labels-vk');

    imgFiles = dir(fullfile(imgDir, '*.ppm'));
    for k = 1:numel(imgFiles)
        [~, stem, ~] = fileparts(imgFiles(k).name);

        vesselAh = '';
        if isfolder(labelsAhDir)
            cand = fullfile(labelsAhDir, [stem, '.ah.ppm']);
            if isfile(cand)
                vesselAh = cand;
            end
        end

        rec = struct();
        rec.dataset_name = 'STARE';
        rec.image_id = char(stem);
        rec.image_path = fullfile(imgFiles(k).folder, imgFiles(k).name);
        rec.fov_mask_path = '';
        rec.optic_disc_mask_path = '';
        rec.optic_disc_center = [NaN, NaN];
        rec.optic_disc_radius = NaN;
        rec.fovea_center = [NaN, NaN];
        rec.vessel_mask_path = char(vesselAh);
        rec.observer_id = 'Adam_Hoover';
        rec.split = 'all';
        rec.license = license;

        records = [records; rec];
    end
end
