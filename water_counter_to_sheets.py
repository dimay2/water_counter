import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from meter_extractor import extract_numbers_from_meter
from gsheet_uploader import upload_to_gsheet

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Suppress verbose INFO logs from underlying Google GenAI and HTTP libraries
logging.getLogger("google.genai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Constants
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID') or '127KX8icaYG03o5WVvnHWcXjxCxlR5s5lBMY4Gl1lSPY'
SHEET_GID = int(os.getenv('SHEET_GID') if os.getenv('SHEET_GID') else 455004741)
KITCHEN_IMG = r'Input_data\Rumyantsevo\kitchen.jpeg'
BATHROOM_IMG = r'Input_data\Rumyantsevo\bacthroom.jpeg'

def main():
    logger.info("--- Water Counter Processor (Vision-Based) ---")
    
    location = "Rumyantsevo"

    # Extraction
    meters = [
        {"name": "kitchen_left", "path": KITCHEN_IMG},
        {"name": "kitchen_right", "path": KITCHEN_IMG},
        {"name": "bathroom_left", "path": BATHROOM_IMG},
        {"name": "bathroom_right", "path": BATHROOM_IMG}
    ]

    results = {}
    for meter in meters:
        val, model = extract_numbers_from_meter(location, meter["name"], meter["path"])
        results[meter["name"]] = {"val": val, "model": model}
        logger.info(f"  {meter['name'].replace('_', ' ').title()}: {val} (via {model})")

    # Validation
    if any(res["val"] == 0 for res in results.values()):
        logger.warning("Extraction failed (one or more values are 0). Exiting.")
        return

    # Upload
    today_date = datetime.now().strftime("%Y-%m-%d")
    new_row = [
        today_date, 
        results["kitchen_left"]["val"], 
        results["kitchen_right"]["val"], 
        results["bathroom_left"]["val"], 
        results["bathroom_right"]["val"]
    ]
    
    upload_to_gsheet(SPREADSHEET_ID, SHEET_GID, new_row)

if __name__ == "__main__":
    main()
