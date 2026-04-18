# Water Counter and Service Charge Extractor

This project automates the reading of water meter values from local images using the Google Gemini Vision API and extracts service charge data from PDF invoices. All extracted data is uploaded directly to a Google Sheet.

## Features

- **Intelligent Model Selection:** Dynamically finds and prioritizes working Gemini vision models to ensure high availability.
- **PDF Invoice Parsing:** Automatically parses "Rumyantsevo" location PDF invoices using Gemini Vision, extracting service-specific charges into a structured format.
- **Persistent Caching:** Remembers the last successful model in `working_models.json` and manages extraction status via `data_for_ingestion.json`.
- **Robust Error Handling & Retries:** Uses exponential backoff (via `tenacity`) to automatically retry temporary `503 Server Errors`.
- **Data Transformation:** 
    - Automatically cleans extracted meter digits by dropping the three rightmost fractional digits and removing leading zeros.
    - Cleans service charge currency values from PDFs by removing digits after the comma.
- **Google Sheets Integration:** Appends combined meter readings and service charges as a new row to a configured Google Sheet.
- **Clean Logging:** Provides clear tracking of the active model, retry attempts, and data output for both meters and PDF fields.

## How It Works

### 1. Processing Pipeline
1. **Meter Extraction:** The Gemini model extracts the exact strings seen on the water meters, which are then cleaned and formatted.
2. **PDF Parsing:** The system scans `Input_data/Rumyantsevo/` for PDF invoices. Gemini Vision parses the table rows for "Виды услуг" and "Всего начисл." (column 9).
3. **Data Ingestion:**
   - Extracted values (e.g., "Содержание и техническое обслуживание помещений") are cleaned and stored in `data_for_ingestion.json`.
   - Data is uploaded to Google Sheets columns H through P.
   - Columns Q and R are automatically populated with values/formulas from the previous row.

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
2. **Crucial:** You must share your target Google Sheet (Viewer or Editor access) with the `client_email` found inside your Service Account JSON file.

### Installation

1.  Clone the repository:
    ```bash
    git clone [repository_url]
    cd water_counter
    ```
2.  Install required packages:
    ```bash
    pip install google-generativeai gspread google-auth pydantic Pillow python-dotenv tenacity pdfplumber
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