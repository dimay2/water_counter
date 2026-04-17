import gspread
import google.auth
import os
import time
import traceback
import json
import logging
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel
from PIL import Image
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception

# Configure professional logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables for Gemini
load_dotenv()

# --- CONFIGURATION ---
SPREADSHEET_ID = '127KX8icaYG03o5WVvnHWcXjxCxlR5s5lBMY4Gl1lSPY'
SHEET_GID = 455004741

KITCHEN_IMG = r'Input_data\Rumyantsevo\kitchen.jpeg'
BATHROOM_IMG = r'Input_data\Rumyantsevo\bacthroom.jpeg'

class MeterReadings(BaseModel):
    meter_1: str
    meter_2: str

def is_503_error(exception: Exception) -> bool:
    return "503" in str(exception) or "UNAVAILABLE" in str(exception)

@retry(
    wait=wait_exponential(multiplier=2, min=2, max=10),
    stop=stop_after_attempt(4),
    retry=retry_if_exception(is_503_error),
    before_sleep=lambda retry_state: logger.warning(f"503 Error encountered. Retrying in {retry_state.next_action.sleep} seconds...")
)
def _call_gemini_with_retry(client, img, prompt, model_name):
    return client.models.generate_content(
        model=model_name,
        contents=[img, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=MeterReadings,
            temperature=0.1
        )
    )

def extract_numbers_from_meter(img_path):
    """
    Extracts all digits from water meters using Gemini and processes them
    (drops 3 rightmost digits and removes leading zeros).
    Returns a list of values found.
    """
    if not os.path.exists(img_path):
        logger.error(f"Image not found: {img_path}")
        return []

    client = genai.Client()
    img = Image.open(img_path)
    prompt = "Extract all digits from the two water meters in this image, including both the black and red background digits. Return them as meter_1 (top or left) and meter_2 (bottom or right) as strings, preserving all leading zeros."
    
    primary_model = 'gemini-2.5-flash'
    fallback_model = 'gemini-1.5-flash'

    def process_meter_string(m_str):
        if not m_str:
            return 0
        # Keep only digits (removes accidental decimals or spaces)
        digits = "".join(filter(str.isdigit, str(m_str)))
        # Drop the 3 rightmost digits
        if len(digits) > 3:
            digits = digits[:-3]
        else:
            return 0
        # Remove leading zeros and convert back to int
        digits = digits.lstrip('0')
        return int(digits) if digits else 0

    try:
        # Attempt extraction with the primary model
        response = _call_gemini_with_retry(client, img, prompt, primary_model)
        data = json.loads(response.text)
        return [process_meter_string(data.get("meter_1", "")), process_meter_string(data.get("meter_2", ""))]
    except Exception as e:
        if is_503_error(e):
            logger.warning(f"Primary model {primary_model} failed after retries. Falling back to {fallback_model} for {img_path}")
            try:
                response = _call_gemini_with_retry(client, img, prompt, fallback_model)
                data = json.loads(response.text)
                return [process_meter_string(data.get("meter_1", "")), process_meter_string(data.get("meter_2", ""))]
            except Exception as fallback_error:
                logger.error(f"Fallback model also failed: {fallback_error}")
                return []
        else:
            logger.error(f"Error extracting from {img_path}: {e}")
            return []

def main():
    print("--- Water Counter Processor (Vision-Based) ---")
    
    # Extract Bathroom values (3 and 4)
    print("Processing Bathroom image...")
    b_values = extract_numbers_from_meter(BATHROOM_IMG)
    # Fallback to 0 if not detected
    b_left = b_values[0] if len(b_values) > 0 else 0
    b_right = b_values[1] if len(b_values) > 1 else 0

    # Extract Kitchen values (1 and 2)
    print("Processing Kitchen image...")
    k_values = extract_numbers_from_meter(KITCHEN_IMG)
    k_left = k_values[0] if len(k_values) > 0 else 0
    k_right = k_values[1] if len(k_values) > 1 else 0

    print(f"\nFinal Results:")
    print(f"Kitchen: B={k_left}, C={k_right}")
    print(f"Bathroom: D={b_left}, E={b_right}")

    if k_left == 0 or k_right == 0 or b_left == 0 or b_right == 0:
        print("\nProper extraction failed (one or more values are 0). Exiting without uploading to Google Sheets.")
        return

    # 2. Authenticate and Upload
    try:
        print("\nConnecting to Google Sheets...")
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds, _ = google.auth.default(scopes=scopes)
        client = gspread.authorize(creds)
        
        # Connect directly to the specific sheet using its ID and GID
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        sheet = spreadsheet.get_worksheet_by_id(SHEET_GID)

        # Ingest: Col B, C, D, E (leaving A empty)
        new_row = ["", k_left, k_right, b_left, b_right]
        sheet.append_row(new_row, value_input_option='RAW')
        print("Success!")
        
    except Exception as e:
        print(f"Error occurred during upload: {type(e).__name__} - {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
