classdef test_dr_training < matlab.unittest.TestCase
% TEST_DR_TRAINING Unit tests for RetinaShield DR severity classifier training pipeline:
%   - train_dr_classifier.m
%   - classify_dr.m (with metadata bundle inspection and smoke checkpoint rejection)
%
% Run with:
%   results = runtests('test_dr_training')
%
% Copyright (c) 2026 RetinaShield Research Project

    properties
        TempDir
        SplitsDir
        ImagesDir
        ModelPath
    end

    methods (TestClassSetup)
        function setupFixtures(testCase)
            testCase.TempDir = fullfile(tempdir, 'retinashield_train_test');
            testCase.SplitsDir = fullfile(testCase.TempDir, 'splits');
            testCase.ImagesDir = fullfile(testCase.TempDir, 'images');
            testCase.ModelPath = fullfile(testCase.TempDir, 'test_efficientnet_dr.mat');

            if ~isfolder(testCase.SplitsDir)
                mkdir(testCase.SplitsDir);
            end
            if ~isfolder(testCase.ImagesDir)
                mkdir(testCase.ImagesDir);
            end

            % Create mock synthetic images and CSV manifests
            for i = 1:15
                img = uint8(randi([20, 200], [64, 64, 3]));
                imwrite(img, fullfile(testCase.ImagesDir, sprintf('test_fundus_%03d.jpg', i)));
            end

            % Create train_manifest.csv (10 images)
            trainIDs = cell(10, 1);
            trainGrades = zeros(10, 1);
            for i = 1:10
                trainIDs{i} = sprintf('test_fundus_%03d', i);
                trainGrades(i) = mod(i - 1, 5);
            end
            trainTbl = table(trainIDs, trainGrades, 'VariableNames', {'id_code', 'diagnosis'});
            writetable(trainTbl, fullfile(testCase.SplitsDir, 'train_manifest.csv'));

            % Create dev_manifest.csv (5 images)
            devIDs = cell(5, 1);
            devGrades = zeros(5, 1);
            for i = 1:5
                devIDs{i} = sprintf('test_fundus_%03d', 10 + i);
                devGrades(i) = mod(i - 1, 5);
            end
            devTbl = table(devIDs, devGrades, 'VariableNames', {'id_code', 'diagnosis'});
            writetable(devTbl, fullfile(testCase.SplitsDir, 'dev_manifest.csv'));
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
        function testClassOrderInvariant(testCase)
            expectedOrder = {'No DR', 'Mild', 'Moderate', 'Severe', 'Proliferative DR'};
            testCase.verifyEqual(numel(expectedOrder), 5);
            testCase.verifyEqual(expectedOrder{1}, 'No DR');
            testCase.verifyEqual(expectedOrder{2}, 'Mild');
            testCase.verifyEqual(expectedOrder{3}, 'Moderate');
            testCase.verifyEqual(expectedOrder{4}, 'Severe');
            testCase.verifyEqual(expectedOrder{5}, 'Proliferative DR');
        end

        function testSmokeTrainingPipeline(testCase)
            % Execute smoke mode
            [~, info] = train_dr_classifier(testCase.TempDir, ...
                'SplitsDir', testCase.SplitsDir, ...
                'ImagesDir', testCase.ImagesDir, ...
                'ModelOutputPath', testCase.ModelPath, ...
                'SmokeMode', true, ...
                'InputSize', [64, 64, 3], ...
                'ExecutionEnvironment', 'cpu');

            testCase.verifyTrue(info.is_smoke_run, 'Must be flagged as smoke run');
            testCase.verifyFalse(info.model_trained, 'Smoke run must NOT be labeled as model_trained=true');
            testCase.verifyTrue(contains(info.status, 'SMOKE_TEST'));
            testCase.verifyNotEmpty(info.manifest_hashes.train_manifest);
            testCase.verifyNotEmpty(info.disclaimer);

            % Verify saved bundle file
            testCase.verifyTrue(isfile(testCase.ModelPath), 'Model .mat file must be saved');
            modelData = load(testCase.ModelPath);
            testCase.verifyTrue(isfield(modelData, 'model_metadata'));
            testCase.verifyTrue(modelData.model_metadata.is_smoke_run);
        end

        function testSmokeCheckpointRejectionInClassify(testCase)
            % When passing a smoke-run checkpoint to classify_dr, it must refuse to report real prediction
            sampleImgPath = fullfile(testCase.ImagesDir, 'test_fundus_001.jpg');
            
            % classify_dr with the smoke-mode model
            res = classify_dr(sampleImgPath, testCase.ModelPath, "good");

            testCase.verifyFalse(res.model_trained, 'classify_dr must report model_trained=false for smoke checkpoints');
            testCase.verifyEqual(res.predicted_grade, -1, 'Predicted grade must be -1');
            testCase.verifyTrue(contains(res.grade_label, 'SMOKE_TEST_CHECKPOINT'));
        end
    end
end
