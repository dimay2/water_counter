import os
import json
import logging
from datetime import datetime
from PIL import Image
from pydantic import BaseModel
from pdf_extractor import parse_rumyantsevo_pdf
from gemini_utils import call_gemini_with_retry

# Configure logging
logger = logging.getLogger(__name__)

MODELS_CACHE_FILE = 'working_models.json'
DATA_INGESTION_FILE = 'data_for_ingestion.json'

class MeterReadings(BaseModel):
    meter_1: str
    meter_2: str

_CACHED_MODELS_TO_TRY = None

def load_cached_models():
    if os.path.exists(MODELS_CACHE_FILE):
        try:
            with open(MODELS_CACHE_FILE, 'r') as f:
                models = json.load(f)
                if isinstance(models, list) and len(models) > 0:
                    return models
        except Exception as e:
            logger.warning(f"Could not read {MODELS_CACHE_FILE}: {e}")
    return []

def save_ingestion_data(data):
    try:
        with open(DATA_INGESTION_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.warning(f"Could not write {DATA_INGESTION_FILE}: {e}")

def load_ingestion_data():
    if os.path.exists(DATA_INGESTION_FILE):
        try:
            with open(DATA_INGESTION_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read {DATA_INGESTION_FILE}: {e}")
    return {}

def process_location(location: str, client):
    ingestion_data = load_ingestion_data()
    pdf_dir = os.path.join('Input_data', location)
    
    global _CACHED_MODELS_TO_TRY
    if _CACHED_MODELS_TO_TRY is None:
        _CACHED_MODELS_TO_TRY = load_cached_models()
    model_name = _CACHED_MODELS_TO_TRY[0]

    if os.path.exists(pdf_dir):
        loc_data = ingestion_data.setdefault(location, {})
        # Check if we should skip parsing: only parse if refresh_pdf is explicitly true
        if loc_data.get("refresh_pdf") is not True:
            logger.info(f"PDF data for {location} is already up to date. Skipping parsing.")
            return

        required_fields = [
            "Содержание и техническое обслуживание помещений",
            "Обращение с ТКО",
            "Холодное водоснабжение",
            "Холодная вода для ГВС",
            "Теплоэнергия для ГВС",
            "Водоотведение",
            "Отопление",
            "Охрана и мониторинг ЖК",
            "Электроснабжение для СОИ:"
        ]
        for filename in os.listdir(pdf_dir):
            if filename.lower().endswith('.pdf'):
                pdf_path = os.path.join(pdf_dir, filename)
                logger.info(f"Processing PDF: {pdf_path}")
                pdf_data = parse_rumyantsevo_pdf(pdf_path, client, model_name)
                
                if pdf_data is None:
                    logger.error(f"PDF extraction failed for {filename}. Skipping upload.")
                    continue

                # Verify all fields present
                missing = [f for f in required_fields if f not in pdf_data]
                if missing:
                    logger.error(f"Missing fields in PDF extraction: {missing}")
                    loc_data["refresh_pdf"] = True
                else:
                    loc_data.update(pdf_data)
                    loc_data["refresh_pdf"] = False
                
                save_ingestion_data(ingestion_data)
                logger.info(f"Updated ingestion data for {location} from {filename}")
def extract_room_meters(location: str, room: str, img_path: str, client) -> dict:
    if not os.path.exists(img_path):
        logger.error(f"Image not found: {img_path}")
        return {"left": 0, "right": 0}

    ingestion_data = load_ingestion_data()
    room_data = ingestion_data.get(location, {}).get(room, {})

    today = datetime.now().strftime("%Y%m%d")

    # Check if we already have data for today's date
    if room_data.get("date") == today and not room_data.get("refresh", False):
        logger.info(f"Cache hit for {location}.{room} on {today}. Skipping extraction.")
        return {"left": room_data.get("left", 0), "right": room_data.get("right", 0)}

    logger.info(f"Processing {location} {room} meters for {today}...")

    global _CACHED_MODELS_TO_TRY
    if _CACHED_MODELS_TO_TRY is None:
        _CACHED_MODELS_TO_TRY = load_cached_models()

    model_name = _CACHED_MODELS_TO_TRY[0]
    img = Image.open(img_path)
    prompt = "Extract both meters from image. Return as JSON: {'meter_1': 'left_value', 'meter_2': 'right_value'}."

    try:
        response = call_gemini_with_retry(client, model_name, img, prompt, response_schema=MeterReadings)
        data = json.loads(response.text)

        def parse(val):
            digits = "".join(filter(str.isdigit, val))
            return int(digits[:-3]) if len(digits) > 3 else 0

        left = parse(data.get("meter_1", "0"))
        right = parse(data.get("meter_2", "0"))

        # Save to cache with date
        ingestion_data.setdefault(location, {})[room] = {
            "date": today,
            "refresh": False,
            "left": left,
            "right": right
        }
        save_ingestion_data(ingestion_data)
        return {"left": left, "right": right}
    except Exception as e:
        logger.error(f"Error extracting {room}: {e}")
        return {"left": 0, "right": 0}
