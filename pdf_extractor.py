import os
import json
import logging
from gemini_utils import call_gemini_with_retry

logger = logging.getLogger(__name__)

def parse_rumyantsevo_pdf(pdf_path: str, client, model_name) -> dict:
    logger.info(f"Initiating PDF parsing for: {pdf_path} using model: {model_name}")
    
    file_upload = client.files.upload(file=pdf_path)
    
    prompt = """
    You are an expert at extracting data from Russian utility bill PDF invoices.
    Extract the following service charges from the table.
    
    Required fields:
    - Содержание и техническое обслуживание помещений
    - Обращение с ТКО
    - Холодное водоснабжение
    - Холодная вода для ГВС
    - Теплоэнергия для ГВС
    - Водоотведение
    - Отопление
    - Охрана и мониторинг ЖК
    - Электроснабжение для СОИ:

    Guidelines:
    1. Identify the table structure. Column 2 contains the service name (Виды услуг), column 9 contains the value (Всего начисл.).
    2. Join multi-line service names into single lines (e.g., "Содержание и техническое\nобслуживание" -> "Содержание и техническое обслуживание").
    3. Remove all digits after the comma from the amount (e.g., '6815,62' -> '6815').
    4. Only extract the specific services listed above.
    5. Return ONLY a valid JSON object: {"Service Name": "Value"}.
    """
    
    try:
        response = call_gemini_with_retry(client, model_name, file_upload, prompt, context_info=f"PDF: {os.path.basename(pdf_path)}")
        extracted_data = json.loads(response.text)
        
        logger.info(f"--- Extracted PDF Fields for {os.path.basename(pdf_path)} ---")
        for service, value in extracted_data.items():
            logger.info(f"Parsed Field: '{service}' -> '{value}'")
        logger.info("--- End of Extraction ---")
            
        return extracted_data
        
    except Exception as e:
        logger.error(f"Failed to parse PDF {pdf_path}: {e}")
        return None
    finally:
        client.files.delete(name=file_upload.name)
