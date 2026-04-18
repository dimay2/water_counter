# Water Counter Vision Extractor

This project automates the reading of water meter values from local images using the Google Gemini Vision API and uploads the extracted data directly to a Google Sheet.

## Features

- **Intelligent Model Selection:** Dynamically finds and prioritizes working Gemini vision models to ensure high availability.
- **Persistent Caching:** Remembers the last successful model in `working_models.json` to speed up subsequent runs and reduce unnecessary API listing calls.
- **Robust Error Handling & Retries:** Uses exponential backoff (via `tenacity`) to automatically retry temporary `503 Server Errors` (waiting ~8s, 16s, and 32s between attempts).
- **Rate Limit Compliance:** Introduces randomized delays (4-8 seconds) before API calls to strictly comply with Google AI Studio's requests-per-minute limitations.
- **Data Transformation:** Automatically cleans extracted meter digits by dropping the three rightmost fractional digits and removing leading zeros.
- **Google Sheets Integration:** Appends the final integer readings as a new row to a configured Google Sheet.
- **Clean Logging:** Suppresses noisy REST API background logs while providing clear, professional tracking of the active model, retry attempts, and data output.

## How It Works

### 1. Model Selection Algorithm
To guarantee the script survives quota limits (`429`) and model deprecations (`404`), it uses a dynamic cascade strategy:
- **Cache First:** The script loads known-working models from `working_models.json`.
- **Fallback:** If cached models fail due to limits or errors, it fetches a fresh list of models directly from the Gemini API.
- **Filter:** It dynamically excludes non-vision models (like `text`, `embedding`, `audio`, etc.).
- **Promote:** Once a model succeeds, it gets promoted to the top of `working_models.json` so the script uses the fastest/most reliable model immediately on the next run.

### 2. Processing Pipeline
1. The chosen Gemini model extracts the exact strings seen on the meters (e.g., `000487016`).
2. The script drops the last three red digits (`000487`).
3. Leading zeros are stripped, leaving the exact integer reading (`487`).
4. Readings for both the Bathroom and Kitchen, along with the **current date**, are formatted and uploaded securely to Google Sheets.

## Setup and Installation

### Prerequisites

-   Python 3.x
-   Google Cloud Project with the Gemini API enabled.
-   Google Sheets API and Google Drive API enabled.
-   Service account credentials (JSON file) mapped to the `GOOGLE_APPLICATION_CREDENTIALS` environment variable.

### Environment Variables

Create a `.env` file in the project root:

```
GOOGLE_API_KEY=YOUR_GEMINI_API_KEY
```

### Google Sheets Configuration

1. Ensure your Google Sheet is set up. The script defaults to specific IDs if the `.env` variables are missing.
2. **Crucial:** You must share your target Google Sheet (Viewer or Editor access) with the `client_email` found inside your Service Account JSON file, otherwise the script will return a `404 Spreadsheet Not Found` error.

### Installation

1.  Clone the repository:
    ```bash
    git clone [repository_url]
    cd water_counter
    ```
2.  Install required packages:
    ```bash
    pip install google-generativeai gspread google-auth pydantic Pillow python-dotenv tenacity
    ```

## Usage

To run the extraction and upload pipeline:

```bash
python water_counter_to_sheets.py
```

## Project Structure

-   `water_counter_to_sheets.py`: Main entry point that orchestrates meter extraction and data upload.
-   `meter_extractor.py`: Logic for extracting water meter values from images, including Gemini API interaction and result caching.
-   `gsheet_uploader.py`: Logic for Google Sheets connectivity and data ingestion.
-   `Input_data/`: Directory to store input images (e.g., `Rumyantsevo/kitchen.jpeg`, `Rumyantsevo/bacthroom.jpeg`).
-   `working_models.json`: Automatically generated cache of working Gemini models.
-   `data_for_ingestion.json`: Local cache storing processed meter readings to reduce redundant API calls.
-   `README.md`: Project description and setup instructions.
-   `.env`: Configuration for API keys and Spreadsheet IDs.