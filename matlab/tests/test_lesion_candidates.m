classdef test_lesion_candidates < matlab.unittest.TestCase
% TEST_LESION_CANDIDATES Unit tests for RetinaShield transparent lesion candidate baseline:
%   - detect_lesion_candidates.m
%   - adapters/import_idrid_lesions.m
%
% Verifies that heuristic candidate proposals NEVER masquerade as validated detections,
% that extent metrics are computed, optic disc regions are excluded from exudates,
% and model-estimated counts are labeled transparently.
%
% Run with:
%   results = runtests('test_lesion_candidates')
%
% Copyright (c) 2026 RetinaShield Research Project

    properties
        TempDir
        SyntheticFundusPath
        SyntheticLesionPath
    end

    methods (TestClassSetup)
        function setupFixtures(testCase)
            testCase.TempDir = fullfile(tempdir, 'retinashield_lesion_test');
            if ~isfolder(testCase.TempDir)
                mkdir(testCase.TempDir);
            end

            % Create synthetic fundus image (512x512)
            [X, Y] = meshgrid(1:512, 1:512);
            center = 256;
            radius = 220;
            fovMask = sqrt((X - center).^2 + (Y - center).^2) < radius;

            img = zeros(512, 512, 3, 'uint8');
            img(:,:,1) = uint8(fovMask * 140);
            img(:,:,2) = uint8(fovMask * 80);
            img(:,:,3) = uint8(fovMask * 35);

            % Optic disc at (180, 256)
            odCenter = [180, 256];
            odMask = sqrt((X - odCenter(1)).^2 + (Y - odCenter(2)).^2) < 38;
            img(:,:,1) = img(:,:,1) + uint8(odMask * 100);
            img(:,:,2) = img(:,:,2) + uint8(odMask * 90);
            img(:,:,3) = img(:,:,3) + uint8(odMask * 50);

            testCase.SyntheticFundusPath = fullfile(testCase.TempDir, 'fundus_clean.png');
            imwrite(img, testCase.SyntheticFundusPath);

            % Add synthetic lesions:
            % 1. Microaneurysm at (240, 200) - small dark dot (radius 3)
            maMask = sqrt((X - 240).^2 + (Y - 200).^2) < 3;
            img(:,:,2) = max(0, img(:,:,2) - uint8(maMask * 60));

            % 2. Hemorrhage at (300, 320) - medium dark patch (radius 10)
            heMask = sqrt((X - 300).^2 + (Y - 320).^2) < 10;
            img(:,:,2) = max(0, img(:,:,2) - uint8(heMask * 55));

            % 3. Hard exudate at (340, 220) - bright yellow spot (radius 8)
            exMask = sqrt((X - 340).^2 + (Y - 220).^2) < 8;
            img(:,:,1) = min(255, img(:,:,1) + uint8(exMask * 90));
            img(:,:,2) = min(255, img(:,:,2) + uint8(exMask * 90));

            % 4. Soft exudate / Cotton-wool spot at (380, 180) - pale diffuse cloud (radius 14)
            cwsMask = sqrt((X - 380).^2 + (Y - 180).^2) < 14;
            img(:,:,1) = min(255, img(:,:,1) + uint8(cwsMask * 50));
            img(:,:,2) = min(255, img(:,:,2) + uint8(cwsMask * 50));
            img(:,:,3) = min(255, img(:,:,3) + uint8(cwsMask * 40));

            testCase.SyntheticLesionPath = fullfile(testCase.TempDir, 'fundus_with_lesions.png');
            imwrite(img, testCase.SyntheticLesionPath);
        end
    end

    methods (TestClassTeardown)
        function cleanupFixtures(testCase)
            if isfolder(testCase.TempDir)
                rmdir(testCase.TempDir, 's');
            end
        end
    end

    methods (Test)
        function testCandidateTransparencyGuarantees(testCase)
            % Test that all candidates have is_validated=false and heuristic labeling
            result = detect_lesion_candidates(testCase.SyntheticLesionPath);

            testCase.verifyFalse(result.is_validated, 'Whole result must be labeled is_validated=false');
            testCase.verifyEqual(result.status, 'heuristic_candidates_only');
            testCase.verifyNotEmpty(result.disclaimer, 'Must include research disclaimer');

            if ~isempty(result.candidates)
                for i = 1:numel(result.candidates)
                    cand = result.candidates(i);
                    testCase.verifyFalse(cand.is_validated, 'Individual candidate must not be validated');
                    testCase.verifyEqual(cand.candidate_type, 'heuristic_proposal');
                    testCase.verifyNotEmpty(cand.approximate_extent.area_pixels);
                    testCase.verifyGreaterThan(cand.approximate_extent.area_pixels, 0);
                    testCase.verifyGreaterThan(cand.approximate_extent.equivalent_diameter, 0);
                    testCase.verifyGreaterThanOrEqual(cand.confidence, 0.0);
                    testCase.verifyLessThanOrEqual(cand.confidence, 1.0);
                end
            end
        end

        function testOpticDiscNotMisidentifiedAsExudate(testCase)
            % Clean image only has an Optic Disc and no real exudates.
            % The OD exclusion logic must prevent the OD from generating false hard exudates.
            result = detect_lesion_candidates(testCase.SyntheticFundusPath);

            odRegion = [180 - 38, 256 - 38, 180 + 38, 256 + 38]; % [x1, y1, x2, y2]
            for i = 1:numel(result.candidates)
                cand = result.candidates(i);
                if strcmp(cand.lesion_type, 'hard_exudate')
                    % Candidate center should not be inside OD centroid region
                    cx = (cand.bbox.x_min + cand.bbox.x_max) / 2;
                    cy = (cand.bbox.y_min + cand.bbox.y_max) / 2;
                    distToOD = sqrt((cx - 180)^2 + (cy - 256)^2);
                    testCase.verifyGreaterThan(distToOD, 30, 'Hard exudate candidate cannot be inside optic disc');
                end
            end
        end

        function testModelEstimatedCountStructure(testCase)
            result = detect_lesion_candidates(testCase.SyntheticLesionPath);

            testCase.verifyTrue(isfield(result, 'model_estimated_count'));
            testCase.verifyTrue(isfield(result.model_estimated_count, 'microaneurysms'));
            testCase.verifyTrue(isfield(result.model_estimated_count, 'hemorrhages'));
            testCase.verifyTrue(isfield(result.model_estimated_count, 'hard_exudates'));
            testCase.verifyTrue(isfield(result.model_estimated_count, 'cotton_wool_spots'));
            testCase.verifyTrue(isfield(result.model_estimated_count, 'is_model_estimate'));
            testCase.verifyTrue(result.model_estimated_count.is_model_estimate);
        end
    end
end
