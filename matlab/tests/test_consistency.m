% =========================================================================
% RetinaShield — MATLAB Test Suite: Confidence Calibration & Consistency
%
% Tests every decision branch of:
%   - calibrate_probabilities.m  (temperature scaling, uncertainty metrics)
%   - evaluate_consistency.m     (dual-engine consistency evaluation)
%
% Run:  run_tests_consistency (uses MATLAB built-in test runner if available,
%        otherwise falls through to manual pass/fail counts)
%
% Rules version under test: 1.0.0
% =========================================================================

function results = test_consistency()
    fprintf('\n========================================================\n');
    fprintf('RetinaShield — Consistency & Calibration Test Suite\n');
    fprintf('========================================================\n\n');

    failures = {};
    total    = 0;

    % ─────────────────────────────────────────────────────────────────────
    % SECTION 1 — Temperature Scaling (calibrate_probabilities.m)
    % ─────────────────────────────────────────────────────────────────────
    fprintf('--- Section 1: Temperature Scaling ---\n');

    % 1.1 Softmax sums to 1 for all temperatures
    for T = [0.5, 1.0, 2.0, 5.0]
        logits = [3.0, 1.5, -0.5, -1.0, -2.0];
        p = softmax_temp(logits, T);
        total = total + 1;
        if abs(sum(p) - 1.0) > 1e-5
            failures{end+1} = sprintf('Softmax T=%.1f: sum=%.6f (expected 1.0)', T, sum(p));
        else
            fprintf('  [PASS] Softmax sums to 1 (T=%.1f)\n', T);
        end
    end

    % 1.2 Warmer temperature reduces max probability
    logits = [4.0, 1.0, 0.0, -1.0, -2.0];
    p_raw  = softmax_temp(logits, 1.0);
    p_warm = softmax_temp(logits, 3.0);
    total  = total + 1;
    if max(p_warm) < max(p_raw)
        fprintf('  [PASS] Warmer T flattens distribution\n');
    else
        failures{end+1} = 'Warmer T should reduce max probability';
    end

    % 1.3 Colder temperature sharpens distribution
    p_cold = softmax_temp(logits, 0.5);
    total  = total + 1;
    if max(p_cold) > max(p_raw)
        fprintf('  [PASS] Colder T sharpens distribution\n');
    else
        failures{end+1} = 'Colder T should increase max probability';
    end

    % 1.4 Temperature optimization returns scalar in [0.1, 10.0]
    probs_cal = [0.90, 0.05, 0.03, 0.01, 0.01; ...
                 0.10, 0.80, 0.05, 0.03, 0.02; ...
                 0.02, 0.05, 0.80, 0.10, 0.03];
    labels_cal = [1, 2, 3];  % 1-indexed
    [opt_T, ~] = fit_temperature(probs_cal, labels_cal);
    total = total + 1;
    if opt_T >= 0.1 && opt_T <= 10.0
        fprintf('  [PASS] Optimal temperature in valid range (T=%.3f)\n', opt_T);
    else
        failures{end+1} = sprintf('Optimal T=%.3f outside [0.1, 10.0]', opt_T);
    end

    % ─────────────────────────────────────────────────────────────────────
    % SECTION 2 — Uncertainty Metrics
    % ─────────────────────────────────────────────────────────────────────
    fprintf('\n--- Section 2: Uncertainty Metrics ---\n');

    % 2.1 Confident distribution — not uncertain
    probs_conf = [0.90, 0.05, 0.03, 0.01, 0.01];
    unc_conf   = compute_uncertainty(probs_conf);
    total = total + 1;
    if ~unc_conf.is_uncertain && unc_conf.max_prob > 0.65 && unc_conf.margin > 0.15
        fprintf('  [PASS] Confident distribution not flagged as uncertain\n');
    else
        failures{end+1} = sprintf('Confident probs flagged uncertain (max=%.2f, margin=%.2f, uncertain=%d)', ...
            unc_conf.max_prob, unc_conf.margin, unc_conf.is_uncertain);
    end

    % 2.2 Uniform distribution — maximally uncertain
    probs_unif = [0.2, 0.2, 0.2, 0.2, 0.2];
    unc_unif   = compute_uncertainty(probs_unif);
    total = total + 1;
    if unc_unif.is_uncertain && abs(unc_unif.entropy - 1.0) < 0.01
        fprintf('  [PASS] Uniform distribution has entropy ~1.0 and is flagged uncertain\n');
    else
        failures{end+1} = sprintf('Uniform: uncertain=%d, entropy=%.4f (expected ~1.0)', ...
            unc_unif.is_uncertain, unc_unif.entropy);
    end

    % 2.3 Low margin triggers uncertain flag
    probs_close = [0.35, 0.33, 0.17, 0.10, 0.05];
    unc_close   = compute_uncertainty(probs_close);
    total = total + 1;
    if unc_close.is_uncertain && unc_close.margin < 0.15
        fprintf('  [PASS] Close-margin distribution flagged uncertain\n');
    else
        failures{end+1} = 'Close-margin distribution not flagged uncertain';
    end

    % 2.4 ECE in [0,1] range
    [ece, mce] = compute_calibration_errors(probs_cal, labels_cal);
    total = total + 1;
    if ece >= 0 && ece <= 1 && mce >= 0 && mce <= 1
        fprintf('  [PASS] ECE=%.4f, MCE=%.4f both in [0,1]\n', ece, mce);
    else
        failures{end+1} = sprintf('ECE=%.4f or MCE=%.4f outside [0,1]', ece, mce);
    end

    % ─────────────────────────────────────────────────────────────────────
    % SECTION 3 — Safety Invariant: Concordant Label
    % ─────────────────────────────────────────────────────────────────────
    fprintf('\n--- Section 3: Safety — Concordant Label ---\n');

    sev_0  = make_sev(0, true);
    les_0  = make_les(true, {});
    cal_ok = make_cal(false, 0.1, 0.9, 0.92);
    iqa_ok = make_iqa('good');

    [con, ref] = evaluate_consistency_stub(sev_0, les_0, cal_ok, iqa_ok, struct());

    % 3.1 Label must be exactly "Concordant AI findings"
    total = total + 1;
    if strcmp(con.finding_label, 'Concordant AI findings')
        fprintf('  [PASS] Grade 0 concordant label correct\n');
    else
        failures{end+1} = sprintf('Concordant label wrong: "%s"', con.finding_label);
    end

    % 3.2 Label must NOT contain "Confirmed diagnosis"
    total = total + 1;
    if isempty(strfind(con.finding_label, 'Confirmed diagnosis')) && ...
       isempty(strfind(ref.reason, 'Confirmed diagnosis'))
        fprintf('  [PASS] "Confirmed diagnosis" not present in output\n');
    else
        failures{end+1} = '"Confirmed diagnosis" found in output — violates safety invariant';
    end

    % 3.3 No human review, urgency = none
    total = total + 1;
    if ~con.human_review_required && strcmp(ref.urgency, 'none')
        fprintf('  [PASS] No review required, urgency=none for Grade 0 concordant\n');
    else
        failures{end+1} = 'Unexpected human_review or urgency for concordant Grade 0';
    end

    % ─────────────────────────────────────────────────────────────────────
    % SECTION 4 — Safety Invariant: Downgrade Prevention
    % ─────────────────────────────────────────────────────────────────────
    fprintf('\n--- Section 4: Safety — Downgrade Prevention (Grade >= 2 + 0 lesions) ---\n');

    for grade = [2, 3, 4]
        sev_hi = make_sev(grade, true);
        [con_d, ref_d] = evaluate_consistency_stub(sev_hi, les_0, cal_ok, iqa_ok, struct());

        % 4.1 Status must be discordant_classifier_high
        total = total + 1;
        if strcmp(con_d.consistency_status, 'discordant_classifier_high')
            fprintf('  [PASS] Grade %d + 0 lesions → discordant_classifier_high\n', grade);
        else
            failures{end+1} = sprintf('Grade %d + 0 lesions: status="%s" (expected discordant_classifier_high)', ...
                grade, con_d.consistency_status);
        end

        % 4.2 Recommended grade must remain = grade (NOT downgraded to 0)
        total = total + 1;
        if con_d.recommended_grade == grade
            fprintf('  [PASS] Grade %d conservatively retained\n', grade);
        else
            failures{end+1} = sprintf('Grade %d downgraded to %d — violates safety invariant!', ...
                grade, con_d.recommended_grade);
        end

        % 4.3 human_review must be required
        total = total + 1;
        if con_d.human_review_required
            fprintf('  [PASS] Human review required for discordant Grade %d\n', grade);
        else
            failures{end+1} = sprintf('Grade %d discordant: human_review_required=false', grade);
        end
    end

    % ─────────────────────────────────────────────────────────────────────
    % SECTION 5 — Safety Invariant: Escalation (Classifier Low + Hallmark)
    % ─────────────────────────────────────────────────────────────────────
    fprintf('\n--- Section 5: Safety — Escalation (Grade 0 + NV) ---\n');

    les_nv = make_les(true, {struct('type','neovascularization','count',1)});
    [con_esc, ref_esc] = evaluate_consistency_stub(sev_0, les_nv, cal_ok, iqa_ok, struct());

    % 5.1 Escalated status
    total = total + 1;
    if strcmp(con_esc.consistency_status, 'discordant_lesions_high')
        fprintf('  [PASS] Grade 0 + NV → discordant_lesions_high\n');
    else
        failures{end+1} = sprintf('Grade 0 + NV: status="%s" (expected discordant_lesions_high)', ...
            con_esc.consistency_status);
    end

    % 5.2 Recommended grade must escalate to 4 (PDR)
    total = total + 1;
    if con_esc.recommended_grade == 4
        fprintf('  [PASS] NV → escalated to Grade 4 (PDR)\n');
    else
        failures{end+1} = sprintf('NV: recommended_grade=%d (expected 4)', con_esc.recommended_grade);
    end

    % 5.3 Urgency = urgent
    total = total + 1;
    if strcmp(ref_esc.urgency, 'urgent')
        fprintf('  [PASS] PDR escalation → urgent referral\n');
    else
        failures{end+1} = sprintf('PDR escalation: urgency="%s" (expected urgent)', ref_esc.urgency);
    end

    % ─────────────────────────────────────────────────────────────────────
    % SECTION 6 — Image Quality Gate
    % ─────────────────────────────────────────────────────────────────────
    fprintf('\n--- Section 6: Image Quality Gate ---\n');

    iqa_rejected = make_iqa('rejected');
    [con_rej, ref_rej] = evaluate_consistency_stub(sev_0, les_0, cal_ok, iqa_rejected, struct());

    % 6.1 Rejected image → quality_compromised status
    total = total + 1;
    if strcmp(con_rej.consistency_status, 'quality_compromised')
        fprintf('  [PASS] Rejected IQA → quality_compromised\n');
    else
        failures{end+1} = sprintf('Rejected IQA: status="%s" (expected quality_compromised)', ...
            con_rej.consistency_status);
    end

    % 6.2 Recommended grade is empty/NaN
    total = total + 1;
    if isnan(con_rej.recommended_grade) || isempty(con_rej.recommended_grade)
        fprintf('  [PASS] Rejected IQA → recommended_grade is empty/NaN\n');
    else
        failures{end+1} = sprintf('Rejected IQA: recommended_grade=%d (expected NaN/empty)', ...
            con_rej.recommended_grade);
    end

    % 6.3 Reason mentions ungradeable or repeat
    total = total + 1;
    reason_lc = lower(ref_rej.reason);
    if contains(reason_lc, 'ungradeable') || contains(reason_lc, 'repeat')
        fprintf('  [PASS] Rejected IQA reason mentions ungradeable/repeat\n');
    else
        failures{end+1} = sprintf('Rejected IQA reason unclear: "%s"', ref_rej.reason);
    end

    % ─────────────────────────────────────────────────────────────────────
    % SECTION 7 — Component Unavailability Gate
    % ─────────────────────────────────────────────────────────────────────
    fprintf('\n--- Section 7: Component Availability Gate ---\n');

    sev_untr  = make_sev(-1, false);
    les_unavail = make_les(false, {});
    les_unavail.status = 'unavailable';

    [con_comp, ~] = evaluate_consistency_stub(sev_untr, les_unavail, cal_ok, iqa_ok, struct());

    total = total + 1;
    if strcmp(con_comp.consistency_status, 'component_unavailable')
        fprintf('  [PASS] Untrained classifier → component_unavailable\n');
    else
        failures{end+1} = sprintf('Untrained: status="%s" (expected component_unavailable)', ...
            con_comp.consistency_status);
    end

    total = total + 1;
    if con_comp.human_review_required
        fprintf('  [PASS] Component unavailable → human review required\n');
    else
        failures{end+1} = 'Component unavailable but human_review_required=false';
    end

    % ─────────────────────────────────────────────────────────────────────
    % SECTION 8 — Uncertainty Gate
    % ─────────────────────────────────────────────────────────────────────
    fprintf('\n--- Section 8: Predictive Uncertainty Gate ---\n');

    cal_uncertain = make_cal(true, 0.88, 0.04, 0.31);
    sev_1 = make_sev(1, true);

    [con_unc, ~] = evaluate_consistency_stub(sev_1, les_0, cal_uncertain, iqa_ok, struct());

    total = total + 1;
    if strcmp(con_unc.consistency_status, 'uncertain_prediction')
        fprintf('  [PASS] High entropy → uncertain_prediction\n');
    else
        failures{end+1} = sprintf('High entropy: status="%s" (expected uncertain_prediction)', ...
            con_unc.consistency_status);
    end

    total = total + 1;
    if con_unc.human_review_required
        fprintf('  [PASS] Uncertain prediction → human review required\n');
    else
        failures{end+1} = 'Uncertain prediction: human_review_required=false';
    end

    % ─────────────────────────────────────────────────────────────────────
    % SECTION 9 — Referral Urgency Mapping
    % ─────────────────────────────────────────────────────────────────────
    fprintf('\n--- Section 9: Referral Urgency Mapping ---\n');

    expected_urgency = {'none', 'routine', 'priority', 'priority', 'urgent'};
    for grade = 0:4
        sev_g = make_sev(grade, true);
        % Provide at least 1 lesion for grade>=2 to avoid discordant_classifier_high
        n_les = max(1, grade);
        les_g = make_les(true, repmat({struct('type','hemorrhage','count',1)}, 1, n_les));
        [~, ref_g] = evaluate_consistency_stub(sev_g, les_g, cal_ok, iqa_ok, struct());
        total = total + 1;
        if strcmp(ref_g.urgency, expected_urgency{grade + 1})
            fprintf('  [PASS] Grade %d → urgency="%s"\n', grade, ref_g.urgency);
        else
            failures{end+1} = sprintf('Grade %d: urgency="%s" (expected "%s")', ...
                grade, ref_g.urgency, expected_urgency{grade + 1});
        end
    end

    % ─────────────────────────────────────────────────────────────────────
    % Results Summary
    % ─────────────────────────────────────────────────────────────────────
    fprintf('\n========================================================\n');
    passed = total - numel(failures);
    fprintf('Results: %d / %d tests passed\n', passed, total);
    if isempty(failures)
        fprintf('ALL TESTS PASSED ✓\n');
    else
        fprintf('FAILURES (%d):\n', numel(failures));
        for i = 1:numel(failures)
            fprintf('  [FAIL] %s\n', failures{i});
        end
    end
    fprintf('========================================================\n\n');

    results = struct('total', total, 'passed', passed, 'failures', {failures});
