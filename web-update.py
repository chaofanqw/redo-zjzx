import gradio as gr
import os
import sqlite3
import pandas as pd
import json

# --- Configuration ---
DATABASE_FILE = "resource/output/answers.db"
WRONG_ANSWERS_FILE = "resource/output/wrong_answers.json"


def load_data(db_file, wrong_answers_file):
    """
    Loads exam data from the SQLite database and wrong answer history from a JSON file.
    It restructures the database table into a nested dictionary for the UI.
    """
    if not os.path.exists(db_file):
        raise FileNotFoundError(f"Database not found at {db_file}. Please run the scraping script first.")

    conn = sqlite3.connect(db_file)
    try:
        # Load all questions from the database
        df = pd.read_sql_query("SELECT * FROM questions", conn)
    finally:
        conn.close()

    # Convert the 'options' column from JSON strings to dictionaries
    df['options'] = df['options'].apply(lambda x: json.loads(x) if isinstance(x, str) else {})

    # Restructure the flat DataFrame into a nested dictionary: {subject: {paper: {type: {num: ...}}}}
    exam_data = {}
    for _, row in df.iterrows():
        subject = row['subject']
        # Ensure the exam paper ID is a string to match dropdown values
        paper = str(row['exam_paper_id'])
        q_type = row['question_type']
        q_id = str(row['question_id'])

        # Create nested dictionaries if they don't exist
        s = exam_data.setdefault(subject, {})
        p = s.setdefault(paper, {})
        t = p.setdefault(q_type, {})

        # Populate the question data
        t[q_id] = {
            'question': row['question_text'],
            'choices': [f"{k}. {v}" for k, v in row['options'].items()] if row['options'] else ['对', '错'],
            'answer': row['correct_answer']
        }

    # Load the history of wrong answers
    if os.path.exists(wrong_answers_file):
        with open(wrong_answers_file, 'r', encoding='utf-8') as f:
            wrong_answers = json.load(f)
    else:
        wrong_answers = {}
    return exam_data, wrong_answers


