import cv2
import pytesseract
import os

# Path to Tesseract executable
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Image Paths
KITCHEN_IMG = r'Input_data\Rumyantsevo\kitchen.jpeg'
BATHROOM_IMG = r'Input_data\Rumyantsevo\bacthroom.jpeg' 

def get_counter_value(image_path, side='left'):
    """Extracts numeric value from a specific side of the photo."""
    if not os.path.exists(image_path):
        print(f"Warning: File not found {image_path}")
        return "N/A"

    img = cv2.imread(image_path)
    if img is None:
        print(f"Error: Could not read image {image_path}")
        return "ERROR"

    height, width, _ = img.shape
    
    # Crop logic: Splitting the image into left and right halves.
    if side == 'left':
        roi = img[0:height, 0:width//2]
    else:
        roi = img[0:height, width//2:width]

    # Preprocessing
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    
    # Tesseract configuration
    custom_config = r'--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789'
    
    try:
        text = pytesseract.image_to_string(thresh, config=custom_config)
        clean_val = "".join(filter(str.isdigit, text))
        return clean_val if clean_val else "0"
    except Exception as e:
        return f"OCR_ERROR: {e}"

def main():
    print("--- Testing OCR Extraction ---")
    
    images = [
        ("Kitchen", KITCHEN_IMG),
        ("Bathroom", BATHROOM_IMG)
    ]
    
    for name, path in images:
        print(f"\nProcessing {name} ({path}):")
        left = get_counter_value(path, 'left')
        right = get_counter_value(path, 'right')
        print(f"  Result -> Left: {left}, Right: {right}")

if __name__ == "__main__":
    main()
