import os
import logging
import json
from datetime import datetime
from dotenv import load_dotenv
from google import genai
from meter_extractor import extract_room_meters, process_location, load_ingestion_data, save_ingestion_data
from gsheet_uploader import update_or_append_gsheet, get_last_readings

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    logger.info("--- Water Counter Processor (Vision-Based) ---")
    client = genai.Client()
    
    with open('profiles.json', 'r', encoding='utf-8') as f:
        profiles = json.load(f)
        
    for location, profile in profiles.items():
        logger.info(f"--- Processing Location: {location} ---")
        
        # 1. Process PDF
        process_location(location, client, profiles)
        ingestion_data = load_ingestion_data()
        
        # Get last readings from GSheet for validation
        prev_readings = get_last_readings(profile["spreadsheet_id"], profile["sheet_gid"])
        
        # 2. Extract Meters
        img_dir = os.path.join('Input_data', location)
        img_files = [os.path.join(img_dir, f) for f in os.listdir(img_dir) if f.lower().endswith(('.jpeg', '.jpg', '.png'))]
        
        results_list = []
        try:
            if profile["meter_logic"] == "color_coded":
                # For Tashkentskiy: F=5 (Red), G=6 (Blue)
                meter_idx_map = [5, 6] 
                
                # Fetch last readings for each meter
                red_reading = get_last_readings(profile["spreadsheet_id"], profile["sheet_gid"], meter_idx=5) or (None, 0)
                blue_reading = get_last_readings(profile["spreadsheet_id"], profile["sheet_gid"], meter_idx=6) or (None, 0)
                
                # Force refresh for Tashkentskiy
                force_refresh = True
                today = datetime.now().strftime("%Y%m%d")

                final_left, final_right = 0, 0
                prev_left, prev_right = 0, 0
                
                for img_file in img_files:
                    logger.info(f"Processing meter image: {img_file}")
                    is_red = "red" in img_file.lower()
                    
                    raw_reading = red_reading if is_red else blue_reading
                    if raw_reading:
                        prev_date, prev_val = raw_reading
                    else:
                        prev_date, prev_val = None, 0
                    
                    # Ensure prev_val is an integer (handle '973.0' case)
                    try:
                        prev_val = int(float(prev_val)) if prev_val else 0
                    except (ValueError, TypeError):
                        prev_val = 0
                    
                    if is_red: prev_left = prev_val
                    else: prev_right = prev_val
                    
                    logger.info(f"Location: {location}, Date: {prev_date}, Previous Reading: {prev_val}")

                    res = extract_room_meters(location, "all", img_file, client, profiles, logic="color_coded", 
                                           prev_date=prev_date,
                                           prev_val=prev_val,
                                           use_cache=not force_refresh)
                    
                    logger.info(f"{'Red' if is_red else 'Blue'} meter reading = {res['left'] if is_red else res['right']}")
                    final_left += res["left"]
                    final_right += res["right"]
                
                results_list = [final_left, final_right]

                # After processing all images, update ingestion_data for Tashkentskiy.all
                loc_data = ingestion_data.setdefault(location, {})
                room_data = loc_data.setdefault("all", {})
                room_data.update({
                    "date": today,
                    "refresh": not (final_left > 0 and final_right > 0),
                    "left": final_left,
                    "right": final_right,
                    "prev_left": prev_left,
                    "prev_right": prev_right
                })
                save_ingestion_data(ingestion_data)

                # Check if we got zeros (this check is now redundant since extract_room_meters will raise an error if validation fails)
                # if results_list[0] == 0 and results_list[1] == 0:
                #     logger.warning(f"Detected 0 values for {location}. Setting refresh=true.")
                #     ingestion_data = load_ingestion_data()
                #     if "all" in ingestion_data.get(location, {}):
                #         ingestion_data[location]["all"]["refresh"] = True
                #         save_ingestion_data(ingestion_data)

            else:
                # Rumyantsevo: B=1 (K_L), C=2 (K_R), D=3 (B_L), E=4 (B_R)
                # prev_date not available for Rumyantsevo currently
                prev_date = None
                pk_l = int(prev_readings[1]) if prev_readings and len(prev_readings) > 1 and str(prev_readings[1]).strip().isdigit() else 0
                pk_r = int(prev_readings[2]) if prev_readings and len(prev_readings) > 2 and str(prev_readings[2]).strip().isdigit() else 0
                pb_l = int(prev_readings[3]) if prev_readings and len(prev_readings) > 3 and str(prev_readings[3]).strip().isdigit() else 0
                pb_r = int(prev_readings[4]) if prev_readings and len(prev_readings) > 4 and str(prev_readings[4]).strip().isdigit() else 0

                k_img = os.path.join(img_dir, "kitchen.jpeg")
                b_img = os.path.join(img_dir, "bacthroom.jpeg")
                
                kitchen = extract_room_meters(location, "kitchen", k_img, client, profiles, prev_date=prev_date, prev_val=(pk_l, pk_r))
                bathroom = extract_room_meters(location, "bathroom", b_img, client, profiles, prev_date=prev_date, prev_val=(pb_l, pb_r))
                results_list = [kitchen["left"], kitchen["right"], bathroom["left"], bathroom["right"]]

            # 3. Upload
            if ingestion_data.get(location, {}).get("refresh_pdf"):
                logger.error(f"Upload canceled for {location} due to PDF parsing requiring a refresh (missing or '0' values).")
                continue

            zero_indices = [i for i, val in enumerate(results_list) if val == 0]
            if zero_indices:
                logger.error(f"Upload canceled for {location} due to '0' values in extracted meter readings: {results_list}.")
                # Only flag refresh for extraction failure. Ignore previous left/right cache values.
                if location in ingestion_data:
                    for room_key, room_data in ingestion_data[location].items():
                        if isinstance(room_data, dict) and "refresh" in room_data:
                            room_data["refresh"] = True
                save_ingestion_data(ingestion_data)
                continue

            update_or_append_gsheet(
                profile["spreadsheet_id"], 
                profile["sheet_gid"], 
                location, 
                profile, 
                results_list, 
                ingestion_data=ingestion_data
            )
        except ValueError as ve:
            logger.error(f"Stopping processing for {location} due to validation error: {ve}")
            continue # Skip to next location

        logger.info(f"Processing complete for {location}")

if __name__ == "__main__":
    main()
