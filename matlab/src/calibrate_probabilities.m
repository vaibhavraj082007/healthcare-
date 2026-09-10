function result = calibrate_probabilities(rawScores, options)
% CALIBRATE_PROBABILITIES Calibrate softmax probabilities using temperature scaling
% and compute uncertainty indicators.
%
% "A softmax score alone is not clinical certainty."
%
% Evaluates max probability, margin between top 2 classes, and normalized Shannon entropy.
%
% USAGE:
%   result = calibrate_probabilities([0.1, 0.7, 0.15, 0.03, 0.02])
%   result = calibrate_probabilities(scores, 'Temperature', 1.35)
%
% INPUTS:
%   rawScores - (1xK double) Uncalibrated probability vector from softmax
%
% OPTIONS:
%   'Temperature'        - (double) Scalar temperature T > 0. Default: 1.0 (uncalibrated)
%   'IsFitted'           - (logical) True if temperature was fitted on calibration data. Default: false
%   'MinConfidence'      - (double) Threshold below which prediction is uncertain. Default: 0.65
%   'MinMargin'          - (double) Minimum margin between top 2 classes. Default: 0.15
%   'MaxEntropy'         - (double) Maximum normalized entropy threshold. Default: 0.60
%
% OUTPUT:
%   result - (struct):
%     .status                     - 'calibrated' | 'uncalibrated_raw_softmax' | 'fallback_uniform'
%     .temperature                - Temperature T used
%     .calibrated_probabilities   - [1xK] temperature-scaled probability vector
%     .max_calibrated_probability - Highest class probability
%     .confidence_margin          - Gap between top 1 and top 2 class
%     .shannon_entropy            - Normalized Shannon entropy [0, 1]
%     .is_uncertain               - (logical) True if uncertainty flag raised
%
% Copyright (c) 2026 RetinaShield Research Project

    arguments
        rawScores (1,:) double
        options.Temperature (1,1) double = 1.0
        options.IsFitted (1,1) logical = false
        options.MinConfidence (1,1) double = 0.65
        options.MinMargin (1,1) double = 0.15
        options.MaxEntropy (1,1) double = 0.60
    end

    result = struct();
    numClasses = numel(rawScores);

    if numClasses == 0 || all(rawScores == 0)
        result.status = 'fallback_uniform';
        result.temperature = NaN;
        result.calibrated_probabilities = ones(1, 5) / 5;
        result.max_calibrated_probability = 0.20;
        result.confidence_margin = 0.0;
        result.shannon_entropy = 1.0;
        result.is_uncertain = true;
        return;
    end

    % 1. Convert raw probabilities to pseudo-logits via log transform
    epsVal = 1e-12;
    clamped = max(epsVal, min(1.0 - epsVal, rawScores));
    logits = log(clamped);

    % 2. Temperature scaling
    T = max(1e-4, options.Temperature);
    scaledLogits = logits / T;
    
    % Softmax computation with numerical stabilization
    maxLogit = max(scaledLogits);
    expScores = exp(scaledLogits - maxLogit);
    calProbs = expScores / sum(expScores);

    % 3. Uncertainty Indicators
    sortedProbs = sort(calProbs, 'descend');
    maxProb = sortedProbs(1);
    secondProb = 0.0;
    if numClasses > 1
        secondProb = sortedProbs(2);
    end
    margin = maxProb - secondProb;

    % Normalized Shannon Entropy: H = -sum(p * log(p)) / log(K)
    rawEntropy = -sum(calProbs .* log(max(epsVal, calProbs)));
    maxEntropy = log(numClasses);
    normEntropy = rawEntropy / maxEntropy;

    isUncertain = (maxProb < options.MinConfidence) || ...
                  (margin < options.MinMargin) || ...
                  (normEntropy > options.MaxEntropy);

    % 4. Build output struct
    if options.IsFitted
        result.status = 'calibrated';
        result.temperature = T;
    else
        result.status = 'uncalibrated_raw_softmax';
        result.temperature = NaN;
    end

    result.calibrated_probabilities = calProbs;
    result.max_calibrated_probability = round(maxProb, 4);
    result.confidence_margin = round(margin, 4);
    result.shannon_entropy = round(normEntropy, 4);
    result.is_uncertain = isUncertain;
end
