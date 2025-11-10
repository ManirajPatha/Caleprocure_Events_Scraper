import re
import json
import time
import argparse
from typing import List, Dict, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementNotInteractableException,
    StaleElementReferenceException,
)

START_URL = "https://caleprocure.ca.gov/pages/Events-BS3/event-search.aspx"

BANNER_SNIPPET = (
    "All businesses are encouraged to provide voluntary diversity data information in their CaleProcure profiles."
)

LABELS = [
    "Event ID",
    "Dept",
    "Dept:",
    "Department",
    # "Judicial Branch",  # <- removed: it's a value, not a label
    "Format/Type",
    "Format/Type:",
    "Event Version",
    "Published Date",
    "Event End Date",
    "Event End Date:",
]

# ================== basic helpers ==================

def build_driver(headless: bool = False) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--start-maximized")
    opts.add_argument("--window-size=1600,1200")
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(120)
    return driver

def scroll_into_view(driver, el):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)

def raw_text(el) -> str:
    try:
        return el.text or ""
    except Exception:
        return ""

def clean_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value
    if BANNER_SNIPPET in v:
        v = v.replace(BANNER_SNIPPET, "")
    v = re.sub(r"\s+", " ", v).strip()
    return v or None

def clean_lines(text: str) -> List[str]:
    if not text:
        return []
    if BANNER_SNIPPET in text:
        text = text.replace(BANNER_SNIPPET, "")
    return [l.strip() for l in text.splitlines() if l.strip()]

# ================== list page helpers ==================

def goto_events_section(driver):
    try:
        heading = driver.find_element(
            By.XPATH,
            "//*[self::h3 or self::h4 or self::h5][normalize-space()='EVENTS']",
        )
    except NoSuchElementException:
        heading = driver.find_element(
            By.XPATH,
            "//*[contains(translate(., 'events', 'EVENTS'),'EVENTS')]",
        )
    scroll_into_view(driver, heading)
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located(
            (By.XPATH, "//table[.//th[normalize-space()='Event Name']]//tbody/tr")
        )
    )

def get_event_rows(driver):
    return driver.find_elements(
        By.XPATH,
        "//table[.//th[normalize-space()='Event Name']]/tbody/tr[.//td]"
    )

def get_event_name_from_row(row) -> str:
    try:
        cell = row.find_element(By.XPATH, ".//td[2]")
    except NoSuchElementException:
        return ""
    txt = cell.get_attribute("innerText") or cell.text or ""
    return clean_text(txt) or ""

def extract_event_url_from_onclick(onclick: str) -> Optional[str]:
    if not onclick:
        return None
    m = re.search(r"['\"](\/event\/[^'\"]+)['\"]", onclick)
    if m:
        return "https://caleprocure.ca.gov" + m.group(1)
    m = re.search(r"https?:\/\/[^'\"]*\/event\/[^\s'\"]+", onclick)
    if m:
        return m.group(0)
    return None

def row_click_target_and_url(row):
    # Prefer Event Name cell's link
    try:
        link = row.find_element(By.XPATH, ".//td[2]//a[normalize-space()]")
        href = link.get_attribute("href") or ""
        if "/event/" in href:
            return link, href
        url_from_onclick = extract_event_url_from_onclick(
            link.get_attribute("onclick") or ""
        )
        return link, url_from_onclick
    except NoSuchElementException:
        pass

    # Fallback: Event ID link
    try:
        link = row.find_element(By.XPATH, ".//td[1]//a[normalize-space()]")
        href = link.get_attribute("href") or ""
        if "/event/" in href:
            return link, href
        url_from_onclick = extract_event_url_from_onclick(
            link.get_attribute("onclick") or ""
        )
        return link, url_from_onclick
    except NoSuchElementException:
        pass

    # Last resort
    try:
        cell = row.find_element(By.XPATH, ".//td[2]")
        return cell, None
    except NoSuchElementException:
        return row, None

