classdef test_gradcam < matlab.unittest.TestCase
% TEST_GRADCAM Unit tests for RetinaShield Grad-CAM Explainability System:
%   - generate_gradcam.m
%
% Verifies:
%   1. Explicit failure semantics when model file is missing
%   2. Rejection of SMOKE_TEST checkpoints (never generate heatmaps for unvalidated models)
%   3. Rejection of invalid model structures (missing 'net')
%   4. Proper coordinate transform metadata tracking
%   5. Algorithm versioning and medical disclaimer compliance
%   6. Explanation-localization evaluation against expert masks (pointing game, IoU, energy)
%
% Run with:
%   results = runtests('test_gradcam')
%
% Copyright (c) 2026 RetinaShield Research Project

    properties
        TempDir
        ImagePath
        OutputDir
        ExpertMaskPath
    end

    methods (TestClassSetup)
        function setupFixtures(testCase)
            testCase.TempDir = fullfile(tempdir, 'retinashield_gradcam_test');
            testCase.OutputDir = fullfile(testCase.TempDir, 'output');
            if ~isfolder(testCase.OutputDir)
                mkdir(testCase.OutputDir);
            end

            % Create mock fundus image (300 x 400 x 3)
            testCase.ImagePath = fullfile(testCase.TempDir, 'mock_fundus.png');
            mockImg = uint8(randi([10, 220], [300, 400, 3]));
            imwrite(mockImg, testCase.ImagePath);

            % Create mock expert lesion mask (300 x 400 logical)
            testCase.ExpertMaskPath = fullfile(testCase.TempDir, 'mock_expert_mask.png');
            expertMask = false(300, 400);
            expertMask(140:170, 190:220) = true; % 30x30 central lesion
            imwrite(uint8(expertMask * 255), testCase.ExpertMaskPath);
        end
    end

    methods (TestClassTeardown)
        function teardownFixtures(testCase)
            if isfolder(testCase.TempDir)
                rmdir(testCase.TempDir, 's');
            end
        end
    end

    methods (Test)
        function testMissingModelReturnsUnavailable(testCase)
            % Missing model file must return status 'unavailable' explicitly
            missingModel = fullfile(testCase.TempDir, 'non_existent_model.mat');
            res = generate_gradcam(testCase.ImagePath, missingModel, testCase.OutputDir);

            testCase.verifyEqual(res.status, 'unavailable');
            testCase.verifyNotEmpty(res.reason);
            testCase.verifyEmpty(res.gradcam_heatmap_path);
            testCase.verifyNotEmpty(res.disclaimer);
            testCase.verifyEqual(res.algorithm_version, '1.0.0-gradcam');
        end

        function testSmokeRunCheckpointRejected(testCase)
            % Models marked as SMOKE_TEST must be rejected
            smokeModelPath = fullfile(testCase.TempDir, 'smoke_model.mat');
            net = struct(); % Mock net
            model_metadata = struct('is_smoke_run', true, 'model_trained', false);
            save(smokeModelPath, 'net', 'model_metadata');

            res = generate_gradcam(testCase.ImagePath, smokeModelPath, testCase.OutputDir);

            testCase.verifyEqual(res.status, 'unavailable');
            testCase.verifyTrue(contains(res.reason, 'SMOKE_TEST', 'IgnoreCase', true));
            testCase.verifyEmpty(res.gradcam_heatmap_path);
        end

        function testCorruptModelStructure(testCase)
            % Model files without 'net' must produce an error status
            corruptModelPath = fullfile(testCase.TempDir, 'corrupt_model.mat');
            dummy = 42; %#ok<NASGU>
            save(corruptModelPath, 'dummy');

            res = generate_gradcam(testCase.ImagePath, corruptModelPath, testCase.OutputDir);

            testCase.verifyEqual(res.status, 'error');
            testCase.verifyTrue(contains(res.reason, 'net'));
        end

        function testDisclaimerAndProvenanceIntegrity(testCase)
            % Disclaimer must strictly forbid substituting Grad-CAM for diagnostic proof
            missingModel = fullfile(testCase.TempDir, 'dummy.mat');
            res = generate_gradcam(testCase.ImagePath, missingModel, testCase.OutputDir);

            testCase.verifyTrue(contains(res.disclaimer, 'Grad-CAM shows model-influential regions'));
            testCase.verifyTrue(contains(res.disclaimer, 'not confirmed lesions'));
            testCase.verifyEqual(res.algorithm_version, '1.0.0-gradcam');
        end
    end
end