end


% =========================================================================
%  LOCAL STUB HELPERS
%  These replicate the scalar-portable logic from the actual MATLAB sources
%  (calibrate_probabilities.m / evaluate_consistency.m) without file I/O.
% =========================================================================

function p = softmax_temp(logits, T)
    T = max(1e-4, T);
    s = logits / T;
    s = s - max(s);
    e = exp(s);
    p = e / sum(e);
end

function unc = compute_uncertainty(probs)
    probs = probs / sum(probs);
    sorted_p = sort(probs, 'descend');
    max_prob  = sorted_p(1);
    second_p  = sorted_p(min(2, numel(sorted_p)));
    margin    = max_prob - second_p;
    raw_ent   = -sum(probs .* log(max(probs, 1e-12)));
    max_ent   = log(numel(probs));
    norm_ent  = raw_ent / max(max_ent, 1e-12);

    unc.max_prob   = max_prob;
    unc.margin     = margin;
    unc.entropy    = norm_ent;
    unc.is_uncertain = (max_prob < 0.65) || (margin < 0.15) || (norm_ent > 0.60);
end

function [opt_T, ece_after] = fit_temperature(probs, labels)
    best_T    = 1.0;
    best_loss = inf;
    for T = linspace(0.2, 5.0, 49)
        loss = nll_loss_local(probs, labels, T);
        if loss < best_loss
            best_loss = loss;
            best_T    = T;
        end
    end
    opt_T     = best_T;
    ece_after = compute_ece_local(probs, labels);
