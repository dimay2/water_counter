import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from meter_extractor import extract_room_meters
from gsheet_uploader import update_or_append_gsheet

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID') or '127KX8icaYG03o5WVvnHWcXjxCxlR5s5lBMY4Gl1lSPY'
SHEET_GID = int(os.getenv('SHEET_GID') if os.getenv('SHEET_GID') else 455004741)
KITCHEN_IMG = r'Input_data\Rumyantsevo\kitchen.jpeg'
BATHROOM_IMG = r'Input_data\Rumyantsevo\bacthroom.jpeg'

def main():
    logger.info("--- Water Counter Processor (Vision-Based) ---")
    
    location = "Rumyantsevo"
    
    # Process Rooms
    kitchen = extract_room_meters(location, "kitchen", KITCHEN_IMG)
    bathroom = extract_room_meters(location, "bathroom", BATHROOM_IMG)

    results = {
        "k_left": kitchen["left"],
        "k_right": kitchen["right"],
        "b_left": bathroom["left"],
        "b_right": bathroom["right"]
    }

    # Validation
    if any(val == 0 for val in results.values()):
        logger.warning("Extraction failed (one or more values are 0).")

    # Upload
    # Row A=Date, B=Kitchen Left, C=Kitchen Right, D=Bathroom Left, E=Bathroom Right
    new_row = [
        "", 
        results["k_left"], 
        results["k_right"], 
        results["b_left"], 
        results["b_right"]
    ]
    
    update_or_append_gsheet(SPREADSHEET_ID, SHEET_GID, new_row)

if __name__ == "__main__":
    main()
