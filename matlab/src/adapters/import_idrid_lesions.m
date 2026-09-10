function manifest = import_idrid_lesions(datasetRoot, options)
% IMPORT_IDRID_LESIONS Import expert-annotated lesion masks from IDRiD.
%
% Ingests pixel-level ground truth binary masks for:
%   1. Microaneurysms (MA)
%   2. Haemorrhages (HE)
%   3. Hard Exudates (EX)
%   4. Soft Exudates / Cotton-Wool Spots (SE / CWS)
%
% Extracts connected components, bounding boxes, approximate extent (area,
% equivalent diameter), and maps records into development (train/val) and
% evaluation (test) splits.
%
% TERMS & LICENSE:
%   IDRiD is published under Creative Commons Attribution 4.0 International (CC BY 4.0).
%   Citation: Porwal et al., "Indian Diabetic Retinopathy Image Dataset (IDRiD)",
%   IEEE DataPort, 2018.
%
% USAGE:
%   manifest = import_idrid_lesions('/path/to/IDRiD_Segmentation')
%   manifest = import_idrid_lesions(datasetRoot, 'outputJson', './idrid_lesions.json')
%
% INPUTS:
%   datasetRoot - (string) Root directory of IDRiD segmentation dataset
%   options     - Name-value pairs:
%       'split'      - (string) 'all' | 'train' | 'test' (default: 'all')
%       'outputJson' - (string) Optional file path to export manifest JSON
%
% OUTPUT:
%   manifest - (struct array):
%     .image_id         - Image identifier (e.g. 'IDRiD_01')
%     .split            - 'train' | 'val' | 'test'
%     .dimensions       - [width, height]
%     .detections       - Array of structs:
%         .lesion_type        - 'microaneurysm' | 'hemorrhage' | 'hard_exudate' | 'soft_exudate'
%         .bbox               - [x_min, y_min, x_max, y_max]
%         .approximate_extent - struct with area_pixels, equivalent_diameter
%     .estimated_counts - struct with counts per lesion type
%     .license          - License attribution
%
% Copyright (c) 2026 RetinaShield Research Project

    arguments
        datasetRoot (1,1) string {mustBeFolder}
        options.split (1,1) string = "all"
        options.outputJson (1,1) string = ""
    end

    license = 'Creative Commons Attribution 4.0 International (CC BY 4.0) — IDRiD (Porwal et al., 2018)';
    lesionTypes = {'microaneurysm', 'hemorrhage', 'hard_exudate', 'soft_exudate'};
    minAreas = [2, 6, 4, 10]; % Minimum pixel areas to filter noise

    % Candidate image folders
    trainDirs = {
        fullfile(datasetRoot, 'Original Images', 'Training Set'), ...
        fullfile(datasetRoot, 'a. Original Images', 'Training Set'), ...
        fullfile(datasetRoot, 'Training Set')
    };
    testDirs = {
        fullfile(datasetRoot, 'Original Images', 'Testing Set'), ...
        fullfile(datasetRoot, 'a. Original Images', 'Testing Set'), ...
        fullfile(datasetRoot, 'Testing Set')
    };

    trainImgDir = '';
    for d = 1:numel(trainDirs)
        if isfolder(trainDirs{d}) && ~isempty(dir(fullfile(trainDirs{d}, '*.jpg')))
            trainImgDir = trainDirs{d};
            break;
        end
    end

    testImgDir = '';
    for d = 1:numel(testDirs)
        if isfolder(testDirs{d}) && ~isempty(dir(fullfile(testDirs{d}, '*.jpg')))
            testImgDir = testDirs{d};
            break;
        end
    end

    manifest = [];
    allImages = {};
    splits = {};

    if ~isempty(trainImgDir) && (options.split == "all" || options.split == "train")
        trainFiles = dir(fullfile(trainImgDir, '*.jpg'));
        for i = 1:numel(trainFiles)
            allImages{end+1} = fullfile(trainFiles(i).folder, trainFiles(i).name);
            splits{end+1} = 'train';
        end
    end

    if ~isempty(testImgDir) && (options.split == "all" || options.split == "test")
        testFiles = dir(fullfile(testImgDir, '*.jpg'));
        for i = 1:numel(testFiles)
            allImages{end+1} = fullfile(testFiles(i).folder, testFiles(i).name);
            splits{end+1} = 'test';
        end
    end

    fprintf('[IDRiD Lesion Importer] Found %d images across splits.\n', numel(allImages));

    for k = 1:numel(allImages)
        imgPath = allImages{k};
        [~, stem, ~] = fileparts(imgPath);
        info = imfinfo(imgPath);
        imgW = info.Width;
        imgH = info.Height;

        rec = struct();
        rec.image_id = char(stem);
        rec.image_path = char(imgPath);
        rec.split = splits{k};
        rec.dimensions = [imgW, imgH];
        rec.license = license;

        counts = struct('microaneurysm', 0, 'hemorrhage', 0, 'hard_exudate', 0, 'soft_exudate', 0);
        detections = [];

        for l = 1:numel(lesionTypes)
            lType = lesionTypes{l};
            mArea = minAreas(l);
            maskPath = find_mask(datasetRoot, stem, lType);

            if ~isempty(maskPath) && isfile(maskPath)
                maskImg = imread(maskPath);
                if size(maskImg, 3) == 3
                    maskImg = rgb2gray(maskImg);
                end
                bw = maskImg > 127;

                cc = bwconncomp(bw, 8);
                if cc.NumObjects > 0
                    stats = regionprops(cc, 'BoundingBox', 'Area', 'EquivDiameter');
                    for b = 1:numel(stats)
                        if stats(b).Area >= mArea
                            bbox = stats(b).BoundingBox; % [x, y, w, h] in 1-based pixel coords
                            detItem = struct();
                            detItem.lesion_type = lType;
                            detItem.bbox = [bbox(1), bbox(2), bbox(1) + bbox(3), bbox(2) + bbox(4)];
                            detItem.approximate_extent = struct(...
                                'area_pixels', stats(b).Area, ...
                                'equivalent_diameter', round(stats(b).EquivDiameter, 1), ...
                                'width', bbox(3), ...
                                'height', bbox(4) ...
                            );
                            detections = [detections; detItem];
                            counts.(lType) = counts.(lType) + 1;
                        end
                    end
                end
            end
        end

        rec.detections = detections;
        rec.estimated_counts = counts;
        manifest = [manifest; rec];
    end

    fprintf('[IDRiD Lesion Importer Done] Processed %d records.\n', numel(manifest));

    if options.outputJson ~= ""
        jsonText = jsonencode(manifest, 'PrettyPrint', true);
        fid = fopen(options.outputJson, 'w');
        if fid ~= -1
            fprintf(fid, '%s', jsonText);
            fclose(fid);
            fprintf('  -> Exported JSON to: %s\n', options.outputJson);
        end
    end