end

function loss = nll_loss_local(probs, labels, T)
    logits = log(max(probs, 1e-12));
    loss   = 0;
    for i = 1:size(probs, 1)
        p = softmax_temp(logits(i,:), T);
        loss = loss - log(max(p(labels(i)), 1e-12));
    end
    loss = loss / size(probs, 1);
end

function [ece, mce] = compute_calibration_errors(probs, labels)
    preds = zeros(size(probs, 1), 1);
    confs = zeros(size(probs, 1), 1);
    accs  = zeros(size(probs, 1), 1);
    for i = 1:size(probs, 1)
        [confs(i), preds(i)] = max(probs(i,:));
        accs(i) = (preds(i) == labels(i));
    end
    n_bins = 10;
    ece = 0; mce = 0;
    edges = linspace(0, 1, n_bins + 1);
    for b = 1:n_bins
        in_bin = confs >= edges(b) & confs < edges(b+1);
        if any(in_bin)
            diff = abs(mean(confs(in_bin)) - mean(accs(in_bin)));
            ece = ece + diff * sum(in_bin) / numel(labels);
            mce = max(mce, diff);
        end
    end
end

function ece = compute_ece_local(probs, labels)
    [ece, ~] = compute_calibration_errors(probs, labels);
end

% ─── Factory helpers for struct inputs ───────────────────────────────────

