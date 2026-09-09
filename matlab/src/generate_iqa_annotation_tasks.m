function generate_iqa_annotation_tasks(resultsJsonPath, outputDir)
% GENERATE_IQA_ANNOTATION_TASKS Batch borderline/ungradeable images for expert review.
%
% This script parses a batch of IQA results (e.g., from a pipeline run),
% extracts the images marked as 'borderline' or 'ungradeable' by the
% heuristic logic, and copies them to an annotation directory along with a
% CSV file. Experts can then label these images to help tune the heuristics.
%
% USAGE:
%   generate_iqa_annotation_tasks('path/to/results.json', 'path/to/annotation_dir/')

    if ~isfolder(outputDir)
        mkdir(outputDir);
    end
    
    % Read JSON (Assuming an array of results or a single result for now)
    fid = fopen(resultsJsonPath, 'r');
    raw = fread(fid, '*char')';
    fclose(fid);
    
    try
        data = jsondecode(raw);
    catch
        error('generate_iqa:invalidJson', 'Could not parse JSON file.');
    end
    
    % Ensure data is array
    if ~iscell(data) && ~isvector(data)
        data = {data};
    elseif isvector(data) && ~iscell(data)
        % struct array to cell array for uniform processing
        data = num2cell(data);
    end
    
    csvPath = fullfile(outputDir, 'iqa_annotation_task.csv');
    fidCsv = fopen(csvPath, 'w');
    fprintf(fidCsv, 'image_id,heuristic_status,reason_codes,expert_status_label,expert_notes\n');
    
    copiedCount = 0;
    
    for i = 1:length(data)
        res = data{i};
        if isfield(res, 'quality_assessment')
            iqa = res.quality_assessment;
            
            if isfield(iqa, 'is_heuristic') && iqa.is_heuristic && ...
               isfield(iqa, 'status') && ...
               (strcmp(iqa.status, 'borderline') || strcmp(iqa.status, 'ungradeable'))
                
                % We need the original image path. Assuming it's in the struct or 
                % we use the analysis ID to name it.
                if isfield(res, 'analysis_id')
                    imgId = res.analysis_id;
                else
                    imgId = sprintf('img_%d', i);
                end
                
                reasonStr = strjoin(iqa.reason_codes, ';');
                fprintf(fidCsv, '%s,%s,%s,,\n', imgId, iqa.status, reasonStr);
                copiedCount = copiedCount + 1;
            end
        end
    end
    
    fclose(fidCsv);
    fprintf('Generated annotation task with %d images at %s\n', copiedCount, outputDir);
end
