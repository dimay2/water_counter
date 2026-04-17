import cv2
import pytesseract
import os
import numpy as np

# Path to Tesseract executable
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def extract_meter_values(image_path):
    """Detects circles (meters) and extracts digits from them."""
    if not os.path.exists(image_path):
        return "N/A", "N/A"

    img = cv2.imread(image_path)
    if img is None:
        return "ERROR", "ERROR"

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 1. Detect Circles (Water Meters)
    # Param1/Param2 adjust sensitivity. MinDist ensures we don't pick up the same meter twice.
    circles = cv2.HoughCircles(
        cv2.medianBlur(gray, 5), 
        cv2.HOUGH_GRADIENT, 1, minDist=img.shape[1]//4,
        param1=50, param2=30, minRadius=img.shape[1]//10, maxRadius=img.shape[1]//3
    )

    detected_values = []

    if circles is not None:
        circles = np.uint16(np.around(circles))
        # Sort circles by X coordinate to identify Left vs Right
        sorted_circles = sorted(circles[0, :], key=lambda x: x[0])

        for i, circle in enumerate(sorted_circles[:2]):
            x, y, r = map(int, circle) # Ensure they are standard Python ints
            
            # 2. Crop around the detected circle
            # We take a square ROI inside the circle
            roi_size = int(r * 0.8)
            y_start, y_end = max(0, y - roi_size // 2), min(img.shape[0], y + roi_size // 2)
            x_start, x_end = max(0, x - roi_size // 2), min(img.shape[1], x + roi_size // 2)
            
            roi = gray[y_start:y_end, x_start:x_end]

            if roi.size == 0:
                detected_values.append("0")
                continue

            # 3. Enhance for OCR
            thresh = cv2.adaptiveThreshold(roi, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                          cv2.THRESH_BINARY, 11, 2)
            
            # 4. OCR
            custom_config = r'--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789'
            text = pytesseract.image_to_string(thresh, config=custom_config)
            clean_val = "".join(filter(str.isdigit, text))
            detected_values.append(clean_val if clean_val else "0")

    # Ensure we return two values (Left, Right)
    while len(detected_values) < 2:
        detected_values.append("0")
    
    return detected_values[0], detected_values[1]

def main():
    print("--- Testing Circular Meter Detection & OCR ---")
    
    paths = [
        ("Kitchen", r'Input_data\Rumyantsevo\kitchen.jpeg'),
        ("Bathroom", r'Input_data\Rumyantsevo\bacthroom.jpeg')
    ]
    
    for name, path in paths:
        print(f"\nScanning {name}...")
        left, right = extract_meter_values(path)
        print(f"  Detected -> Left: {left}, Right: {right}")

if __name__ == "__main__":
    main()
