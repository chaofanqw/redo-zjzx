import time
import pickle
import os
import sqlite3
import json
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import WebDriverException, TimeoutException, StaleElementReferenceException, \
    NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import pandas as pd

# --- Configuration ---
TARGET_URL = "https://zjzx.zjnu.edu.cn/bm/exercise/index"
BASE_URL = "https://zjzx.zjnu.edu.cn/"
SESSION_FILE = "resource/output/zjnu_session.pkl"
DATABASE_FILE = "resource/output/answers.db"  # File for the SQLite database


def setup_database(db_file):
    """Creates/updates the SQLite database and tables for questions and completion tracking."""
    # Ensure the directory for the database exists
    os.makedirs(os.path.dirname(db_file), exist_ok=True)
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    # Main questions table with a composite primary key
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            question_id INTEGER NOT NULL,
            exam_paper_id INTEGER NOT NULL,
            subject TEXT NOT NULL,
            question_type TEXT,
            question_text TEXT NOT NULL,
            options TEXT,
            correct_answer TEXT,
            PRIMARY KEY (question_id, exam_paper_id)
        )
    """)

    # Table to track completed exams for resumability
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS completed_exams (
            exam_paper_id INTEGER PRIMARY KEY
        )
    """)
    conn.commit()
    print(f"Database '{db_file}' is ready.")
    return conn


def save_session_data(driver, location):
    """Saves cookies, local storage, and session storage to a single file."""
    # Ensure the directory for the session file exists
    os.makedirs(os.path.dirname(location), exist_ok=True)
    print("Saving session data...")
    storage_data = driver.execute_script("""
        const data = { localStorage: {}, sessionStorage: {} };
        for (let i = 0; i < localStorage.length; i++) data.localStorage[localStorage.key(i)] = localStorage.getItem(localStorage.key(i));
        for (let i = 0; i < sessionStorage.length; i++) data.sessionStorage[sessionStorage.key(i)] = sessionStorage.getItem(sessionStorage.key(i));
        return data;
    """)
    session_data = {'cookies': driver.get_cookies(), 'localStorage': storage_data['localStorage'],
                    'sessionStorage': storage_data['sessionStorage']}
    with open(location, "wb") as file:
        pickle.dump(session_data, file)
    print("Session data saved.")


def load_session_data(driver, location):
    """Loads cookies, local storage, and session storage from a file."""
    print("Loading session data...")
    with open(location, "rb") as file:
        session_data = pickle.load(file)

    # Go to the base domain to set cookies correctly
    driver.get(BASE_URL)
    # Clear existing cookies before loading saved ones to prevent conflicts
    driver.delete_all_cookies()

    # Load Cookies
    for cookie in session_data.get('cookies', []):
        try:
            driver.add_cookie(cookie)
        except Exception as e:
            print(f"Warning: Could not add cookie '{cookie.get('name', 'N/A')}'. Error: {e}")
    # Load Storage
    driver.execute_script("""
        const data = arguments[0];
        // Clear existing storage first
        localStorage.clear();
        sessionStorage.clear();
        // Load new storage items
        Object.keys(data.localStorage).forEach(key => localStorage.setItem(key, data.localStorage[key]));
        Object.keys(data.sessionStorage).forEach(key => sessionStorage.setItem(key, data.sessionStorage[key]));
    """, session_data)
    print("Session data loaded.")


