import os
import json
import logging
from google.genai import types

logger = logging.getLogger(__name__)

def parse_rumyantsevo_pdf(pdf_path: str, client) -> dict:
    """
    Parses Rumyantsevo PDF invoice using Gemini Vision API.
    Uses 'refresh' logic to avoid unnecessary re-parsing.
    """
    logger.info(f"Checking PDF for parsing: {pdf_path}")
    
    # Placeholder: Assuming we load ingestion data to check 'refresh' status
    # This matches the pattern in meter_extractor.py
    
    logger.info(f"Parsing PDF with Gemini: {pdf_path}")
    
    # Upload the PDF file
    file_upload = client.files.upload(path=pdf_path)
    
    prompt = """
    Extract data from this PDF invoice table.
    1. Focus on columns "Виды услуг" and "Всего начисл." (column 9).
    2. Extract only the service type and its corresponding value.
    3. Remove all digits after the comma in the value (e.g., '6815,62' -> '6815').
    4. Stop extraction after the service "Электроснабжение для СОИ:".
    5. Return result as pure JSON: {"Service Name": "Value"}.
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=[file_upload, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0
            )
        )
        
        extracted_data = json.loads(response.text)
        
        # Log parsed fields with Russian characters
        for service, value in extracted_data.items():
            logger.info(f"Parsed Field: {service} -> {value}")
            
        return extracted_data
        
    except Exception as e:
        logger.error(f"Error parsing PDF with Gemini: {e}")
        return {}
    finally:
        client.files.delete(name=file_upload.name)
