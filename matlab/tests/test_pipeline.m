classdef test_pipeline < matlab.unittest.TestCase
% TEST_PIPELINE Unit tests for the RetinaShield MATLAB analysis pipeline.
%
% Run with:
%   results = runtests('test_pipeline')
%
% These tests use synthetic images to validate pipeline stages without
% requiring a real fundus dataset or trained model weights.
%
% Copyright (c) 2026 RetinaShield Research Project

    properties (TestParameter)
    end

    properties
        TestImagePath
        OutputDir
    end

    methods (TestClassSetup)
        function createTestFixtures(testCase)
            % Create a synthetic "fundus-like" test image
            testCase.OutputDir = fullfile(tempdir, 'retinashield_test');
            if ~isfolder(testCase.OutputDir)
                mkdir(testCase.OutputDir);
            end

            % Create a 512x512 synthetic fundus image:
            %   - Dark background (like a fundus camera field)
            %   - Bright circular disc (simulating optic disc)
            %   - Branching patterns (very rough vessel simulation)
            img = zeros(512, 512, 3, 'uint8');

            % Add a circular fundus field
            [X, Y] = meshgrid(1:512, 1:512);
            center = 256;
            radius = 220;
            fundusMask = sqrt((X - center).^2 + (Y - center).^2) < radius;

            % Fill fundus region with retina-like color
            img(:,:,1) = uint8(fundusMask * 140);  % Red
            img(:,:,2) = uint8(fundusMask * 80);   % Green
            img(:,:,3) = uint8(fundusMask * 40);    % Blue

            % Add a bright "optic disc" region
            odCenter = [370, 256];
            odRadius = 40;
            odMask = sqrt((X - odCenter(1)).^2 + (Y - odCenter(2)).^2) < odRadius;
            img(:,:,1) = img(:,:,1) + uint8(odMask * 110);
            img(:,:,2) = img(:,:,2) + uint8(odMask * 100);
            img(:,:,3) = img(:,:,3) + uint8(odMask * 60);

            % Add some line structures (crude vessel approximation)
            for angle = [0, 30, -30, 60, -60, 90]
                for t = -200:200
                    x = round(center + t * cosd(angle));
                    y = round(center + t * sind(angle));
                    if x > 2 && x < 511 && y > 2 && y < 511 && fundusMask(y, x)
                        img(y-1:y+1, x-1:x+1, 1) = max(0, img(y-1:y+1, x-1:x+1, 1) - 30);
                        img(y-1:y+1, x-1:x+1, 2) = max(0, img(y-1:y+1, x-1:x+1, 2) - 20);
                    end
                end
            end

            testCase.TestImagePath = fullfile(testCase.OutputDir, 'synthetic_fundus.png');
            imwrite(img, testCase.TestImagePath);
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
    % Quality Assessment Tests
    % ===================================================================
    methods (Test)
        function testQualityAssessmentReturnsStruct(testCase)
            result = quality_assessment(testCase.TestImagePath);
            testCase.verifyClass(result, 'struct');
            testCase.verifyTrue(isfield(result, 'overall_quality'));
            testCase.verifyTrue(isfield(result, 'sharpness_score'));
            testCase.verifyTrue(isfield(result, 'illumination_uniformity'));
            testCase.verifyTrue(isfield(result, 'field_of_view_adequate'));
            testCase.verifyTrue(isfield(result, 'artifacts_detected'));
        end

        function testQualityAssessmentValidValues(testCase)
            result = quality_assessment(testCase.TestImagePath);
            validQualities = {'good', 'acceptable', 'poor', 'rejected'};
            testCase.verifyTrue(ismember(result.overall_quality, validQualities), ...
                sprintf('Quality "%s" is not a valid value.', result.overall_quality));
            testCase.verifyGreaterThanOrEqual(result.illumination_uniformity, 0);
            testCase.verifyLessThanOrEqual(result.illumination_uniformity, 1);
        end
    end

    % ===================================================================
    % Enhancement Tests
    % ===================================================================
    methods (Test)
        function testEnhanceFundusCreatesFiles(testCase)
            enhDir = fullfile(testCase.OutputDir, 'enhance_test');
            result = enhance_fundus(testCase.TestImagePath, enhDir);
            testCase.verifyClass(result, 'struct');
            testCase.verifyTrue(isfile(result.green_channel_path), ...
                'Green channel file not created.');
            testCase.verifyTrue(isfile(result.enhanced_image_path), ...
                'Enhanced image file not created.');
        end
    end

    % ===================================================================
    % Structure Segmentation Tests
    % ===================================================================
    methods (Test)
        function testSegmentStructuresReturnsComplete(testCase)
            segDir = fullfile(testCase.OutputDir, 'segment_test');
            result = segment_structures(testCase.TestImagePath, segDir);
            testCase.verifyTrue(isfield(result, 'field_of_view'));
            testCase.verifyTrue(isfield(result, 'optic_disc'));
            testCase.verifyTrue(isfield(result, 'macula'));
            testCase.verifyTrue(isfield(result, 'fovea'));
            testCase.verifyTrue(isfield(result, 'vasculature'));
            testCase.verifyTrue(isfield(result, 'is_experimental'));
            testCase.verifyTrue(result.is_experimental);
            testCase.verifyTrue(isfield(result.optic_disc, 'detected'));
            testCase.verifyTrue(isfield(result.macula, 'detected'));
        end
    end

    % ===================================================================
    % Classifier Tests (Without Trained Model)
    % ===================================================================
    methods (Test)
        function testClassifyDrUntrainedReturnsPlaceholder(testCase)
            result = classify_dr(testCase.TestImagePath);
            testCase.verifyFalse(result.model_trained, ...
                'model_trained should be false when no weights file exists.');
            testCase.verifyEqual(result.predicted_grade, -1, ...
                'Untrained model should return grade -1.');
            testCase.verifyTrue(contains(result.grade_label, 'UNTRAINED'), ...
                'Untrained model grade_label should contain UNTRAINED.');
        end
    end

    % ===================================================================
    % Full Pipeline Tests
    % ===================================================================
    methods (Test)
        function testRunPipelineProducesResult(testCase)
            pipelineDir = fullfile(testCase.OutputDir, 'pipeline_test');
            result = run_pipeline(testCase.TestImagePath, pipelineDir);
            testCase.verifyClass(result, 'struct');
            testCase.verifyTrue(isfield(result, 'analysis_id'));
            testCase.verifyTrue(isfield(result, 'pipeline_version'));
            testCase.verifyTrue(isfield(result, 'disclaimer'));
            testCase.verifyTrue(contains(result.disclaimer, 'RESEARCH SCREENING'));
            testCase.verifyTrue(isfield(result, 'quality_assessment'));
            testCase.verifyTrue(isfield(result, 'severity_classification'));
            testCase.verifyTrue(isfield(result, 'referral_recommendation'));
        end

        function testRunPipelineSavesJSON(testCase)
            pipelineDir = fullfile(testCase.OutputDir, 'pipeline_json_test');
            run_pipeline(testCase.TestImagePath, pipelineDir);
            jsonPath = fullfile(pipelineDir, 'analysis_result.json');
            testCase.verifyTrue(isfile(jsonPath), 'Pipeline should save analysis_result.json.');

            % Verify JSON is valid
            jsonText = fileread(jsonPath);
            decoded = jsondecode(jsonText);
            testCase.verifyClass(decoded, 'struct');
        end
    end
end