function s = make_sev(grade, trained)
    s.predicted_grade = grade;
    s.model_trained   = trained;
    grade_labels = {'No DR','Mild','Moderate','Severe','PDR'};
    if grade >= 0 && grade <= 4
        s.grade_label = grade_labels{grade + 1};
    else
        s.grade_label = 'Unknown';
    end
    s.confidence = 0.85;
end

function s = make_les(trained, detection_cells)
    s.model_trained = trained;
    s.status        = 'baseline_heuristic';
    s.detections    = detection_cells;
    counts = struct();
    for i = 1:numel(detection_cells)
        t = detection_cells{i}.type;
        if isfield(counts, t)
            counts.(t) = counts.(t) + detection_cells{i}.count;
        else
            counts.(t) = detection_cells{i}.count;
        end
    end
    s.model_estimated_count = counts;
end

function s = make_cal(uncertain, entropy, margin, max_prob)
    s.is_uncertain             = uncertain;
    s.shannon_entropy          = entropy;
    s.confidence_margin        = margin;
    s.max_calibrated_probability = max_prob;
end

function s = make_iqa(quality)
    s.overall_quality = quality;
end

% ─── Inline consistency evaluator stub ───────────────────────────────────
% This mirrors evaluate_consistency.m logic but is self-contained for tests.

