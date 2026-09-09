function tests = test_preprocessing
    tests = functiontests(localfunctions);
end

function setupOnce(testCase)
    % Create a dummy fundus image for testing
    img = uint8(zeros(600, 800, 3));
    [X, Y] = meshgrid(1:800, 1:600);
    center = [400, 300];
    mask = sqrt((X - center(1)).^2 + (Y - center(2)).^2) < 250;
    
    for c = 1:3
        channel = img(:,:,c);
        channel(mask) = randi([50, 200], sum(mask(:)), 1);
        img(:,:,c) = channel;
    end
    
    testCase.TestData.baseImg = img;
    testCase.TestData.tempDir = tempname;
    mkdir(testCase.TestData.tempDir);
    
    % Save image
    testCase.TestData.imgPath = fullfile(testCase.TestData.tempDir, 'dummy.png');
    imwrite(img, testCase.TestData.imgPath);
    
    % Dummy IQA result
    testCase.TestData.iqa = struct('status', 'acceptable', ...
        'reason_codes', {{}}, 'measurements', struct('illumination_cv', 0.1));
end

function teardownOnce(testCase)
    rmdir(testCase.TestData.tempDir, 's');
end

function test_geometry_tracking(testCase)
    outDir = fullfile(testCase.TestData.tempDir, 'out1');
    res = enhance_fundus(testCase.TestData.imgPath, outDir, testCase.TestData.iqa);
    
    % Original was 800x600 (W x H)
    % Target is 512x512
    % Scale should be min(512/600, 512/800) = 512/800 = 0.64
    
    verifyEqual(testCase, res.geometry.original_size, [600, 800]);
    verifyEqual(testCase, res.geometry.scale_factor, 0.64, 'RelTol', 0.01);
    
    % New size before pad = 0.64 * 600 = 384 height, 0.64 * 800 = 512 width
    % Padding should be top/bottom
    verifyEqual(testCase, res.geometry.pad_left, 0);
    verifyEqual(testCase, res.geometry.pad_right, 0);
    verifyEqual(testCase, res.geometry.pad_top + res.geometry.pad_bottom, 512 - 384);
    
    % Check inverse transform works correctly
    % center of target is 256, 256.
    % xt = 256 = x_orig * 0.64 + 0 => x_orig = 256 / 0.64 = 400
    p_t = [256; 256; 1];
    p_orig = res.geometry.transform_to_original * p_t;
    verifyEqual(testCase, p_orig(1), 400, 'RelTol', 0.01);
end

function test_conditional_clahe(testCase)
    outDir = fullfile(testCase.TestData.tempDir, 'out2');
    
    % IQA with perfect illumination (cv = 0.1) -> No CLAHE
    res1 = enhance_fundus(testCase.TestData.imgPath, outDir, testCase.TestData.iqa);
    verifyFalse(testCase, res1.parameters.clahe_applied);
    
    % IQA with poor illumination (cv = 0.8) -> CLAHE
    badIqa = testCase.TestData.iqa;
    badIqa.measurements.illumination_cv = 0.8;
    res2 = enhance_fundus(testCase.TestData.imgPath, outDir, badIqa);
    verifyTrue(testCase, res2.parameters.clahe_applied);
end

function test_intensity_range(testCase)
    outDir = fullfile(testCase.TestData.tempDir, 'out3');
    res = enhance_fundus(testCase.TestData.imgPath, outDir, testCase.TestData.iqa);
    
    enhImg = imread(res.enhanced_image_path);
    minVal = min(enhImg(:));
    maxVal = max(enhImg(:));
    
    % Should stay within 0-255 uint8 range without crashing/overflow
    verifyGreaterThanOrEqual(testCase, minVal, 0);
    verifyLessThanOrEqual(testCase, maxVal, 255);
end

function test_reproducibility(testCase)
    outDir = fullfile(testCase.TestData.tempDir, 'out4');
    res1 = enhance_fundus(testCase.TestData.imgPath, outDir, testCase.TestData.iqa);
    res2 = enhance_fundus(testCase.TestData.imgPath, outDir, testCase.TestData.iqa);
    
    % Read both and compare
    img1 = imread(res1.enhanced_image_path);
    img2 = imread(res2.enhanced_image_path);
    verifyEqual(testCase, img1, img2);
end
