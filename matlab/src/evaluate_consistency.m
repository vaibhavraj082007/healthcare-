function [consistency, referral] = evaluate_consistency(result, options)
% EVALUATE_CONSISTENCY Conservative Dual-Engine Consistency Layer for RetinaShield.
%
% Compares:
%   1. Engine A: Global DR Classifier (EfficientNet-B0 + Temperature Scaling)
%   2. Engine B: Focal Lesion Analysis Branch (YOLOv8 / Candidate Baselines)
%   3. Image Quality Assessment (IQA status & metrics)
%   4. Component Availability
%
% CLINICAL SAFETY INVARIANTS:
%   - A softmax score alone is not clinical certainty.
%   - Do not use a simplistic lesion-count-to-grade rule or assume independent errors.
%   - Absence of detected lesions MUST NEVER downgrade a moderate/severe classifier prediction.
%   - Concordant findings are labeled 'Concordant AI findings', strictly never 'Confirmed diagnosis'.
%   - Flags disagreement, missing components, ungradeable quality, and high entropy for mandatory human review.
%
% USAGE:
%   [consistency, referral] = evaluate_consistency(analysisResult)
%
% Copyright (c) 2026 RetinaShield Research Project

    arguments
        result struct
        options.RulesVersion (1,1) string = "1.0.0"
    end

    rulesVersion = options.RulesVersion;
    reviewReasons = {};
    humanReviewRequired = false;

    consistency = struct();
    consistency.rules_version = char(rulesVersion);
    consistency.consistency_status = 'concordant';
    consistency.finding_label = 'Concordant AI findings';
    consistency.human_review_required = false;
    consistency.review_reasons = {};
    consistency.recommended_grade = NaN;
    consistency.recommended_urgency = 'none';

    referral = struct('urgency', 'none', 'reason', '', 'suggested_followup_weeks', 52);

    % --- 1. Component Availability Gate ---
    classifierTrained = false;
    if isfield(result, 'severity_classification') && isfield(result.severity_classification, 'model_trained')
        classifierTrained = result.severity_classification.model_trained;
    end

    lesionsAvailable = false;
    if isfield(result, 'lesion_detection')
        if isfield(result.lesion_detection, 'model_trained') && result.lesion_detection.model_trained
            lesionsAvailable = true;
        elseif isfield(result.lesion_detection, 'status') && ~strcmp(result.lesion_detection.status, 'unavailable')
            lesionsAvailable = true;
        end
    end

    if ~classifierTrained
        reviewReasons{end+1} = 'DR Severity Classifier is untrained / missing weights';
        humanReviewRequired = true;
    end
    if ~lesionsAvailable
        reviewReasons{end+1} = 'Lesion detector is unavailable / missing weights';
        humanReviewRequired = true;
    end

    % --- 2. Image Quality Gate ---
    qualityStatus = 'good';
    if isfield(result, 'quality_assessment') && isfield(result.quality_assessment, 'overall_quality')
        qualityStatus = result.quality_assessment.overall_quality;
    end

    if strcmp(qualityStatus, 'rejected') || strcmp(qualityStatus, 'ungradeable')
        reviewReasons{end+1} = 'Image rejected by IQA: severe blur, artifact, or out-of-focus aperture';
        consistency.consistency_status = 'quality_compromised';
        consistency.finding_label = 'Ungradeable Image — Automated analysis refused';
        consistency.human_review_required = true;
        consistency.review_reasons = reviewReasons;
        consistency.recommended_grade = NaN;
        consistency.recommended_urgency = 'none';

        referral.urgency = 'none';
        referral.reason = 'Image is ungradeable. Refusal of autonomous grading. Repeat fundus photography or in-person examination required.';
        referral.suggested_followup_weeks = 0;
        return;
    end

    if strcmp(qualityStatus, 'poor')
        reviewReasons{end+1} = 'Suboptimal image quality / illumination uniformity may compromise subtle lesion detection';
        humanReviewRequired = true;
    end

    % --- 3. Uncertainty Gate ---
    isUncertain = false;
    if isfield(result, 'confidence_calibration') && isfield(result.confidence_calibration, 'is_uncertain')
        isUncertain = result.confidence_calibration.is_uncertain;
    end
    if isUncertain
        reviewReasons{end+1} = 'High predictive uncertainty / borderline class separation';
        humanReviewRequired = true;
    end

    % --- 4. Evaluate Classifier Findings ---
    if ~classifierTrained || ~isfield(result, 'severity_classification') || result.severity_classification.predicted_grade < 0
        consistency.consistency_status = 'component_unavailable';
        consistency.finding_label = 'Component Unavailable — Clinical review required';
        consistency.human_review_required = true;
        consistency.review_reasons = reviewReasons;
        consistency.recommended_grade = NaN;
        consistency.recommended_urgency = 'none';

        referral.urgency = 'none';
        referral.reason = 'Model components untrained or unavailable. Mandatory in-person ophthalmological evaluation required.';
        referral.suggested_followup_weeks = 0;
        return;
    end

    predGrade = result.severity_classification.predicted_grade;

    % --- 5. Evaluate Lesion Findings ---
    totalLesions = 0;
    hasNV = false;
    heCount = 0;
    exCount = 0;
    cwsCount = 0;

    if isfield(result, 'lesion_detection')
        if isfield(result.lesion_detection, 'detections')
            totalLesions = numel(result.lesion_detection.detections);
            for i = 1:numel(result.lesion_detection.detections)
                lt = result.lesion_detection.detections(i).lesion_type;
                if strcmp(lt, 'neovascularization'), hasNV = true; end
                if strcmp(lt, 'hemorrhage'), heCount = heCount + 1; end
                if strcmp(lt, 'hard_exudate'), exCount = exCount + 1; end
                if strcmp(lt, 'cotton_wool_spot') || strcmp(lt, 'soft_exudate'), cwsCount = cwsCount + 1; end
            end
        end
        if isfield(result.lesion_detection, 'model_estimated_count')
            mec = result.lesion_detection.model_estimated_count;
            if isfield(mec, 'neovascularization') && mec.neovascularization > 0, hasNV = true; end
            if isfield(mec, 'hemorrhage'), heCount = max(heCount, mec.hemorrhage); end
            if isfield(mec, 'hard_exudate'), exCount = max(exCount, mec.hard_exudate); end
        end
    end

    % Macular involvement check
    maculaInvolved = false;
    if isfield(result, 'structure_analysis') && isfield(result.structure_analysis, 'macula')
        if isfield(result.structure_analysis.macula, 'detected') && result.structure_analysis.macula.detected
            if exCount > 0 && predGrade >= 1
                maculaInvolved = true;
            end
        end
    end

    % --- 6. Conservative Cross-Engine Decision Rules ---
    consistencyStatus = 'concordant';
    findingLabel = 'Concordant AI findings';
    recommendedGrade = predGrade;

    % RULE 6A: Classifier High (Grade >= 2), Lesions Zero -> DISCORDANT CLASSIFIER HIGH
    % SAFETY: Never downgrade disease severity when classifier predicts high grade
    if predGrade >= 2 && totalLesions == 0
        consistencyStatus = 'discordant_classifier_high';
        findingLabel = 'Discordant Findings — Global classifier elevated but lesion detector empty';
        reviewReasons{end+1} = sprintf('Disagreement: Classifier predicts Grade %d but lesion detector found no candidate boxes. Classifier finding conservatively retained.', predGrade);
        humanReviewRequired = true;
        recommendedGrade = predGrade; % Retain high grade

    % RULE 6B: Classifier Low (Grade 0), Hallmark Lesions Present -> DISCORDANT LESIONS HIGH
    % ESCALATION: Upgrade review priority if significant pathology was spotted by lesion branch
    elseif predGrade == 0 && (hasNV || heCount >= 2 || exCount >= 2 || cwsCount >= 2)
        consistencyStatus = 'discordant_lesions_high';
        findingLabel = 'Discordant Findings — Classifier predicts No DR but hallmark lesions detected';
        reviewReasons{end+1} = sprintf('Disagreement: Global classifier predicted Grade 0 (No DR), but focal lesions detected (NV: %d, HE: %d, EX: %d, CWS: %d). Escalating for review.', ...
                                       double(hasNV), heCount, exCount, cwsCount);
        humanReviewRequired = true;
        if hasNV
            recommendedGrade = 4;
        else
            recommendedGrade = 2;
        end

    % RULE 6C: Classifier Grade 1, High-Grade Lesions Present -> ESCALATE
    elseif predGrade == 1 && (hasNV || heCount >= 4)
        consistencyStatus = 'discordant_lesions_high';
        findingLabel = 'Discordant Findings — Severe focal lesions detected exceeding Grade 1';
        reviewReasons{end+1} = 'Disagreement: High-grade focal lesions exceed Mild NPDR classification.';
        humanReviewRequired = true;
        if hasNV
            recommendedGrade = 4;
        else
            recommendedGrade = 3;
        end

    % RULE 6D: Concordant Findings
    else
        if isUncertain
            consistencyStatus = 'uncertain_prediction';
            findingLabel = 'Borderline Prediction — Expert validation suggested';
            humanReviewRequired = true;
        else
            consistencyStatus = 'concordant';
            findingLabel = 'Concordant AI findings';
        end
    end

    % --- 7. Referral Recommendation Determination ---
    switch recommendedGrade
        case 0
            urgency = 'none';
            reason = 'No apparent diabetic retinopathy detected. Routine annual screening recommended.';
            weeks = 52;
        case 1
            urgency = 'routine';
            reason = 'Mild NPDR detected (microaneurysms only). Referral for ophthalmological evaluation within 6 months.';
            weeks = 26;
        case 2
            urgency = 'priority';
            reason = 'Moderate NPDR detected. Priority referral for ophthalmological evaluation within 3 months.';
            weeks = 13;
        case 3
            urgency = 'priority';
            reason = 'Severe NPDR detected (4-2-1 criteria). Priority referral to retina specialist within 2-4 weeks.';
            weeks = 4;
        case 4
            urgency = 'urgent';
            reason = 'Proliferative Diabetic Retinopathy (PDR) detected. URGENT referral to retina specialist within 1 week.';
            weeks = 1;
        otherwise
            urgency = 'none';
            reason = 'Grade undetermined. Clinical evaluation required.';
            weeks = 0;
    end

    if maculaInvolved
        reason = [reason, ' Macular involvement / exudate proximity suspected — consider OCT evaluation.'];
        if strcmp(urgency, 'routine') || strcmp(urgency, 'priority')
            urgency = 'urgent';
            weeks = min(weeks, 2);
        end
    end

    if ~isempty(reviewReasons)
        reason = [reason, sprintf(' [Human Review Flags: %s]', reviewReasons{1})];
    end

    consistency.consistency_status = consistencyStatus;
    consistency.finding_label = findingLabel;
    consistency.human_review_required = humanReviewRequired;
    consistency.review_reasons = reviewReasons;
    consistency.recommended_grade = recommendedGrade;
    consistency.recommended_urgency = urgency;

    referral.urgency = urgency;
    referral.reason = reason;
    referral.suggested_followup_weeks = weeks;
end
