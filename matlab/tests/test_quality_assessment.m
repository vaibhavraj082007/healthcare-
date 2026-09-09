function tests = test_quality_assessment
    tests = functiontests(localfunctions);
end

function setupOnce(testCase)
    % Create a dummy fundus image for testing
    % We need something that passes the basic plausibility (circular mask, non-black)
    img = uint8(zeros(600, 800, 3));
    [X, Y] = meshgrid(1:800, 1:600);
    center = [400, 300];
    mask = sqrt((X - center(1)).^2 + (Y - center(2)).^2) < 250;
    
    % Fill with "retina-like" color and some texture
    for c = 1:3
        channel = img(:,:,c);
        if c == 1
            val = 150; % R
        elseif c == 2
            val = 70;  % G
        else
            val = 20;  % B
        end
        % Add random noise for focus metrics
        noise = uint8(randi([0, 30], 600, 800));
        channel(mask) = val + noise(mask);
        img(:,:,c) = channel;
    end
    
    testCase.TestData.baseImg = img;
    testCase.TestData.tempDir = tempname;
    mkdir(testCase.TestData.tempDir);
end

function teardownOnce(testCase)
    rmdir(testCase.TestData.tempDir, 's');
end

function test_acceptable_image(testCase)
    img = testCase.TestData.baseImg;
    imgPath = fullfile(testCase.TestData.tempDir, 'acceptable.jpg');
    imwrite(img, imgPath);
    
    res = quality_assessment(imgPath);
    verifyEqual(testCase, res.status, 'acceptable');
end

function test_underexposed(testCase)
    img = testCase.TestData.baseImg;
    img = img / 10; % Make it very dark
    imgPath = fullfile(testCase.TestData.tempDir, 'dark.jpg');
    imwrite(img, imgPath);
    
    res = quality_assessment(imgPath);
    verifyEqual(testCase, res.status, 'ungradeable');
    verifyTrue(testCase, any(strcmp(res.reason_codes, 'ERR_UNDEREXPOSED')));
end

function test_overexposed(testCase)
    img = testCase.TestData.baseImg;
    img = img + 200; % Make it very bright
    imgPath = fullfile(testCase.TestData.tempDir, 'bright.jpg');
    imwrite(img, imgPath);
    
    res = quality_assessment(imgPath);
    verifyEqual(testCase, res.status, 'ungradeable');
    verifyTrue(testCase, any(strcmp(res.reason_codes, 'ERR_OVEREXPOSED')));
end

function test_out_of_focus(testCase)
    img = testCase.TestData.baseImg;
    % Apply heavy gaussian blur
    img = imgaussfilt(img, 10);
    imgPath = fullfile(testCase.TestData.tempDir, 'blur.jpg');
    imwrite(img, imgPath);
    
    res = quality_assessment(imgPath);
    verifyEqual(testCase, res.status, 'ungradeable');
    verifyTrue(testCase, any(strcmp(res.reason_codes, 'ERR_OUT_OF_FOCUS')));
end

function test_clipped_edges(testCase)
    img = testCase.TestData.baseImg;
    % Shift the mask so it touches the border
    img(1:50, :, :) = 150; % Fake retina at the top edge
    imgPath = fullfile(testCase.TestData.tempDir, 'clipped.jpg');
    imwrite(img, imgPath);
    
    res = quality_assessment(imgPath);
    % Clipping alone usually downgrades to borderline
    verifyTrue(testCase, strcmp(res.status, 'borderline') || strcmp(res.status, 'ungradeable'));
    verifyTrue(testCase, any(strcmp(res.reason_codes, 'WARN_CLIPPED_EDGES')));
end

function test_blank_image(testCase)
    img = uint8(zeros(600, 800, 3));
    imgPath = fullfile(testCase.TestData.tempDir, 'blank.jpg');
    imwrite(img, imgPath);
    
    res = quality_assessment(imgPath);
    verifyEqual(testCase, res.status, 'ungradeable');
    verifyTrue(testCase, any(strcmp(res.reason_codes, 'ERR_NON_FUNDUS_OR_TINY')));
end

function test_low_resolution(testCase)
    img = imresize(testCase.TestData.baseImg, [200, 300]);
    imgPath = fullfile(testCase.TestData.tempDir, 'lowres.jpg');
    imwrite(img, imgPath);
    
    res = quality_assessment(imgPath);
    verifyEqual(testCase, res.status, 'ungradeable');
    verifyTrue(testCase, any(strcmp(res.reason_codes, 'ERR_LOW_RESOLUTION')));
end