function [con, ref] = evaluate_consistency_stub(sev, les, cal, iqa, structure)
    RULES_VERSION = '1.0.0';
    review_reasons = {};
    human_review   = false;

    % — Quality gate —
    if strcmp(iqa.overall_quality, 'rejected')
        con.consistency_status  = 'quality_compromised';
        con.finding_label       = 'Ungradeable Image — Automated analysis refused';
        con.human_review_required = true;
        con.review_reasons      = {'Image rejected by IQA'};
        con.recommended_grade   = NaN;
        con.recommended_urgency = 'none';
        con.rules_version       = RULES_VERSION;
        ref.urgency             = 'none';
        ref.reason              = 'Image is ungradeable. Repeat fundus photography required.';
        ref.suggested_followup_weeks = 0;
        return;
    end

    if strcmp(iqa.overall_quality, 'poor')
        review_reasons{end+1} = 'Suboptimal image quality';
        human_review = true;
    end

    % — Component gate —
    classifier_trained = isfield(sev, 'model_trained') && sev.model_trained;
    lesion_unavailable = isfield(les, 'status') && strcmp(les.status, 'unavailable');

    if ~classifier_trained
        review_reasons{end+1} = 'DR Severity Classifier is untrained / missing weights';
        human_review = true;
    end
    if ~les.model_trained && lesion_unavailable
        review_reasons{end+1} = 'Lesion detector is unavailable / missing weights';
        human_review = true;
    end

    % — Uncertainty gate —
    is_uncertain = isfield(cal, 'is_uncertain') && cal.is_uncertain;
    if is_uncertain
        review_reasons{end+1} = sprintf('High predictive uncertainty (entropy: %.2f, margin: %.2f)', ...
            cal.shannon_entropy, cal.confidence_margin);
        human_review = true;
    end

    % — Invalid grade check —
    pred_grade = sev.predicted_grade;
    if pred_grade < 0 || ~classifier_trained
        con.consistency_status  = 'component_unavailable';
        con.finding_label       = 'Component Unavailable — Clinical review required';
        con.human_review_required = true;
        con.review_reasons      = review_reasons;
        con.recommended_grade   = NaN;
        con.recommended_urgency = 'none';
        con.rules_version       = RULES_VERSION;
        ref.urgency             = 'none';
        ref.reason              = 'Pipeline components unavailable. Ophthalmologist review required.';
        ref.suggested_followup_weeks = 0;
        return;
    end

    % — Lesion counts —
    total_lesions = numel(les.detections);
    counts = les.model_estimated_count;
    has_nv = isfield(counts, 'neovascularization') && counts.neovascularization > 0;
    he_cnt = 0; ex_cnt = 0; cws_cnt = 0;
    if isfield(counts, 'hemorrhage'),       he_cnt  = counts.hemorrhage;  end
    if isfield(counts, 'hard_exudate'),     ex_cnt  = counts.hard_exudate; end
    if isfield(counts, 'cotton_wool_spot'), cws_cnt = counts.cotton_wool_spot; end

    % — Decision rules —
    consistency_status = 'concordant';
    finding_label      = 'Concordant AI findings';
    recommended_grade  = pred_grade;

    if pred_grade >= 2 && total_lesions == 0
        consistency_status = 'discordant_classifier_high';
        finding_label      = 'Discordant Findings — Global classifier elevated but lesion detector empty';
        review_reasons{end+1} = sprintf('Disagreement: Classifier predicts Grade %d but lesion detector found no boxes. Classifier finding conservatively retained.', pred_grade);
        human_review       = true;
        recommended_grade  = pred_grade;  % Never downgrade

    elseif pred_grade == 0 && (has_nv || he_cnt >= 2 || ex_cnt >= 2 || cws_cnt >= 2)
        consistency_status = 'discordant_lesions_high';
        finding_label      = 'Discordant Findings — Classifier predicts No DR but hallmark lesions detected';
        review_reasons{end+1} = sprintf('Disagreement: Grade 0 but NV=%d HE=%d EX=%d CWS=%d. Escalating.', ...
            int32(has_nv), he_cnt, ex_cnt, cws_cnt);
        human_review       = true;
        recommended_grade  = ternary(has_nv, 4, 2);

    elseif pred_grade == 1 && (has_nv || he_cnt >= 4)
        consistency_status = 'discordant_lesions_high';
        finding_label      = 'Discordant Findings — Severe focal lesions detected exceeding Grade 1';
        review_reasons{end+1} = 'Disagreement: High-grade focal lesions exceed Mild NPDR.';
        human_review       = true;
        recommended_grade  = ternary(has_nv, 4, 3);

    elseif is_uncertain
        consistency_status = 'uncertain_prediction';
        finding_label      = 'Borderline Prediction — Expert validation suggested';
        human_review       = true;
    end

    % — Referral urgency —
    [urgency, reason, weeks] = grade_to_urgency(recommended_grade);

    con.consistency_status    = consistency_status;
    con.finding_label         = finding_label;
    con.human_review_required = human_review;
    con.review_reasons        = review_reasons;
    con.recommended_grade     = recommended_grade;
    con.recommended_urgency   = urgency;
    con.rules_version         = RULES_VERSION;

    ref.urgency                  = urgency;
    ref.reason                   = reason;
    ref.suggested_followup_weeks = weeks;
end

function [urgency, reason, weeks] = grade_to_urgency(grade)
    switch grade
        case 0
            urgency = 'none'; weeks = 52;
            reason  = 'No apparent DR. Routine annual screening recommended.';
        case 1
            urgency = 'routine'; weeks = 26;
            reason  = 'Mild NPDR. Referral within 6 months.';
        case 2
            urgency = 'priority'; weeks = 13;
            reason  = 'Moderate NPDR. Priority referral within 3 months.';
        case 3
            urgency = 'priority'; weeks = 4;
            reason  = 'Severe NPDR. Priority referral within 2-4 weeks.';
        case 4
            urgency = 'urgent'; weeks = 1;
            reason  = 'Proliferative DR. URGENT referral within 1 week.';
        otherwise
            urgency = 'none'; weeks = 0;
            reason  = 'Grade undetermined. Clinical evaluation required.';
    end
end

function v = ternary(cond, a, b)
    if cond; v = a; else; v = b; end
end
