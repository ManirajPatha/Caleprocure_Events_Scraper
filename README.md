CaleProcure Events Scraper
This repository contains a Selenium-based scraper for extracting detailed bid opportunity information from the California State procurement portal (CaleProcure).
Features
•	Navigates the CaleProcure event search page and iterates through event rows.
•	Opens each event’s detail page in a separate tab and extracts structured data.
•	Captures core fields: Event Name, Event ID, Dept, Format/Type, Event Version, Published Date, Event End Date.
•	Extracts Contact Information, Pre-Bid Conference details, Description text, and UNSPSC codes.
•	Follows the "View Event Package" link and collects attachment download URLs from the "Download Attachment" popup.
•	Handles common UI issues: loading screen, blocked popup notices, stale elements, and other intermittent Selenium errors.
•	Supports partial/segmented scraping using a row range argument so large runs can be split across multiple executions.
•	Writes results as a structured JSON file.
Requirements
•	Python 3.8+
•	Google Chrome browser
•	ChromeDriver compatible with your Chrome version
•	The following Python packages: selenium, python-docx (only needed to generate this README), and any other standard library dependencies
Installation
1. Clone this repository:
   git clone https://github.com/<your-username>/<your-repo>.git
   cd <your-repo>
2. Create and activate a virtual environment (optional but recommended).
3. Install dependencies:
   pip install -r requirements.txt
4. Ensure ChromeDriver is installed and either on your PATH or configured for Selenium’s default discovery.
Script Overview
The main script is `Caleprocure_events_scraper.py`. It opens the CaleProcure event search page, scrolls to the results table, iterates through event rows, and for each event:
•	Opens the event details in a new tab.
•	Waits for the details page to fully load and passes over rows that remain on `loading.html`.
•	Extracts Details (Event ID, Dept, Format/Type, Event Version, Published Date, Event End Date).
•	Extracts Contact Information block (name, phone, email if present).
•	Extracts the Pre-Bid Conference section when available.
•	Extracts the full Description text under the Description heading.
•	Expands and parses UNSPSC Codes table if present.
•	Clicks "View Event Package", iterates the attachments table, and for each row:
   - Clicks the download icon/button.
   - Waits for the "Download Attachment" popup.
   - Reads the `href` from the `Download Attachment` button (`id="downloadButton"`).
   - Adds that URL to the `Attachments` list.
All values are normalized and written to a JSON file as a list of event objects.
Command-Line Usage
Basic run (scrape all rows until completion or an unrecoverable error).
    python Caleprocure_events_scraper.py --out-json caleprocure_all.json
Run in headless mode:
    python Caleprocure_events_scraper.py --out-json caleprocure_all.json --headless
Limit maximum pages (for testing):
    python Caleprocure_events_scraper.py --out-json test.json --max-pages 2
Limit number of events (for testing):
    python Caleprocure_events_scraper.py --out-json test.json --limit 50
Row Range / Chunked Scraping
For large datasets or when the site is unstable, the scraper supports processing only a specific range of rows across the entire result set using the `--upto` argument.
Syntax:
    --upto "start-end"
The indices are 1-based and inclusive, based on the overall row order as the script walks the table.
Examples:
    # Scrape rows 1-100
    python Caleprocure_events_scraper.py --out-json caleprocure_1_100.json --upto "1-100"
    # Scrape rows 101-200
    python Caleprocure_events_scraper.py --out-json caleprocure_101_200.json --upto "101-200"
Each run produces a JSON file for that slice. You can merge these JSON arrays later to build a complete dataset.
Resilience & Error Handling
•	If an individual row fails (timeouts, bad navigation, etc.), it is skipped and the script continues.
•	If an event details page remains on `loading.html`, that row is logged and skipped.
•	Blocked popup notices (such as "Popup Blocked!!") are detected and closed automatically.
•	Attachment extraction is best-effort: missing or failing attachment rows are logged but do not stop the run.
•	On any unexpected exception, all successfully scraped events collected so far are still written to the output JSON file.
Output Format
The output JSON file is a list of objects. Each object can contain:
•	`Event Name`
•	`Details` (sub-object: Event ID, Dept, Format/Type, Event Version, Published Date, Event End Date)
•	`Contact Information` (sub-object)
•	`Pre Bid Conference` (sub-object)
•	`Description`
•	`UNSPSC Codes` (list of sub-objects)
•	`Attachments` (list of attachment URLs from Download Attachment buttons)
•	`Detail URL` (URL of the event details page)
Notes
- This scraper is tailored specifically to the current CaleProcure layout. If the site’s structure changes, selectors may need updating.
- Use responsibly and in accordance with CaleProcure’s terms of use.
- Long runs are best executed in smaller `--upto` chunks to reduce risk of interruption.