def robust_open_new_tab(driver, clickable, guessed_url: Optional[str]) -> None:
    handles_before = driver.window_handles[:]
    scroll_into_view(driver, clickable)
    time.sleep(0.1)

    try:
        clickable.click()
    except ElementNotInteractableException:
        try:
            driver.execute_script("arguments[0].click();", clickable)
        except Exception:
            pass

    time.sleep(0.5)
    handles_after = driver.window_handles[:]

    if len(handles_after) == len(handles_before):
        if not guessed_url:
            href = clickable.get_attribute("href") or ""
            if "/event/" in href:
                guessed_url = href
            else:
                guessed_url = extract_event_url_from_onclick(
                    clickable.get_attribute("onclick") or ""
                )
        if guessed_url:
            driver.execute_script("window.open(arguments[0], '_blank');", guessed_url)
            time.sleep(0.4)

    driver.switch_to.window(driver.window_handles[-1])

def ensure_event_loaded_or_skip(driver, base_wait: float = 10.0) -> bool:
    time.sleep(base_wait)
    try:
        if "loading.html" in driver.current_url:
            WebDriverWait(driver, 20).until(EC.url_matches(r".*/event/.*"))
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[normalize-space()='Details']")
            )
        )
    except TimeoutException:
        if "loading.html" in driver.current_url:
            print("[WARN] stuck on loading.html, skip row")
            return False
    if "loading.html" in driver.current_url:
        print("[WARN] still on loading.html, skip row")
        return False
    return True

# ================== Details label extraction ==================

def is_label(text: str) -> bool:
    t = text.strip().rstrip(":")
    return any(t == l.rstrip(":") for l in LABELS)

def find_value_by_label(driver, label: str) -> Optional[str]:
    try:
        el = driver.find_element(
            By.XPATH,
            f"(//*[normalize-space(text())='{label}'])[1]/following::*[normalize-space()!=''][1]"
        )
    except NoSuchElementException:
        return None

    txt = clean_text(raw_text(el))
    if not txt:
        return None
    if is_label(txt):
        return None
    for lab in LABELS:
        if lab != label and txt.startswith(lab):
            return None
    return txt

def extract_label_values(driver) -> Dict[str, str]:
    # First, handle the common pattern:
    # <small class="text-muted">Dept:</small><br>
    # <span data-if-label="dept" ...>Judicial Branch</span>
    details: Dict[str, str] = {}

    try:
        dept_span = driver.find_element(
            By.XPATH,
            "//*[@data-if-label='dept' or @data-if-label='Dept' or contains(@data-if-label,'DEPT')]"
        )
        dept_val = clean_text(raw_text(dept_span))
        if dept_val:
            details["Dept"] = dept_val
    except NoSuchElementException:
        pass

    label_map = {
        "Event ID": "Event ID",
        "Dept:": "Dept",
        "Dept": "Dept",
        "Department": "Dept",
        # "Judicial Branch": "Dept",  # <- removed: it's a value not a label
        "Format/Type:": "Format/Type",
        "Format/Type": "Format/Type",
        "Event Version": "Event Version",
        "Published Date": "Published Date",
        "Event End Date:": "Event End Date",
        "Event End Date": "Event End Date",
    }

    for label, key in label_map.items():
        # Skip label-based Dept extraction if we already captured Dept from data-if-label
        if key == "Dept" and "Dept" in details:
            continue

        v = find_value_by_label(driver, label)
        if not v:
            continue
        if key == "Event Version":
            m = re.search(r"\d+", v)
            if m:
                v = m.group(0)
        if key not in details:
            details[key] = v

    return details

# ================== Contact / Pre-Bid / UNSPSC / Description ==================

