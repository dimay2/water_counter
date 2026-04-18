import os
import json
import logging
from PIL import Image
from google import genai
from google.genai import types
from pydantic import BaseModel
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception, RetryError

# Configure logging
logger = logging.getLogger(__name__)

MODELS_CACHE_FILE = 'working_models.json'
DATA_INGESTION_FILE = 'data_for_ingestion.json'

# Suppress verbose library logs
logging.getLogger("google").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

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

def save_cached_models(models_list):
    try:
        with open(MODELS_CACHE_FILE, 'w') as f:
            json.dump(models_list, f, indent=4)
    except Exception as e:
        logger.warning(f"Could not write {MODELS_CACHE_FILE}: {e}")

def load_ingestion_data():
    if os.path.exists(DATA_INGESTION_FILE):
        try:
            with open(DATA_INGESTION_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read {DATA_INGESTION_FILE}: {e}")
    return {}

def save_ingestion_data(data):
    try:
        with open(DATA_INGESTION_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.warning(f"Could not write {DATA_INGESTION_FILE}: {e}")

def get_api_vision_models(client):
    valid_model_names = [m.name.replace("models/", "") for m in client.models.list()]
    preferred_order = ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.0-flash']
    return [m for m in preferred_order if m in valid_model_names]

def is_503_error(exception: Exception) -> bool:
    return "503" in str(exception) or "UNAVAILABLE" in str(exception)

@retry(
    wait=wait_exponential(multiplier=8, min=8, max=40),
    stop=stop_after_attempt(4),
    retry=retry_if_exception(is_503_error)
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

def extract_room_meters(location: str, room: str, img_path: str) -> dict:
    if not os.path.exists(img_path):
        logger.error(f"Image not found: {img_path}")
        return {"left": 0, "right": 0}

    ingestion_data = load_ingestion_data()
    room_data = ingestion_data.get(location, {}).get(room, {})
    
    if room_data and not room_data.get("refresh", False):
        logger.info(f"Cache hit for {location}.{room}. Using cached values.")
        return {"left": room_data.get("left", 0), "right": room_data.get("right", 0)}

    logger.info(f"Processing {location} {room} meters...")
    
    global _CACHED_MODELS_TO_TRY
    if _CACHED_MODELS_TO_TRY is None:
        _CACHED_MODELS_TO_TRY = load_cached_models()

    client = genai.Client()
    img = Image.open(img_path)
    prompt = "Extract both meters from image. Return as JSON: {'meter_1': 'left_value', 'meter_2': 'right_value'}."
    
    try:
        response = _call_gemini_with_retry(client, img, prompt, _CACHED_MODELS_TO_TRY[0])
        data = json.loads(response.text)
        
        def parse(val):
            digits = "".join(filter(str.isdigit, val))
            return int(digits[:-3]) if len(digits) > 3 else 0

        left = parse(data.get("meter_1", "0"))
        right = parse(data.get("meter_2", "0"))
        
        # Save to cache
        ingestion_data.setdefault(location, {})[room] = {
            "refresh": False,
            "left": left,
            "right": right
        }
        save_ingestion_data(ingestion_data)
        return {"left": left, "right": right}
    except Exception as e:
        logger.error(f"Error extracting {room}: {e}")
        return {"left": 0, "right": 0}
