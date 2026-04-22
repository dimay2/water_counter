# Water Counter and Service Charge Extractor

This project automates the reading of water meter values from local images using the Google Gemini Vision API and extracts service charge data from PDF invoices. All extracted data is uploaded directly to a Google Sheet.

## Features

- **Intelligent Model Selection:** Dynamically finds and prioritizes working Gemini vision models to ensure high availability.
- **PDF Invoice Parsing:** Automatically parses location-specific PDF invoices using Gemini Vision, extracting service-specific charges into a structured format.
- **Persistent Caching:** Remembers the last successful model in `working_models.json` and manages extraction status via `data_for_ingestion.json`.
- **Robust Error Handling & Retries:** Uses exponential backoff (via `tenacity`) to automatically retry temporary `503 Server Errors`.
- **Data Transformation & Validation:** 
    - **Deterministic Parsing:** Automatically cleans extracted meter digits by dropping the three rightmost fractional digits and removing leading zeros.
    - **Reading Validation:** Compares current readings with previous values from Google Sheets; raises an error if the consumption exceeds 20 units to prevent faulty extractions.
    - **Service Charge Cleaning:** Cleans service charge currency values from PDFs by removing digits after the comma.
- **Color-Coded Meter Logic:** Specifically designed to handle locations like "Tashkentskiy" where meters are identified by color (Red for Left/Hot, Blue for Right/Cold). The system ensures that cached readings are only considered complete if both red and blue meter readings are successfully populated for the day.
- **Google Sheets Integration:** Appends combined meter readings and service charges as a new row to a configured Google Sheet.
- **Clean Logging:** Provides clear tracking of the active model, extraction results, validation checks, and data upload status.

## How It Works

### 1. Processing Pipeline
1. **Meter Extraction:** 
   - For standard locations (e.g., Rumyantsevo), it extracts both meters from single images (kitchen, bathroom).
   - For color-coded locations (e.g., Tashkentskiy), it identifies the meter color and reading from individual images and combines them.
2. **Validation:** Before saving, the system fetches the last row from Google Sheets. If the new reading is more than 20 units higher than the previous one, it raises a validation error and stops processing for that location.
3. **PDF Parsing:** The system scans for PDF invoices in location-specific directories. Gemini Vision parses the utility charges into structured data.
4. **Data Ingestion:**
   - Extracted values are cleaned and stored in `data_for_ingestion.json`.
   - Data is uploaded to specific columns in Google Sheets based on the location profile.
   - Summarization formulas are dynamically applied where configured.

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

1. Profiles and column mappings are defined in `profiles.json`.
2. **Crucial:** You must share your target Google Sheet (Viewer or Editor access) with the `client_email` found inside your Service Account JSON file.

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

To run the full extraction and upload pipeline:

```bash
python water_counter_to_sheets.py
```

## Project Structure

-   `water_counter_to_sheets.py`: Main entry point that orchestrates extraction and upload.
-   `meter_extractor.py`: Logic for water meter image extraction and orchestration of location data.
-   `pdf_extractor.py`: Gemini-powered PDF invoice parsing logic.
-   `gsheet_uploader.py`: Logic for Google Sheets connectivity and data ingestion.
-   `Input_data/`: Directory for input images and PDF invoices.
-   `data_for_ingestion.json`: Local cache for extracted readings and PDF service charge data.
-   `README.md`: Project description and setup instructions.
-   `.env`: Configuration for API keys and Spreadsheet IDs.