def extract_contact_info(driver) -> Dict[str, str]:
    try:
        root = driver.find_element(
            By.XPATH,
            "//*[normalize-space()='Contact Information']"
            "/ancestor::*[contains(@class,'col') or contains(@class,'card') or contains(@class,'panel')][1]"
        )
    except NoSuchElementException:
        try:
            root = driver.find_element(
                By.XPATH,
                "//*[normalize-space()='Contact Information']/parent::*"
            )
        except NoSuchElementException:
            return {}

    lines = clean_lines(raw_text(root))
    info: Dict[str, str] = {}

    try:
        idx = lines.index("Contact Information")
    except ValueError:
        idx = -1

    if idx != -1:
        for line in lines[idx + 1:]:
            if not line:
                continue
            if ":" in line or "Pre Bid Conference" in line:
                break
            info["Contact Name"] = line
            break

    for line in lines:
        low = line.lower()
        if low.startswith("phone"):
            val = line.split(":", 1)[1].strip() if ":" in line else ""
            if val:
                info["Phone"] = val
        if low.startswith("email"):
            val = line.split(":", 1)[1].strip() if ":" in line else ""
            if val:
                info["Email"] = val

    try:
        a = root.find_element(By.XPATH, ".//a[contains(@href,'mailto:')]")
        email = (a.get_attribute("href") or "").replace("mailto:", "").strip()
        if email:
            email = email.split("?", 1)[0]
            info["Email"] = email
    except NoSuchElementException:
        pass

    for k in list(info.keys()):
        cv = clean_text(info[k])
        if cv:
            info[k] = cv
        else:
            del info[k]

    return info

def extract_prebid(driver) -> Dict[str, str]:
    titles = [
        "Pre Bid Conference",
        "Pre Bid Conference (N/A)",
        "Pre Bid Conference(N/A)",
    ]
    root = None
    for t in titles:
        try:
            root = driver.find_element(
                By.XPATH,
                f"//*[contains(normalize-space(),'{t}')]"
                "/ancestor::*[contains(@class,'col') or contains(@class,'card') or contains(@class,'panel')][1]"
            )
            break
        except NoSuchElementException:
            continue
    if root is None:
        for t in titles:
            try:
                root = driver.find_element(
                    By.XPATH,
                    f"//*[contains(normalize-space(),'{t}')]/parent::*"
                )
                break
            except NoSuchElementException:
                continue
    if root is None:
        return {}

    lines = clean_lines(raw_text(root))
    pre: Dict[str, str] = {}

    for line in lines:
        low = line.lower()
        if low.startswith("mandatory"):
            v = line.split(":", 1)[1].strip() if ":" in line else ""
            if v:
                pre["Mandatory"] = v
        elif low.startswith("date"):
            v = line.split(":", 1)[1].strip() if ":" in line else ""
            if v:
                pre["Date"] = v
        elif low.startswith("time"):
            v = line.split(":", 1)[1].strip() if ":" in line else ""
            if v:
                pre["Time"] = v
        elif low.startswith("location"):
            v = line.split(":", 1)[1].strip() if ":" in line else ""
            if v:
                pre["Location"] = v
        elif low.startswith("comments"):
            v = line.split(":", 1)[1].strip() if ":" in line else ""
            if v:
                pre["Comments"] = v

    for k in list(pre.keys()):
        cv = clean_text(pre[k])
        if cv:
            pre[k] = cv
        else:
            del pre[k]

    return pre

def expand_unspsc_if_needed(driver):
    try:
        header = driver.find_element(
            By.XPATH,
            "//*[normalize-space()='UNSPSC Codes' or contains(., 'UNSPSC Codes')]"
        )
        try:
            driver.find_element(
                By.XPATH,
                "//table[.//th[contains(.,'UNSPSC Classification')]]"
            )
            return
        except NoSuchElementException:
            pass
        try:
            header.click()
        except Exception:
            driver.execute_script("arguments[0].click();", header)
        time.sleep(0.4)
    except NoSuchElementException:
        pass

