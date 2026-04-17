import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel
from PIL import Image

# Load the environment variables from the .env file
load_dotenv()

# Define the exact JSON schema we expect using Pydantic
class MeterReadings(BaseModel):
    top_meter: str
    bottom_meter: str

def extract_meter_readings(image_path: str) -> str:
    # The client automatically picks up GEMINI_API_KEY from the environment
    client = genai.Client()
    
    # Load the image
    img = Image.open(image_path)
    
    # Prompt focusing strictly on the black background numbers
    prompt = "Extract the numbers from the two water meters in this image. Only provide the digits on the BLACK background."
    
    # Call the model, enforcing the Pydantic schema
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[img, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=MeterReadings
        )
    )
    
    return response.text

if __name__ == "__main__":
    target_image = r"c:\tmp\water_counter\Input_data\Rumyantsevo\bacthroom.jpeg"
    
    try:
        json_result = extract_meter_readings(target_image)
        print("Extraction Successful:")
        print(json_result)
    except Exception as e:
        print(f"An error occurred during extraction: {e}")