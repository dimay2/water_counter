# Water Meter Reading Enhancement Plan

## Design Document: Tashkentskiy Meter Logic & Validation

### 1. Overview
The goal is to enhance the water meter reading extraction process for the `Tashkentskiy` location. This involves retrieving historical data from Google Sheets, implementing a logic check against previous readings, and fine-tuning the AI prompt if the readings exceed reasonable bounds.

### 2. Objectives
- Programmatically fetch the latest readings for each meter from the relevant Google Sheet.
- Integrate these values as "previous_reading" in `data_for_ingestion.json`.
- Implement a post-extraction validation step:
  - If `decoded_reading` is within `[previous, previous + 20]`, proceed.
  - If the reading is out of range, re-trigger the extraction for that specific image with a refined prompt that includes the constraint: `reading <= [previous] + 20`.
- Standardize the Tashkentskiy meter cleanup logic:
  - Trim trailing fractional digits (3 digits).
  - Trim leading zeros.

### 3. Proposed Changes

#### A. Data Retrieval
- Enhance `gsheet_uploader.py` or create a utility function to retrieve the last row's data for specific meters.
- Update the script to fetch this before starting the extraction loop.

#### B. Validation & Logic Loop
- The `meter_extractor.py` will handle the comparison.
- If validation fails, it will re-invoke the extraction function with an adjusted prompt.

#### C. Prompt Refinement
- Update the prompt sent to Gemini to explicitly mention expected ranges when a previous reading is available.

### 4. Implementation Steps

1.  **GSheet Data Retrieval**
    - Create/Update utility to fetch the latest values from GSheet.
2.  **Logic Update in `meter_extractor.py`**
    - Modify `extract_room_meters` to accept `prev_value`.
    - Implement conditional logic to re-extract with refined prompt if necessary.
3.  **Data Ingestion Updates**
    - Persist the retrieved `prev_value` in `data_for_ingestion.json` for subsequent checks.
4.  **Testing**
    - Run the pipeline and inspect `data_for_ingestion.json` for correct field population.
    - Validate that outliers (e.g., jump > 20) correctly trigger a re-extraction.

---
**Does this design align with your requirements? Once approved, I will proceed to create the implementation plan.**