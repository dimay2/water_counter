import os
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

load_dotenv()

class MeterReadings(BaseModel):
    top_meter: str
    bottom_meter: str

# Helper function for tenacity to only retry on 503 Service Unavailable errors
def is_503_error(exception: Exception) -> bool:
    return "503" in str(exception) or "UNAVAILABLE" in str(exception)

# Retry strategy: Wait 2^x * 2 seconds between each retry, up to 10 seconds, max 4 attempts
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
            response_schema=MeterReadings
        )
    )

def extract_meter_readings(image_path: str) -> str:
    client = genai.Client()
    img = Image.open(image_path)
    prompt = "Extract the numbers from the two water meters in this image. Only provide the digits on the BLACK background."
    
    primary_model = 'gemini-2.5-flash'
    fallback_model = 'gemini-1.5-flash'
    
    try:
        # Attempt extraction with the primary model, applying exponential backoff
        response = _call_gemini_with_retry(client, img, prompt, primary_model)
        return response.text
        
    except Exception as e:
        if is_503_error(e):
            logger.warning(f"Primary model {primary_model} failed after retries. Falling back to {fallback_model} for {image_path}")
            try:
                # Attempt extraction with the fallback model
                response = _call_gemini_with_retry(client, img, prompt, fallback_model)
                return response.text
            except Exception as fallback_error:
                logger.error(f"Fallback model also failed: {fallback_error}")
                raise
        else:
            # Re-raise if it's a different type of error (e.g., authentication, invalid image)
            raise e

if __name__ == "__main__":
    # Use absolute path relative to the script's directory or the project root
    base_dir = os.path.dirname(os.path.abspath(__file__))
    target_image = os.path.join(base_dir, "Input_data", "Rumyantsevo", "kitchen.jpeg")
    
    if not os.path.exists(target_image):
        # Try bathroom as fallback for testing if kitchen isn't there
        target_image = os.path.join(base_dir, "Input_data", "Rumyantsevo", "bacthroom.jpeg")

    try:
        json_result = extract_meter_readings(target_image)
        logger.info("Extraction Successful:")
        print(json_result)
    except Exception as final_error:
        logger.error(f"Final extraction failure for {target_image}: {final_error}")
