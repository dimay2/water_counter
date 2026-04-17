import cv2
import pytesseract
import os
import numpy as np

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def extract_meter_values(image_path, prefix):
    """Detects circles, saves debug images, and extracts digits."""
    if not os.path.exists(image_path):
        return "N/A", "N/A"

    img = cv2.imread(image_path)
    if img is None: return "ERROR", "ERROR"

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.medianBlur(gray, 5)
    
    # Debug: Save blurred grayscale
    cv2.imwrite(f"debug_{prefix}_1_gray.jpg", blurred)

    circles = cv2.HoughCircles(
        blurred, 
        cv2.HOUGH_GRADIENT, 1, minDist=img.shape[1]//4,
        param1=50, param2=35, # Increased param2 slightly for less noise
        minRadius=img.shape[1]//10, maxRadius=img.shape[1]//3
    )

    detected_values = []

    if circles is not None:
        circles = np.uint16(np.around(circles))
        sorted_circles = sorted(circles[0, :], key=lambda x: x[0])

        for i, circle in enumerate(sorted_circles[:2]):
            x, y, r = map(int, circle)
            
            # Draw circle on a copy for debug
            debug_img = img.copy()
            cv2.circle(debug_img, (x, y), r, (0, 255, 0), 2)
            cv2.imwrite(f"debug_{prefix}_{i}_circle.jpg", debug_img)

            # Crop ROI (slightly adjusted for digit placement)
            roi_h = int(r * 0.4)
            roi_w = int(r * 1.2)
            y_start, y_end = max(0, y - roi_h), min(img.shape[0], y + roi_h)
            x_start, x_end = max(0, x - roi_w//2), min(img.shape[1], x + roi_w//2)
            
            roi = gray[y_start:y_end, x_start:x_end]
            if roi.size == 0: continue

            # Preprocessing for OCR
            thresh = cv2.adaptiveThreshold(roi, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                          cv2.THRESH_BINARY, 11, 2)
            cv2.imwrite(f"debug_{prefix}_{i}_roi.jpg", thresh)

            custom_config = r'--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789'
            text = pytesseract.image_to_string(thresh, config=custom_config)
            clean_val = "".join(filter(str.isdigit, text))
            detected_values.append(clean_val if clean_val else "0")

    while len(detected_values) < 2:
        detected_values.append("0")
    
    return detected_values[0], detected_values[1]

def main():
    print("--- Debugging OCR Extraction ---")
    paths = [("kitchen", r'Input_data\Rumyantsevo\kitchen.jpeg'), 
             ("bathroom", r'Input_data\Rumyantsevo\bacthroom.jpeg')]
    
    for prefix, path in paths:
        print(f"\nProcessing {prefix}...")
        l, r = extract_meter_values(path, prefix)
        print(f"  Results -> Left: {l}, Right: {r}")
    print("\nDebug images saved to current directory.")

if __name__ == "__main__":
    main()