def submit_answer(question_choice, answer_state):
    """Handles answer submission, checks correctness, and updates wrong answer history."""
    _, wrong_answers = load_data(DATABASE_FILE, WRONG_ANSWERS_FILE)

    # FIX: The 'answer_state' parameter is the gr.State object itself, not its value.
    # We need to access the stored dictionary through the .value attribute.
    state_value = answer_state.value

    subject = str(state_value['subject'])
    exam_paper = str(state_value['exam_paper'])
    section = state_value['section']
    question_id = str(state_value['question_id'])
    correct_answer_str = state_value['correct_answer']

    # Standardize user's choice(s)
    user_answer = ""
    if section == '多选题':
        # For multiple choice, sort the chosen letters and join them
        user_answer = "".join(sorted([c.split('.')[0] for c in question_choice]))
    elif question_choice:
        # For single choice, get the letter
        user_answer = question_choice.split('.')[0]

    # Check if the answer is correct
    is_correct = (user_answer == correct_answer_str)

    dialog = ""
    if is_correct:
        dialog = f"<p style='color:green; font-weight:bold;'>回答正确！答案是：{correct_answer_str}</p>"
    else:
        dialog = f"<p style='color:red; font-weight:bold;'>回答错误。正确答案是：{correct_answer_str}</p>"

    # Update wrong answer log
    # Ensure nested keys exist
    paper_log = wrong_answers.setdefault(subject, {}).setdefault(exam_paper, {})
    section_log = paper_log.setdefault(section, {'correct_ids': []})

    correct_ids = section_log.get('correct_ids', [])
    if is_correct and question_id not in correct_ids:
        correct_ids.append(question_id)
    elif not is_correct and question_id in correct_ids:
        correct_ids.remove(question_id)

    section_log['correct_ids'] = sorted(list(set(correct_ids)))  # Ensure uniqueness and order

    # Save updated history
    with open(WRONG_ANSWERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(wrong_answers, f, ensure_ascii=False, indent=4)

    return gr.HTML(dialog, visible=True)


def make_components(section_label, max_questions=50):
    """Pre-builds all necessary Gradio components for a given section."""
    info = {'label': section_label, 'num': max_questions, 'component': {}}
    info['component']['accordion'] = gr.Accordion(label=info['label'], visible=False)
    with info['component']['accordion']:
        for i in range(1, info['num'] + 1):
            q_key = str(i)
            info['component'][q_key] = {}
            with gr.Accordion(f'题目 {i}', visible=False) as acc:
                info['component'][q_key]['label'] = acc
                if section_label == '多选题':
                    info['component'][q_key]['question'] = gr.CheckboxGroup(visible=True)
                else:
                    info['component'][q_key]['question'] = gr.Radio(visible=True)
                info['component'][q_key]['submission'] = gr.Button("提交答案")
                info['component'][q_key]['answer_state'] = gr.State()
                info['component'][q_key]['answer_dialog'] = gr.HTML(visible=False)

            info['component'][q_key]['submission'].click(submit_answer,
                                                         inputs=[info['component'][q_key]['question'],
                                                                 info['component'][q_key]['answer_state']],
                                                         outputs=[info['component'][q_key]['answer_dialog']])
    return info


def load_section_ui(subject, exam_paper, mode, section, exam_data, wrong_answers, section_components):
    """Updates the UI for a specific section based on the selected mode."""
    # Get all questions for the selected subject, paper, and section
    question_data = exam_data.get(str(subject), {}).get(str(exam_paper), {}).get(section, {})
    question_ids = list(question_data.keys())

    # Filter questions based on the selected mode
    required_questions = []
    if mode == '正常答题':
        required_questions = question_ids
    elif mode in ['错题重答', '错题集']:
        correctly_answered_ids = wrong_answers.get(str(subject), {}).get(str(exam_paper), {}).get(section, {}).get(
            'correct_ids', [])
        required_questions = [qid for qid in question_ids if qid not in correctly_answered_ids]

    # If no questions to display, hide the whole section accordion
    if not required_questions:
        return {section_components['component']['accordion']: gr.Accordion(visible=False)}

    # Dictionary to hold all the UI updates
    updated_components = {section_components['component']['accordion']: gr.Accordion(visible=True, open=True)}

    # Hide all question accordions initially
    for i in range(1, section_components['num'] + 1):
        updated_components[section_components['component'][str(i)]['label']] = gr.Accordion(visible=False)

    # Loop through the questions that need to be displayed
    for idx, qid in enumerate(required_questions):
        component_key = str(idx + 1)
        question_info = question_data[qid]

        q_text = f"{idx + 1}. {question_info['question']} (id: {qid})"
        choices = question_info.get('choices', ['对', '错'])
        correct_answer = question_info['answer']

        # Determine the UI state based on the mode
        interactive = (mode != '错题集')
        show_answer_value = None

        # In '错题集' mode, find the full text of the correct answer(s) to display
        if mode == '错题集':
            if section == '多选题':
                # For CheckboxGroup, the value is a list of choice strings
                show_answer_value = [c for c in choices if c and c.split('.')[0] in correct_answer]
            else:
                # For Radio, the value is a single choice string. Find the choice that starts with the correct answer.
                # This handles both 'A' and '对' style answers.
                correct_choices = [c for c in choices if c and c.startswith(correct_answer)]
                if correct_choices:
                    show_answer_value = correct_choices[0]

        question_component_type = gr.CheckboxGroup if section == '多选题' else gr.Radio
        question_ui = question_component_type(
            label=q_text,
            choices=choices,
            value=show_answer_value,
            interactive=interactive,
            visible=True
        )

        # The state object holds all necessary info for answer submission
        state_obj = gr.State(value={'subject': subject, 'exam_paper': exam_paper, 'section': section,
                                    'question_id': qid, 'correct_answer': correct_answer})

        # Update the dictionary with the new components for this question
        updated_components[section_components['component'][component_key]['label']] = gr.Accordion(visible=True,
                                                                                                   open=True)
        updated_components[section_components['component'][component_key]['question']] = question_ui
        updated_components[section_components['component'][component_key]['submission']] = gr.Button(
            visible=interactive)
        updated_components[section_components['component'][component_key]['answer_state']] = state_obj
        updated_components[section_components['component'][component_key]['answer_dialog']] = gr.HTML(visible=False)

    return updated_components


def load_all_sections_ui(subject, exam_paper, mode):
    """Loads and updates the UI for all question sections."""
    exam_data, wrong_answers = load_data(DATABASE_FILE, WRONG_ANSWERS_FILE)
    updated_components = {}

    # Process each section type
    for section_name, section_components in components.items():
        section_ui_updates = load_section_ui(subject, exam_paper, mode, section_name, exam_data, wrong_answers,
                                             section_components)
        updated_components.update(section_ui_updates)

    return updated_components


def get_all_components_flat(components_dict):
    """Flattens the component dictionary into a single list for Gradio outputs."""
    result = []
    for section_info in components_dict.values():
        result.append(section_info['component']['accordion'])
        for i in range(1, section_info['num'] + 1):
            q_comps = section_info['component'][str(i)]
            # Ensure keys exist before extending
            if 'label' in q_comps:
                result.extend(q_comps.values())
    return result


def export_data_to_files():
    """Exports the cleaned database content to Markdown and Excel files."""
    output_path = './resource/output/'
    os.makedirs(output_path, exist_ok=True)

    exam_data, wrong_answers = load_data(DATABASE_FILE, WRONG_ANSWERS_FILE)

    for subject in exam_data:
        rows = []
        for exam_paper in exam_data[subject]:
            for section in exam_data[subject][exam_paper]:
                question_data = exam_data[subject][exam_paper][section]
                correct_list = wrong_answers.get(str(subject), {}).get(str(exam_paper), {}).get(section, {}).get(
                    'correct_ids', [])

                for qid, q_info in question_data.items():
                    correct_status = '是' if qid in correct_list else '否'
                    rows.append({
                        '试卷ID': exam_paper,
                        '题型': section,
                        '题目ID': qid,
                        '题目': q_info['question'],
                        '选项': " | ".join(q_info['choices']),
                        '答案': q_info['answer'],
                        '曾回答正确': correct_status
                    })

        df = pd.DataFrame(rows)
        if not df.empty:
            df.to_excel(f'{output_path}{subject}.xlsx', index=False)
            df.to_markdown(f'{output_path}{subject}.md', index=False)

    gr.Info("Data export successful!")


def build_gradio_ui(exam_data):
    """Constructs the main Gradio application UI."""
    global components
    with gr.Blocks(theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 考试练习平台", elem_id="title")
        with gr.Row():
            # Get the first subject and its papers for initial dropdown values
            first_subject = list(exam_data.keys())[0] if exam_data else None
            initial_papers = list(exam_data.get(first_subject, {}).keys())

            subject_dropdown = gr.Dropdown(
                label="科目",
                choices=list(exam_data.keys()),
                value=first_subject,
                interactive=True
            )
            exam_paper_dropdown = gr.Dropdown(
                label="试卷",
                choices=initial_papers,
                value=initial_papers[0] if initial_papers else None,
                interactive=True
            )
            mode_dropdown = gr.Dropdown(
                label="模式", choices=["正常答题", "错题重答", "错题集"], value="正常答题", interactive=True
            )

        with gr.Row():
            load_button = gr.Button("加载试题", variant="primary")
            export_button = gr.Button("导出数据")

        # Pre-build component structure for all sections
        components = {
            '单选题': make_components('单选题'),
            '多选题': make_components('多选题'),
            '判断题': make_components('判断题')
        }

        # Define UI interactions
        def update_paper_choices(subject):
            choices = list(exam_data.get(subject, {}).keys())
            return gr.Dropdown(choices=choices, value=choices[0] if choices else None)

        subject_dropdown.change(fn=update_paper_choices, inputs=subject_dropdown, outputs=exam_paper_dropdown)

        load_button.click(load_all_sections_ui,
                          inputs=[subject_dropdown, exam_paper_dropdown, mode_dropdown],
                          outputs=get_all_components_flat(components))

        export_button.click(export_data_to_files)

    demo.launch()


if __name__ == '__main__':
    try:
        # Load the initial data to populate the dropdowns
        initial_exam_data, _ = load_data(DATABASE_FILE, WRONG_ANSWERS_FILE)
        build_gradio_ui(initial_exam_data)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Please ensure the scraping script has been run and the database file exists.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

