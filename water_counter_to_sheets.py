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
        
        # Sync previous readings from GSheet into ingestion_data proactively
        today_date_str = datetime.now().strftime("%d/%m/%Y")
        
        if profile["meter_logic"] == "color_coded":
            # Tashkentskiy
            red_reading = get_last_readings(profile["spreadsheet_id"], profile["sheet_gid"], meter_idx=5)
            blue_reading = get_last_readings(profile["spreadsheet_id"], profile["sheet_gid"], meter_idx=6)
            
            loc_data = ingestion_data.setdefault(location, {})
            room_data = loc_data.setdefault("all", {})
            
            if red_reading and red_reading[0] != today_date_str:
                room_data["prev_left"] = int(float(red_reading[1]))
            if blue_reading and blue_reading[0] != today_date_str:
                room_data["prev_right"] = int(float(blue_reading[1]))
            
            save_ingestion_data(ingestion_data)
        else:
            # Rumyantsevo
            from gsheet_uploader import get_previous_meter_readings_for_rumyantsevo_meters
            fetched_prev_vals = get_previous_meter_readings_for_rumyantsevo_meters(
                profile["spreadsheet_id"], profile["sheet_gid"], profile["columns"]
            )
            if fetched_prev_vals:
                loc_data = ingestion_data.setdefault(location, {})
                for room in ["kitchen", "bathroom"]:
                    room_data = loc_data.setdefault(room, {})
                    # Only update if current data in ingestion_data is NOT for today
                    if room_data.get("date") != datetime.now().strftime("%Y%m%d"):
                        room_data["prev_left"] = fetched_prev_vals[room]["prev_left"]
                        room_data["prev_right"] = fetched_prev_vals[room]["prev_right"]
                save_ingestion_data(ingestion_data)

        # Reload ingestion_data after sync
        ingestion_data = load_ingestion_data()

        # 2. Extract Meters
        img_dir = os.path.join('Input_data', location)
        img_files = [os.path.join(img_dir, f) for f in os.listdir(img_dir) if f.lower().endswith(('.jpeg', '.jpg', '.png'))]
        
        results_list = []
        try:
            if profile["meter_logic"] == "color_coded":
                # For Tashkentskiy: F=5 (Red), G=6 (Blue)
                
                # Use the synced values from ingestion_data
                room_data = ingestion_data.get(location, {}).get("all", {})
                prev_left = room_data.get("prev_left", 0)
                prev_right = room_data.get("prev_right", 0)
                
                # Force refresh for Tashkentskiy
                force_refresh = True
                today = datetime.now().strftime("%Y%m%d")

                final_left, final_right = 0, 0
                
                for img_file in img_files:
                    logger.info(f"Processing meter image: {img_file}")
                    is_red = "red" in img_file.lower()
                    
                    cur_prev_val = prev_left if is_red else prev_right
                    
                    # Re-fetch specific readings to get dates if needed for prompts
                    red_reading = get_last_readings(profile["spreadsheet_id"], profile["sheet_gid"], meter_idx=5) or (None, 0)
                    blue_reading = get_last_readings(profile["spreadsheet_id"], profile["sheet_gid"], meter_idx=6) or (None, 0)
                    raw_reading = red_reading if is_red else blue_reading
                    prev_date = raw_reading[0] if raw_reading else None

                    logger.info(f"Location: {location}, Date: {prev_date}, Previous Reading: {cur_prev_val}")

                    res = extract_room_meters(location, "all", img_file, client, profiles, logic="color_coded", 
                                           prev_date=prev_date,
                                           prev_val=cur_prev_val,
                                           use_cache=not force_refresh)
                    
                    logger.info(f"{'Red' if is_red else 'Blue'} meter reading = {res['left'] if is_red else res['right']}")
                    final_left += res["left"]
                    final_right += res["right"]
                
                results_list = [final_left, final_right]

                # Update ingestion_data with final results
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

            else:
                # Rumyantsevo: B=1 (K_L), C=2 (K_R), D=3 (B_L), E=4 (B_R)
                loc_data = ingestion_data.get(location, {})
                k_data = loc_data.get("kitchen", {})
                b_data = loc_data.get("bathroom", {})

                pk_l = k_data.get("prev_left", 0)
                pk_r = k_data.get("prev_right", 0)
                pb_l = b_data.get("prev_left", 0)
                pb_r = b_data.get("prev_right", 0)

                k_img = os.path.join(img_dir, "kitchen.jpeg")
                b_img = os.path.join(img_dir, "bathroom.jpeg")
                
                kitchen = extract_room_meters(location, "kitchen", k_img, client, profiles, prev_val=(pk_l, pk_r))
                bathroom = extract_room_meters(location, "bathroom", b_img, client, profiles, prev_val=(pb_l, pb_r))
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
