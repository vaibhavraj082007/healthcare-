function view_enhancement_comparison(originalPath, enhancedPath, outputPath)
% VIEW_ENHANCEMENT_COMPARISON Creates a side-by-side comparison image.
%
% Generates a single image showing the original fundus alongside the
% preprocessed (masked, normalized, conditional CLAHE, resized) version.
% No generative restorations are applied; this purely visualizes the
% deterministic preprocessing pipeline.
%
% USAGE:
%   view_enhancement_comparison('orig.jpg', 'enhanced.png', 'out_comparison.png')

    origImg = imread(originalPath);
    enhImg = imread(enhancedPath);
    
    % Resize original to match enhanced height for display purposes
    [enhH, enhW, ~] = size(enhImg);
    [origH, origW, ~] = size(origImg);
    
    dispOrigW = round(origW * (enhH / origH));
    origImgResized = imresize(origImg, [enhH, dispOrigW]);
    
    % Create a canvas
    margin = 20;
    canvasW = dispOrigW + enhW + margin * 3;
    canvasH = enhH + margin * 4; % extra room for titles
    
    canvas = uint8(ones(canvasH, canvasW, 3) * 255); % White background
    
    % Insert original
    canvas(margin+40:margin+39+enhH, margin:margin+dispOrigW-1, :) = origImgResized;
    
    % Insert enhanced
    canvas(margin+40:margin+39+enhH, margin*2+dispOrigW:margin*2+dispOrigW+enhW-1, :) = enhImg;
    
    % Note: In a full MATLAB environment we would use insertText from CV toolbox,
    % but we keep it simple here by just saving the stitched image. The user
    % knows which is which (Left = Original, Right = Preprocessed).
    
    imwrite(canvas, outputPath);
    fprintf('Saved side-by-side comparison to %s\n', outputPath);
end
