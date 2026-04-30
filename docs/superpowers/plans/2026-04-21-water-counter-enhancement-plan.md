# Water Meter Reading Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate historical reading checks and refined extraction logic for water meters.

**Architecture:** Modify `meter_extractor.py` and `water_counter_to_sheets.py` to retrieve previous readings, compare against new ones, and re-extract with tuned prompts if necessary.

**Tech Stack:** Python, JSON, Pydantic, Gemini API.

---

### Task 1: Add Utility for GSheet Reading Retrieval

**Files:**
- Modify: `gsheet_uploader.py`

- [ ] **Step 1: Add a function to `gsheet_uploader.py` to fetch the last row's reading**

```python
def get_last_readings(spreadsheet_id, sheet_name):
    # Logic to fetch last values
    pass
```

- [ ] **Step 2: Commit**

```bash
git add gsheet_uploader.py
git commit -m "feat: add get_last_readings utility"
```

### Task 2: Update `meter_extractor.py` for Validation Logic

**Files:**
- Modify: `meter_extractor.py`

- [ ] **Step 1: Update `extract_room_meters` to accept `prev_value`**

- [ ] **Step 2: Add validation logic: if difference > 20, re-extract with tuned prompt**

```python
def validate_reading(current, previous):
    if 0 <= (current - previous) <= 20:
        return True
    return False
```

- [ ] **Step 3: Commit**

```bash
git add meter_extractor.py
git commit -m "feat: add validation logic for readings"
```

### Task 3: Update `water_counter_to_sheets.py` Main Loop

**Files:**
- Modify: `water_counter_to_sheets.py`

- [ ] **Step 1: Fetch previous values at start of processing loop**
- [ ] **Step 2: Pass `prev_value` to `extract_room_meters`**
- [ ] **Step 3: Commit**

```bash
git add water_counter_to_sheets.py
git commit -m "feat: integrate previous value check in main loop"
```

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-21-water-counter-enhancement-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**