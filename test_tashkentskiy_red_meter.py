import os
import json
import logging
from google import genai
from PIL import Image
from dotenv import load_dotenv

# Configure logging to show detailed output
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def load_prompts(file_path):
    if not os.path.exists(file_path):
        logger.error(f"Prompts file not found at: {file_path}")
        return {}
    with open(file_path, 'r', encoding='utf-8') as f:
        try:
            prompts_list = json.load(f)
            return {p['name']: p['content'] for p in prompts_list}
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from {file_path}: {e}")
            return {}

def main():
    logger.info("--- Testing Tashkentskiy Red Meter Extraction (Direct API Call) ---")

    # Define full absolute paths based on the script's execution directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    prompts_path = os.path.join(script_dir, 'prompts.json')
    img_path = os.path.join(script_dir, 'Input_data', 'Tashkentskiy', 'red.jpeg')
    env_path = os.path.join(script_dir, '.env')
    
    # Load environment variables from the .env file
    load_dotenv(dotenv_path=env_path)

    # Load prompts
    prompts = load_prompts(prompts_path)
    prompt_name = "tashkentskiy_image_prompt_template"
    prompt_content = prompts.get(prompt_name)

    if not prompt_content:
        logger.error(f"Prompt '{prompt_name}' not found in {prompts_path}")
        return

    if not os.path.exists(img_path):
        logger.error(f"Image not found at: {img_path}")
        return

    try:
        img = Image.open(img_path)
        
        # Initialize Gemini client; it now automatically detects GEMINI_API_KEY from the environment
        client = genai.Client()
        logger.info("Gemini client initialized successfully.")
        
        # Target the specific lightweight model
        model_name = 'gemini-3.1-flash-lite-preview'
        
        # Print the model name and the full prompt payload
        logger.info(f"Targeting Gemini Model: {model_name}")
        logger.info(f"Full text of the prompt sent to the model:\n{prompt_content}")
        
        # Use the correct generate_content method for the google.genai SDK
        response = client.models.generate_content(
            model=model_name,
            contents=[prompt_content, img]
        )

        logger.info("Gemini API call successful.")
        logger.info(f"Raw Gemini API Response: \n{response.text}")

    except Exception as e:
        logger.error(f"An error occurred during Gemini API call: {e}")

if __name__ == "__main__":
    main()