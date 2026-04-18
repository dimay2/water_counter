import os
import json
import logging
from datetime import datetime
import random
import time
from PIL import Image
from google import genai
from google.genai import types
from pydantic import BaseModel
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception, RetryError

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
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            logger.warning(f"Could not read {DATA_INGESTION_FILE}: {e}")
    return []

def save_ingestion_data(data_list):
    try:
        with open(DATA_INGESTION_FILE, 'w') as f:
            json.dump(data_list, f, indent=4)
    except Exception as e:
        logger.warning(f"Could not write {DATA_INGESTION_FILE}: {e}")

def get_api_vision_models(client):
    valid_model_names = [m.name.replace("models/", "") for m in client.models.list()]
    preferred_order = [
        'gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.0-flash', 
        'gemini-2.0-flash-lite', 'gemini-2.0-pro-exp'
    ]
    models_to_try = [m for m in preferred_order if m in valid_model_names]
    excluded_keywords = ['embedding', 'aqa', 'text', '1.0', '1.5', 'tts', 'audio', 'imagen', 'veo', 'lyria', 'robotics', 'computer-use']
    for m in valid_model_names:
        if m.startswith('gemini-') and not any(kw in m for kw in excluded_keywords) and m not in models_to_try:
            models_to_try.append(m)
    return models_to_try

def is_503_error(exception: Exception) -> bool:
    return "503" in str(exception) or "UNAVAILABLE" in str(exception)

def is_429_error(exception: Exception) -> bool:
    return "429" in str(exception) or "RESOURCE_EXHAUSTED" in str(exception)

def is_404_error(exception: Exception) -> bool:
    return "404" in str(exception) or "NOT_FOUND" in str(exception)

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

def extract_numbers_from_meter(location: str, position: str, img_path: str) -> tuple[int, str]:
    if not os.path.exists(img_path):
        logger.error(f"Image not found: {img_path}")
        return 0, ""

    today_ymd = datetime.now().strftime("%Y%m%d")
    ingestion_data = load_ingestion_data()
    
    # Check cache for existing data for this meter and today's date
    for entry in ingestion_data:
        if (entry.get("water_meter_location") == location and
            entry.get("water_meter_position") == position and
            entry.get("last_update") == today_ymd):
            if not entry.get("refresh", False):
                return entry.get('water_meter_value', 0), "Cached"
            else:
                logger.info(f"Refresh requested for {location} {position} meter. Re-processing...")
                break

    global _CACHED_MODELS_TO_TRY

    try:
        client = genai.Client()
        img = Image.open(img_path)
        prompt = f"Extract all digits from the {position} water meter in this image, including both the black and red background digits. Return it as meter_1 as string, preserving all leading zeros. If there are two meters, extract the one that corresponds to the {position} position."
        
        if _CACHED_MODELS_TO_TRY is None:
            _CACHED_MODELS_TO_TRY = load_cached_models()

        if not _CACHED_MODELS_TO_TRY:
            _CACHED_MODELS_TO_TRY = get_api_vision_models(client)

        def process_meter_string(m_str):
            if not m_str: return 0
            digits = "".join(filter(str.isdigit, str(m_str)))
            if len(digits) <= 3: return 0
            digits = digits[:-3]
            digits = digits.lstrip('0')
            return int(digits) if digits else 0

        while True:
            models_to_iterate = list(_CACHED_MODELS_TO_TRY)
            for model_name in models_to_iterate:
                time.sleep(random.uniform(4.0, 8.0))
                try:
                    response = _call_gemini_with_retry(client, img, prompt, model_name)
                    data = json.loads(response.text)
                    meter_value = process_meter_string(data.get("meter_1", ""))

                    new_entry = {
                        "water_meter_location": location,
                        "water_meter_position": position,
                        "water_meter_value": meter_value,
                        "last_update": today_ymd
                    }
                    found = False
                    for idx, entry in enumerate(ingestion_data):
                        if entry.get("water_meter_location") == location and entry.get("water_meter_position") == position:
                            ingestion_data[idx] = new_entry
                            found = True
                            break
                    if not found:
                        ingestion_data.append(new_entry)
                    save_ingestion_data(ingestion_data)

                    if model_name in _CACHED_MODELS_TO_TRY:
                        _CACHED_MODELS_TO_TRY.remove(model_name)
                    _CACHED_MODELS_TO_TRY.insert(0, model_name)
                    save_cached_models(_CACHED_MODELS_TO_TRY)
                    
                    return meter_value, model_name
                except Exception as e:
                    if is_429_error(e) or is_404_error(e):
                        continue
                    else:
                        if model_name in _CACHED_MODELS_TO_TRY:
                            _CACHED_MODELS_TO_TRY.remove(model_name)
                            save_cached_models(_CACHED_MODELS_TO_TRY)
            break
        return 0, ""
    except Exception as e:
        logger.error(f"Error in extract_numbers_from_meter: {e}")
        return 0, ""