def take_exam(driver, subject_name, exam_paper_id, db_conn):
    """
    Automates taking an exam, extracting question data, and saving it to the database.
    It cleans up partial data before starting and marks the exam as complete at the end.
    """
    wait = WebDriverWait(driver, 15)
    cursor = db_conn.cursor()
    try:
        # Clean up any partial data from a previous failed run for this exam
        print(f"    -> Cleaning up previous entries for exam ID {exam_paper_id} to ensure data integrity.")
        cursor.execute("DELETE FROM questions WHERE exam_paper_id = ?", (exam_paper_id,))
        db_conn.commit()

        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "st_right_bd")))
        print("    -> Exam page loaded. Finding questions...")

        question_cards = driver.find_elements(By.CSS_SELECTOR, ".st_right_bd .answerCard")
        num_questions = len(question_cards)
        print(f"    -> Found {num_questions} questions.")
        if num_questions == 0: return

        for i in range(num_questions):
            try:
                # Re-find elements each time to prevent stale element exceptions
                card = driver.find_elements(By.CSS_SELECTOR, ".st_right_bd .answerCard")[i]
                q_num_text = card.text.strip()
                question_id = int(card.get_attribute("qsid"))
                question_type = card.get_attribute("qstype")

                print(f"    -> Processing Question {q_num_text} ({i + 1}/{num_questions})...")

                driver.execute_script("arguments[0].click();", card)
                wait.until(EC.frame_to_be_available_and_switch_to_it((By.ID, "showQuestion")))

                # --- Inside iframe ---
                try:
                    question_text = wait.until(EC.visibility_of_element_located((By.CLASS_NAME, "sct_tit"))).text

                    # Selectors adjusted for different question types
                    if question_type == '多选题':
                        option_elements = driver.find_elements(By.CSS_SELECTOR, ".sct_answer .layui-form-item > div")
                    else:
                        option_elements = driver.find_elements(By.CSS_SELECTOR, ".sct_answer .layui-form-radio > div")

                    # Parsing logic for options based on question type
                    if question_type == '单选题' or question_type == '多选题':
                        options_dict = {opt.text[0]: opt.text[2:].strip() for opt in option_elements if
                                        len(opt.text) > 2}
                    else:  # Handle 判断题 (True/False)
                        options_dict = {opt.text: '' for opt in option_elements}

                    answer_element = driver.find_element(By.CSS_SELECTOR, '#answerDiv .color_green')
                    correct_answer = answer_element.get_attribute('textContent').strip()

                    # Use INSERT OR IGNORE to prevent errors on duplicate entries, thanks to the new composite PRIMARY KEY
                    cursor.execute("""
                        INSERT OR IGNORE INTO questions (question_id, exam_paper_id, subject, question_type, question_text, options, correct_answer)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (question_id, exam_paper_id, subject_name, question_type, question_text,
                          json.dumps(options_dict, ensure_ascii=False), correct_answer))
                    db_conn.commit()
                    print(f"       -> Saved question to database (ID: {question_id}, Exam: {exam_paper_id}).")

                except Exception as e:
                    print(f"       -> ERROR: Could not process question inside iframe. {e}")
                finally:
                    driver.switch_to.default_content()  # IMPORTANT: Always switch back
                time.sleep(0.5)

            except (StaleElementReferenceException, IndexError):
                print(f"       -> Stale element/index error for question card {i + 1}. Re-finding and continuing.")
                continue
            except Exception as e:
                print(f"       -> An error occurred processing question card {i + 1}: {e}")
                driver.switch_to.default_content()

        print("\n    -> All questions processed. Submitting exam.")
        submit_button = wait.until(EC.element_to_be_clickable((By.ID, "submitExercise")))
        driver.execute_script("arguments[0].click();", submit_button)
        time.sleep(1)

        try:
            WebDriverWait(driver, 5).until(EC.alert_is_present())
            alert = driver.switch_to.alert
            print(f"    -> Alert says: '{alert.text}'. Accepting.")
            alert.accept()
            # Wait for the report card to appear after accepting the alert
            wait.until(EC.presence_of_element_located((By.XPATH, "//span[text()='练习报告']")))
            print("    -> Practice report appeared.")
        except TimeoutException:
            print("    -> No confirmation alert or report appeared.")

        # Mark this exam as complete in the database
        print(f"    -> Marking exam paper ID {exam_paper_id} as complete.")
        cursor.execute("INSERT OR IGNORE INTO completed_exams (exam_paper_id) VALUES (?)", (exam_paper_id,))
        db_conn.commit()
        print("    -> Completion status saved.")

    except Exception as e:
        print(f"    -> ERROR: An unexpected error occurred while taking the exam: {e}")


def process_and_export_data(db_file):
    """
    Reads data from the database, cleans it by filling in missing options using a canonical
    version, standardizes answers, updates the database, and exports the result to Excel.
    """
    print("\n--- Starting post-processing of the database ---")
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    try:
        df = pd.read_sql_query("SELECT * FROM questions", conn)
    except Exception as e:
        print(f"Could not read from database: {e}")
        conn.close()
        return

    if df.empty:
        print("Database is empty. Nothing to process.")
        conn.close()
        return

    # Deserialize 'options' from JSON string to Python dict
    def safe_json_loads(x):
        try:
            return json.loads(x)
        except (json.JSONDecodeError, TypeError):
            return {}  # Return an empty dict for invalid/empty JSON

    df['options'] = df['options'].apply(safe_json_loads)

    # More robustly find the first non-empty option set for each question
    def find_first_valid_option(series):
        for item in series:
            if item and isinstance(item, dict) and item:  # Check it's a non-empty dictionary
                return item
        return {}  # Return empty dict if no valid option is found

    print("Finding canonical options for each question...")
    canonical_options_map = df.groupby('question_id')['options'].agg(find_first_valid_option)

    # Apply the map to fill in empty option dicts
    print("Refilling empty options and standardizing answers...")
    df['options'] = df.apply(
        lambda row: canonical_options_map.get(row['question_id'], {}) if not row['options'] else row['options'],
        axis=1
    )
    df['options'] = df.apply(lambda x: {"对": "", "错": ""} if x['question_type'] == '判断题' else x['options'], axis=1)

    # Standardize answers
    answer_map = {"正确": "对", "错误": "错"}
    df['correct_answer'] = df['correct_answer'].replace(answer_map)

    # Update the database with the cleaned data
    print("Updating database with cleaned data...")
    update_queue = []
    for index, row in df.iterrows():
        update_queue.append((
            json.dumps(row['options'], ensure_ascii=False),
            row['correct_answer'],
            row['question_id'],
            row['exam_paper_id']
        ))

    cursor.executemany("""
        UPDATE questions 
        SET options = ?, correct_answer = ? 
        WHERE question_id = ? AND exam_paper_id = ?
    """, update_queue)
    conn.commit()
    print("Database update complete.")

    # Export the cleaned DataFrame to an Excel file
    excel_path = "resource/output/answers.xlsx"
    print(f"Exporting cleaned data to '{excel_path}'...")
    # Convert options dict back to JSON string for a clean export
    df['options'] = df['options'].apply(lambda x: json.dumps(x, ensure_ascii=False))
    df.to_excel(excel_path, index=False)
    print("Export complete.")

    conn.close()


def main():
    """Main function to handle login and automate exams with resume capability."""
    db_conn = setup_database(DATABASE_FILE)
    options = webdriver.ChromeOptions()
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
    wait = WebDriverWait(driver, 10)

    try:
        if os.path.exists(SESSION_FILE):
            print("Found session file. Attempting auto-login.")
            load_session_data(driver, SESSION_FILE)
            driver.refresh()
            time.sleep(2)
        else:
            print("Session file not found. Please log in manually.")
            driver.get(BASE_URL)
            input("\n>>> After you have logged in, press Enter here to save your session...")
            save_session_data(driver, SESSION_FILE)

        print("\nNavigating to exercise page...")
        driver.get(TARGET_URL)
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "subjects")))

        cursor = db_conn.cursor()
        cursor.execute("SELECT exam_paper_id FROM completed_exams")
        completed_exam_ids = {row[0] for row in cursor.fetchall()}
        if completed_exam_ids:
            print(f"Found {len(completed_exam_ids)} previously completed exams. They will be skipped.")

        num_subjects = len(driver.find_elements(By.CSS_SELECTOR, "li.subject"))
        print(f"Found {num_subjects} subjects.")

        for i in range(num_subjects):
            subjects = driver.find_elements(By.CSS_SELECTOR, "li.subject")
            subject_name = subjects[i].find_element(By.TAG_NAME, "span").text
            print(f"\n--- Processing Subject [{i + 1}/{num_subjects}]: {subject_name} ---")

            options_list = subjects[i].find_elements(By.CSS_SELECTOR, "select > option")
            exam_data = [{'value': opt.get_attribute('value'), 'text': opt.text} for opt in options_list if
                         opt.get_attribute('value') and int(opt.get_attribute('value')) > 0]

            if not exam_data:
                print("  No exam papers found. Skipping.")
                continue

            print(f"  Found {len(exam_data)} exams.")
            for j, exam in enumerate(exam_data):
                exam_id = int(exam['value'])
                exam_name = exam['text']

                if exam_id in completed_exam_ids:
                    print(
                        f"  -> [{j + 1}/{len(exam_data)}] SKIPPING already completed exam '{exam_name}' (ID: {exam_id})")
                    continue

                try:
                    print(f"  -> [{j + 1}/{len(exam_data)}] Starting '{exam_name}' (ID: {exam_id})")
                    current_subject_element = driver.find_elements(By.CSS_SELECTOR, "li.subject")[i]
                    dropdown = Select(current_subject_element.find_element(By.TAG_NAME, "select"))
                    dropdown.select_by_value(exam['value'])
                    time.sleep(0.5)
                    current_subject_element.find_element(By.CSS_SELECTOR, "a.exercise").click()

                    take_exam(driver, subject_name, exam_id, db_conn)

                    print("    -> Navigating back to exercise list...")
                    driver.get(TARGET_URL)
                    wait.until(EC.visibility_of_element_located((By.CLASS_NAME, "subjects")))
                except Exception as e:
                    print(f"  An error occurred in the main exam loop: {e}")
                    driver.get(TARGET_URL)
                    wait.until(EC.visibility_of_element_located((By.CLASS_NAME, "subjects")))

        print("\n\nAutomation complete.")
        time.sleep(10)
    finally:
        db_conn.close()
        print("Database connection closed.")
        driver.quit()
        print("Browser closed.")


if __name__ == "__main__":
    main()
    process_and_export_data(DATABASE_FILE)
