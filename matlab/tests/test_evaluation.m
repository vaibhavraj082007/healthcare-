classdef test_evaluation < matlab.unittest.TestCase
% TEST_EVALUATION Unit tests for RetinaShield Reproducible Evaluation Suite:
%   - evaluate_model_suite.m
%
% Verifies:
%   1. Report generation and required metric fields
%   2. Quadratic Weighted Kappa calculation and bounds
%   3. Multi-class confusion matrix dimensions and properties
%   4. Screening endpoint metrics (rDR Sensitivity & Specificity)
%   5. Patient-level cluster bootstrap 95% Confidence Intervals
%   6. JSON export validity
%
% Run with:
%   results = runtests('test_evaluation')
%
% Copyright (c) 2026 RetinaShield Research Project

    properties
        TempDir
        ManifestPath
        ModelPath
        OutputDir
    end

    methods (TestClassSetup)
        function setupFixtures(testCase)
            testCase.TempDir = fullfile(tempdir, 'retinashield_eval_test');
            testCase.OutputDir = fullfile(testCase.TempDir, 'output');
            if ~isfolder(testCase.OutputDir)
                mkdir(testCase.OutputDir);
            end

            % Create small synthetic test manifest
            testCase.ManifestPath = fullfile(testCase.TempDir, 'test_eval_manifest.csv');
            n = 20;
            id_code = cell(n, 1);
            diagnosis = zeros(n, 1);
            patient_id = cell(n, 1);

            for i = 1:n
                id_code{i} = sprintf('eval_%03d', i);
                diagnosis(i) = mod(i - 1, 5);
                patient_id{i} = sprintf('PAT_%03d', ceil(i / 2)); % 2 images per patient
            end
            t = table(id_code, diagnosis, patient_id);
            writetable(t, testCase.ManifestPath);

            testCase.ModelPath = fullfile(testCase.TempDir, 'mock_model.mat');
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
        function testEvaluationReportStructure(testCase)
            % Report must contain all core clinical metrics and metadata
            report = evaluate_model_suite(testCase.ManifestPath, testCase.ModelPath, ...
                testCase.OutputDir, 'bootstrapIterations', 50, 'seed', 42);

            testCase.verifyNotEmpty(report.report_id);
            testCase.verifyEqual(report.pipeline_version, '1.0.0-frozen');
            testCase.verifyEqual(report.rules_version, '1.0.0');

            % QWK
            testCase.verifyTrue(isfield(report, 'quadratic_weighted_kappa'));
            testCase.verifyTrue(report.quadratic_weighted_kappa.value >= -1.0 && report.quadratic_weighted_kappa.value <= 1.0);
            testCase.verifyTrue(report.quadratic_weighted_kappa.ci_lower <= report.quadratic_weighted_kappa.ci_upper);

            % Macro-F1
            testCase.verifyTrue(isfield(report, 'macro_f1'));
            testCase.verifyTrue(report.macro_f1.value >= 0.0 && report.macro_f1.value <= 1.0);

            % Referable DR
            testCase.verifyTrue(isfield(report, 'referable_dr'));
            testCase.verifyTrue(report.referable_dr.sensitivity.value >= 0.0 && report.referable_dr.sensitivity.value <= 1.0);
            testCase.verifyTrue(report.referable_dr.specificity.value >= 0.0 && report.referable_dr.specificity.value <= 1.0);

            % Confusion Matrix
            testCase.verifyEqual(size(report.confusion_matrix), [5, 5]);
            testCase.verifyEqual(sum(report.confusion_matrix(:)), 20);

            % JSON file existence
            jsonPath = fullfile(testCase.OutputDir, 'matlab_evaluation_report.json');
            testCase.verifyTrue(isfile(jsonPath));
        end

        function testPatientClusterBootstrapBounds(testCase)
            % Bootstrap intervals must be statistically valid (lower <= upper)
            report = evaluate_model_suite(testCase.ManifestPath, testCase.ModelPath, ...
                testCase.OutputDir, 'bootstrapIterations', 50, 'seed', 123);

            testCase.verifyTrue(report.referable_dr.sensitivity.ci_lower <= report.referable_dr.sensitivity.ci_upper);
            testCase.verifyTrue(report.referable_dr.specificity.ci_lower <= report.referable_dr.specificity.ci_upper);
        end
    end
end
