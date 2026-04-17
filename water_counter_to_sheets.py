import gspread
import google.auth
import os
import traceback
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel
from PIL import Image

# Load environment variables for Gemini
load_dotenv()

# --- CONFIGURATION ---
SPREADSHEET_ID = '127KX8icaYG03o5WVvnHWcXjxCxlR5s5lBMY4Gl1lSPY'
SHEET_GID = 455004741

KITCHEN_IMG = r'Input_data\Rumyantsevo\kitchen.jpeg'
BATHROOM_IMG = r'Input_data\Rumyantsevo\bacthroom.jpeg'

class MeterReadings(BaseModel):
    meter_1: int
    meter_2: int

def extract_numbers_from_meter(img_path):
    """
    Extracts white-on-black digits from water meters using Gemini.
    Returns a list of values found.
    """
    if not os.path.exists(img_path):
        return []

    try:
        client = genai.Client()
        img = Image.open(img_path)
        
        prompt = "Extract the numbers from the two water meters in this image. Only provide the digits on the BLACK background. Return them as meter_1 (top or left) and meter_2 (bottom or right)."
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[img, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=MeterReadings,
                temperature=0.1
            )
        )
        
        data = json.loads(response.text)
        return [data.get("meter_1", 0), data.get("meter_2", 0)]
    except Exception as e:
        print(f"Error extracting from {img_path}: {e}")
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