def extract_unspsc(driver) -> List[Dict[str, str]]:
    expand_unspsc_if_needed(driver)
    rows: List[Dict[str, str]] = []
    try:
        table = driver.find_element(
            By.XPATH,
            "//table[.//th[contains(.,'UNSPSC Classification')]]"
        )
    except NoSuchElementException:
        return rows

    headers = [
        clean_text(raw_text(th)) or "" for th in table.find_elements(By.XPATH, ".//th")
    ]

    for tr in table.find_elements(By.XPATH, ".//tbody/tr"):
        tds = tr.find_elements(By.XPATH, ".//td")
        if not tds:
            continue
        row = {}
        for i, td in enumerate(tds):
            key = headers[i] if i < len(headers) else f"col_{i+1}"
            val = clean_text(raw_text(td)) or ""
            row[key] = val
        if any(v for v in row.values()):
            rows.append(row)

    return rows

def extract_full_description(driver) -> Optional[str]:
    try:
        label = driver.find_element(
            By.XPATH,
            "//*[normalize-space()='Description:' or normalize-space()='Description']"
        )
    except NoSuchElementException:
        return None

    parent = label.find_element(
        By.XPATH,
        "./ancestor::*[contains(@class,'col') or contains(@class,'panel')][1]"
    )

    following = parent.find_elements(
        By.XPATH,
        ".//*[preceding-sibling::*[normalize-space()='Description:' or normalize-space()='Description']]"
    )

    texts = []
    for el in following:
        t = raw_text(el).strip()
        if not t:
            continue
        low = t.lower()
        if (
            low.startswith("contact information")
            or low.startswith("pre bid conference")
            or "unspsc codes" in low
            or "unspsc classification" in low
        ):
            break
        texts.append(t)

    if not texts:
        return None

    return clean_text(" ".join(texts))

# ================== Attachments ==================

