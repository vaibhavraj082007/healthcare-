classdef test_structures < matlab.unittest.TestCase
% TEST_STRUCTURES Unit tests for RetinaShield modular structure segmentation functions:
%   - segment_fov.m
%   - segment_optic_disc.m
%   - localize_fovea.m
%   - segment_vessels.m
%   - segment_structures.m
%   - import_structure_dataset.m
%
% Run with:
%   results = runtests('test_structures')
%
% Copyright (c) 2026 RetinaShield Research Project

    properties
        OutputDir
        NormalFundusPath
        NoDiscFundusPath
        ExudatesFundusPath
        RectangularFundusPath
    end

    methods (TestClassSetup)
        function createTestFixtures(testCase)
            testCase.OutputDir = fullfile(tempdir, 'retinashield_struct_test');
            if ~isfolder(testCase.OutputDir)
                mkdir(testCase.OutputDir);
            end

            % Common meshgrid for 512x512 images
            [X, Y] = meshgrid(1:512, 1:512);
            center = 256;
            radius = 220;
            fundusMask = sqrt((X - center).^2 + (Y - center).^2) < radius;

            % --- Fixture 1: Normal Right Eye (OD) Fundus ---
            % Optic disc on nasal side (left: x=180, y=256), Fovea on temporal side (right: x=360, y=265)
            imgNormal = zeros(512, 512, 3, 'uint8');
            imgNormal(:,:,1) = uint8(fundusMask * 140);
            imgNormal(:,:,2) = uint8(fundusMask * 80);
            imgNormal(:,:,3) = uint8(fundusMask * 35);

            % Add OD (bright disc)
            odCenter = [180, 256];
            odMask = sqrt((X - odCenter(1)).^2 + (Y - odCenter(2)).^2) < 38;
            imgNormal(:,:,1) = imgNormal(:,:,1) + uint8(odMask * 100);
            imgNormal(:,:,2) = imgNormal(:,:,2) + uint8(odMask * 90);
            imgNormal(:,:,3) = imgNormal(:,:,3) + uint8(odMask * 50);

            % Add Fovea (dark dip)
            foveaCenter = [360, 265];
            foveaMask = sqrt((X - foveaCenter(1)).^2 + (Y - foveaCenter(2)).^2) < 22;
            imgNormal(:,:,2) = max(10, imgNormal(:,:,2) - uint8(foveaMask * 40));

            % Add radial vessel branches from OD
            for angle = [-50, -30, 0, 30, 50, 140, 160, 200, 220]
                for t = 10:180
                    vx = round(odCenter(1) + t * cosd(angle));
                    vy = round(odCenter(2) + t * sind(angle));
                    if vx > 2 && vx < 510 && vy > 2 && vy < 510 && fundusMask(vy, vx)
                        imgNormal(vy-1:vy+1, vx-1:vx+1, 2) = max(0, imgNormal(vy-1:vy+1, vx-1:vx+1, 2) - 30);
                    end
                end
            end

            testCase.NormalFundusPath = fullfile(testCase.OutputDir, 'normal_od_fundus.png');
            imwrite(imgNormal, testCase.NormalFundusPath);

            % --- Fixture 2: Fundus with OD Outside Field of View (e.g. Macula-Centered / Peripheral) ---
            imgNoDisc = zeros(512, 512, 3, 'uint8');
            imgNoDisc(:,:,1) = uint8(fundusMask * 130);
            imgNoDisc(:,:,2) = uint8(fundusMask * 75);
            imgNoDisc(:,:,3) = uint8(fundusMask * 30);
            % Fovea in center, no bright disc anywhere
            imgNoDisc(:,:,2) = max(10, imgNoDisc(:,:,2) - uint8(foveaMask * 35));

            testCase.NoDiscFundusPath = fullfile(testCase.OutputDir, 'no_disc_fundus.png');
            imwrite(imgNoDisc, testCase.NoDiscFundusPath);

            % --- Fixture 3: Image with Flash Glare & Multiple Hard Exudates ---
            % Ensures false-positive resistance: small bright exudates must not fool the OD detector
            imgExudates = imgNormal;
            % Add small punctate bright spots (simulating hard exudates)
            for ex = [320, 340, 330, 280]
                for ey = [180, 190, 210, 170]
                    exMask = sqrt((X - ex).^2 + (Y - ey).^2) < 6;
                    imgExudates(:,:,1) = imgExudates(:,:,1) + uint8(exMask * 115);
                    imgExudates(:,:,2) = imgExudates(:,:,2) + uint8(exMask * 115);
                end
            end
            % Add flash reflection near edge (saturated white, no vessels)
            glareMask = sqrt((X - 420).^2 + (Y - 140).^2) < 25;
            imgExudates(:,:,1) = imgExudates(:,:,1) + uint8(glareMask * 150);
            imgExudates(:,:,2) = imgExudates(:,:,2) + uint8(glareMask * 150);
            imgExudates(:,:,3) = imgExudates(:,:,3) + uint8(glareMask * 150);

            testCase.ExudatesFundusPath = fullfile(testCase.OutputDir, 'exudates_fundus.png');
            imwrite(imgExudates, testCase.ExudatesFundusPath);

            % --- Fixture 4: Rectangular Pre-Cropped Fundus ---
            imgRect = uint8(randi([50, 180], 400, 600, 3));
            testCase.RectangularFundusPath = fullfile(testCase.OutputDir, 'rect_fundus.png');
            imwrite(imgRect, testCase.RectangularFundusPath);
        end
    end

    methods (TestClassTeardown)
        function cleanupTestFixtures(testCase)
            if isfolder(testCase.OutputDir)
                rmdir(testCase.OutputDir, 's');
            end
        end
    end

    % ===================================================================
    % 1. Field of View (FOV) Segmentation Tests
    % ===================================================================
    methods (Test)
        function testFovSegmentationCircular(testCase)
            res = segment_fov(testCase.NormalFundusPath);
            testCase.verifyTrue(res.is_reliable);
            testCase.verifyGreaterThan(res.area_ratio, 0.40);
            testCase.verifyLessThan(res.area_ratio, 0.95);
            testCase.verifyEqual(res.failure_reason, '');
            testCase.verifyEqual(size(res.mask), [512, 512]);
        end

        function testFovSegmentationRectangular(testCase)
            res = segment_fov(testCase.RectangularFundusPath);
            testCase.verifyTrue(res.is_reliable);
            testCase.verifyGreaterThanOrEqual(res.area_ratio, 0.90);
        end
    end

    % ===================================================================
    % 2. Optic Disc Localization & Segmentation Tests
    % ===================================================================
    methods (Test)
        function testOpticDiscLocalizationNormal(testCase)
            res = segment_optic_disc(testCase.NormalFundusPath);
            testCase.verifyTrue(res.detected, 'Optic disc should be detected in normal image.');
            testCase.verifyTrue(res.is_reliable);
            % Check localization is near x=180, y=256
            testCase.verifyLessThan(abs(res.center_x - 180), 30);
            testCase.verifyLessThan(abs(res.center_y - 256), 30);
            testCase.verifyGreaterThan(res.confidence, 0.50);
            testCase.verifyEqual(size(res.mask), [512, 512]);
        end

        function testOpticDiscFalsePositiveResistance(testCase)
            % When exudates and flash glare are present, it must still locate the true disc
            res = segment_optic_disc(testCase.ExudatesFundusPath);
            testCase.verifyTrue(res.detected);
            testCase.verifyLessThan(abs(res.center_x - 180), 35);
        end

        function testOpticDiscOutsideFovFailsExplicitly(testCase)
            % When no optic disc is in the image, must fail explicitly rather than hallucinating
            res = segment_optic_disc(testCase.NoDiscFundusPath, 'minConfidence', 0.60);
            testCase.verifyFalse(res.detected, 'Must fail when disc is not in image.');
            testCase.verifyFalse(res.is_reliable);
            testCase.verifyNotEmpty(res.failure_reason);
        end
    end

    % ===================================================================
    % 3. Fovea Localization Tests
    % ===================================================================
    methods (Test)
        function testFoveaLocalizationWithOdReference(testCase)
            od = segment_optic_disc(testCase.NormalFundusPath);
            fovea = localize_fovea(testCase.NormalFundusPath, od);
            testCase.verifyTrue(fovea.detected, 'Fovea should be detected.');
            % Check localization near x=360, y=265
            testCase.verifyLessThan(abs(fovea.center_x - 360), 40);
            testCase.verifyEqual(fovea.inferred_laterality, 'OD');
            testCase.verifyTrue(fovea.is_reliable);
        end

        function testFoveaLeftEyeLateralityInference(testCase)
            % Simulated Left Eye (OS) where OD is on nasal side (right side: x=350, y=256)
            fakeOdOS = struct('detected', true, 'center_x', 360, 'center_y', 256, ...
                              'radius', 35, 'confidence', 0.88, 'is_reliable', true);
            fovea = localize_fovea(testCase.NormalFundusPath, fakeOdOS, 'laterality', 'auto');
            % Should infer Left Eye ('OS') and search to the left of the disc
            testCase.verifyEqual(fovea.inferred_laterality, 'OS');
        end
    end

    % ===================================================================
    % 4. Retinal Vessel Segmentation Tests
    % ===================================================================
    methods (Test)
        function testVesselSegmentationMetrics(testCase)
            res = segment_vessels(testCase.NormalFundusPath);
            testCase.verifyTrue(res.is_reliable);
            testCase.verifyGreaterThan(res.vessel_density, 0.01);
            testCase.verifyLessThan(res.vessel_density, 0.30);
            testCase.verifyGreaterThanOrEqual(res.tortuosity_index, 1.0);
            testCase.verifyEqual(size(res.mask), [512, 512]);
            testCase.verifyEqual(size(res.skeleton_mask), [512, 512]);
        end
    end

    % ===================================================================
    % 5. Orchestrated Structure Segmentation Pipeline
    % ===================================================================
    methods (Test)
        function testSegmentStructuresOrchestrator(testCase)
            outDir = fullfile(testCase.OutputDir, 'pipeline_out');
            res = segment_structures(testCase.NormalFundusPath, outDir);
            
            testCase.verifyTrue(isfield(res, 'field_of_view'));
            testCase.verifyTrue(isfield(res, 'optic_disc'));
            testCase.verifyTrue(isfield(res, 'macula'));
            testCase.verifyTrue(isfield(res, 'fovea'));
            testCase.verifyTrue(isfield(res, 'vasculature'));
            testCase.verifyTrue(res.is_experimental);
            testCase.verifyTrue(res.optic_disc.detected);
            testCase.verifyTrue(res.fovea.detected);
            testCase.verifyNotEmpty(res.field_of_view.mask_path);
        end
    end
end