end


function maskPath = find_mask(rootPath, stem, lesionType)
    maskPath = '';
    candFolders = {
        fullfile(rootPath, 'Groundtruths'), ...
        fullfile(rootPath, 'b. Groundtruths'), ...
        rootPath
    };

    switch lesionType
        case 'microaneurysm'
            subNames = {'1. Microaneurysms', 'Microaneurysms', 'MA'};
        case 'hemorrhage'
            subNames = {'2. Haemorrhages', 'Haemorrhages', 'Hemorrhages', 'HE'};
        case 'hard_exudate'
            subNames = {'3. Hard Exudates', 'Hard Exudates', 'EX'};
        case 'soft_exudate'
            subNames = {'4. Soft Exudates', 'Soft Exudates', 'SE'};
    end

    for f = 1:numel(candFolders)
        if ~isfolder(candFolders{f})
            continue;
        end
        for s = 1:numel(subNames)
            dirCand = fullfile(candFolders{f}, subNames{s});
            if isfolder(dirCand)
                hits = dir(fullfile(dirCand, [char(stem), '*.*']));
                for h = 1:numel(hits)
                    [~, ~, ext] = fileparts(hits(h).name);
                    if ismember(lower(ext), {'.tif', '.png', '.jpg'})
                        maskPath = fullfile(hits(h).folder, hits(h).name);
                        return;
                    end
                end
            end
        end
    end
end