def get_attachments(driver) -> List[str]:
    """
    From the Event Details page:
    - Click 'View Event Package'
    - On attachments table, for each row:
        - Click its download icon/button/link
        - Wait for 'Download Attachment' popup
        - Read href from <a id="downloadButton" ...>
        - Close popup
    - Return list of all unique hrefs
    - Navigate back to the details page.
    """
    attachments: List[str] = []
    detail_url = driver.current_url

    # 1) Open attachments page via "View Event Package"
    try:
        vp = driver.find_element(
            By.XPATH,
            "//a[normalize-space()='View Event Package']"
            " | //button[normalize-space()='View Event Package']"
        )
    except NoSuchElementException:
        return attachments

    scroll_into_view(driver, vp)
    try:
        vp.click()
    except Exception:
        driver.execute_script("arguments[0].click();", vp)

    table_xpath = "//table[.//th[normalize-space()='Attached File']]"

    # 2) Wait for attachments table to appear
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located(
                (By.XPATH, table_xpath + "//tbody/tr[.//td]")
            )
        )
    except TimeoutException:
        # If it never loads, go back to detail page
        driver.get(detail_url)
        time.sleep(2)
        return attachments

    def current_rows():
        # always fetch fresh rows to avoid stale references
        return driver.find_elements(
            By.XPATH, table_xpath + "//tbody/tr[.//td]"
        )

    idx = 0
    while True:
        rows = current_rows()
        if idx >= len(rows):
            break

        tr = rows[idx]
        idx += 1

        try:
            # 3) Find something clickable in the Download column

            clickable = None

            # common: button with fa-download icon
            btns = tr.find_elements(
                By.XPATH,
                ".//td[last()]//button[.//*[contains(@class,'fa-download')]]"
            )
            if btns:
                clickable = btns[0]

            # icon inside link/button
            if clickable is None:
                icons = tr.find_elements(
                    By.XPATH,
                    ".//td[last()]//*[contains(@class,'fa-download')]"
                )
                if icons:
                    try:
                        parent = icons[0].find_element(
                            By.XPATH, "ancestor::a[1] | ancestor::button[1]"
                        )
                        clickable = parent
                    except NoSuchElementException:
                        clickable = icons[0]

            # fallback: any button or link in last cell
            if clickable is None:
                btn_or_link = tr.find_elements(
                    By.XPATH, ".//td[last()]//button | .//td[last()]//a"
                )
                if btn_or_link:
                    clickable = btn_or_link[0]

            if clickable is None:
                # nothing clickable for this attachment row
                continue

            scroll_into_view(driver, clickable)
            try:
                clickable.click()
            except Exception:
                driver.execute_script("arguments[0].click();", clickable)

            # 4) Wait for the popup with Download Attachment
            try:
                WebDriverWait(driver, 15).until(
                    EC.visibility_of_element_located(
                        (By.ID, "downloadButton")
                    )
                )
            except TimeoutException:
                # try close any popup if half-open, then continue
                try:
                    close = driver.find_element(
                        By.XPATH,
                        "//button[contains(normalize-space(),'Close')]"
                    )
                    try:
                        close.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", close)
                except NoSuchElementException:
                    pass
                continue

            # 5) Grab the href from Download Attachment
            try:
                a = driver.find_element(By.ID, "downloadButton")
                href = (a.get_attribute("href") or "").strip()
                if href and href != "#" and href not in attachments:
                    attachments.append(href)
            except NoSuchElementException:
                pass

            # 6) Close popup
            try:
                close = driver.find_element(
                    By.XPATH,
                    "//button[contains(normalize-space(),'Close')]"
                )
                try:
                    close.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", close)
            except NoSuchElementException:
                # fallback: ESC
                driver.execute_script(
                    "var e = new KeyboardEvent('keydown', {key:'Escape'});"
                    "document.dispatchEvent(e);"
                )

            time.sleep(0.25)

        except StaleElementReferenceException:
            # row changed; just move on to next index
            continue
        except Exception as e:
            print(f"[WARN] attachment row {idx} error: {e}")
            # best-effort close popup if any, then continue
            try:
                close = driver.find_element(
                    By.XPATH,
                    "//button[contains(normalize-space(),'Close')]"
                )
                try:
                    close.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", close)
            except NoSuchElementException:
                pass
            continue

    # 7) Go back to Event Details page
    try:
        ret = driver.find_element(
            By.XPATH,
            "//a[normalize-space()='Return']"
            " | //button[normalize-space()='Return']"
        )
        scroll_into_view(driver, ret)
        try:
            ret.click()
        except Exception:
            driver.execute_script("arguments[0].click();", ret)
        time.sleep(2)
    except NoSuchElementException:
        driver.get(detail_url)
        time.sleep(2)

    return attachments

# ================== Event Name from details page ==================

def get_event_name_from_details_page(driver) -> Optional[str]:
    # 1) explicit data-label
    try:
        el = driver.find_element(
            By.XPATH,
            "//*[@data-label='eventName' and normalize-space()!='']"
        )
        t = clean_text(raw_text(el))
        if t and t.lower() not in ("event details", "details"):
            return t
    except NoSuchElementException:
        pass

    # 2) visual bold h3
    try:
        el = driver.find_element(
            By.XPATH,
            "(//h3[contains(@class,'h2') and contains(@class,'bold') and normalize-space()!=''][1])"
        )
        t = clean_text(raw_text(el))
        if t and t.lower() not in ("event details", "details"):
            return t
    except NoSuchElementException:
        pass

    # 3) nearest element above Details
    try:
        el = driver.find_element(
            By.XPATH,
            "(//h2[normalize-space()='Details']/preceding::*[normalize-space()!=''][1])"
        )
        t = clean_text(raw_text(el))
        if t and t.lower() not in ("event details", "details"):
            return t
    except NoSuchElementException:
        pass

    return None

# ================== aggregate event extraction ==================

def extract_event_details(driver, list_row_event_name: str) -> Optional[Dict]:
    if "loading.html" in driver.current_url:
        return None

    data: Dict[str, object] = {}

    details = extract_label_values(driver)

    # Event Name: prefer details-page title, else list-row Event Name
    event_name = get_event_name_from_details_page(driver)
    if not event_name:
        event_name = clean_text(list_row_event_name) or ""
    if not event_name:
        event_name = "Unknown Event Name"

    data["Event Name"] = event_name
    data["Details"] = details

    contact = extract_contact_info(driver)
    if contact:
        data["Contact Information"] = contact

    prebid = extract_prebid(driver)
    if prebid:
        data["Pre Bid Conference"] = prebid

    desc = extract_full_description(driver)
    if desc:
        data["Description"] = desc

    unspsc = extract_unspsc(driver)
    if unspsc:
        data["UNSPSC Codes"] = unspsc

    attachments = get_attachments(driver)
    if attachments:
        data["Attachments"] = attachments

    data["Detail URL"] = driver.current_url

    return data

# ================== pagination ==================

def click_next_if_available(driver) -> bool:
    for xp in [
        "//a[normalize-space()='Next' and not(contains(@class,'disabled'))]",
        "//button[normalize-space()='Next' and not(contains(@class,'disabled'))]",
        "//*[contains(@class,'pagination')]//*[contains(.,'Next') and not(contains(@class,'disabled'))]",
    ]:
        try:
            btn = driver.find_element(By.XPATH, xp)
            if btn.is_displayed() and btn.is_enabled():
                scroll_into_view(driver, btn)
                try:
                    btn.click()
                except ElementNotInteractableException:
                    driver.execute_script("arguments[0].click();", btn)
                time.sleep(0.8)
                goto_events_section(driver)
                return True
        except NoSuchElementException:
            continue
    return False

# ================== main loop ==================

def process_all(driver, max_pages=0, limit: int = 0) -> List[Dict]:
    all_events: List[Dict] = []
    page_idx = 0

    while True:
        page_idx += 1
        # Always ensure we are on the search page + EVENTS table
        if "event-search.aspx" not in driver.current_url:
            driver.get(START_URL)
            time.sleep(3)
        goto_events_section(driver)

        rows = get_event_rows(driver)
        print(f"[INFO] Page {page_idx}: Found {len(rows)} rows")

        for i in range(len(rows)):
            if limit and len(all_events) >= limit:
                return all_events

            # Re-grab rows each time (in case DOM changed)
            rows = get_event_rows(driver)
            if i >= len(rows):
                break

            row = rows[i]
            tds = row.find_elements(By.XPATH, ".//td")
            if len(tds) < 2:
                continue

            time.sleep(1.0)
            event_name = get_event_name_from_row(row)
            print(f"[ROW {i+1}] {event_name[:120]}")

            clickable, url_guess = row_click_target_and_url(row)
            robust_open_new_tab(driver, clickable, url_guess)

            if not ensure_event_loaded_or_skip(driver):
                # Close whatever tab we opened and go back to search
                if len(driver.window_handles) > 1:
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                # If we somehow lost the search page, reopen it
                if "event-search.aspx" not in driver.current_url:
                    driver.get(START_URL)
                    time.sleep(3)
                continue

            data = extract_event_details(driver, event_name)
            if data:
                all_events.append(data)

            # Close detail tab and return to search page
            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])

            # Hard guarantee: if we are not on search page now, reopen it
            if "event-search.aspx" not in driver.current_url:
                driver.get(START_URL)
                time.sleep(3)

            time.sleep(0.25)

            if limit and len(all_events) >= limit:
                return all_events

        # pagination / exit
        if max_pages and page_idx >= max_pages:
            break
        if not click_next_if_available(driver):
            break

    return all_events

# ================== entrypoint ==================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--initial-wait", type=float, default=10.0)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    driver = build_driver(headless=args.headless)
    try:
        print("[STEP] Open search page…")
        driver.get(START_URL)
        time.sleep(max(0, args.initial_wait))

        print("[STEP] Scrape results…")
        results = process_all(
            driver,
            max_pages=args.max_pages,
            limit=args.limit,
        )

        print(f"[OK] Total events scraped: {len(results)}")
        with open(args.out_json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"[OK] Saved JSON: {args.out_json}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()