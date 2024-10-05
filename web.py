import gradio as gr

import os
import json


def load_data(exam_data_path, wrong_answers_file):
    exam_data = open(exam_data_path, 'r', encoding='utf-8')
    exam_data = json.load(exam_data)
    if os.path.exists(wrong_answers_file):
        with open(wrong_answers_file, 'r', encoding='utf-8') as f:
            wrong_answers = json.load(f)
    else:
        wrong_answers = {}
    return exam_data, wrong_answers


def make_components(num, label):
    info = {'label': label, 'num': num, 'component': {}}
    info['component']['accordion'] = gr.Accordion(label=info['label'])
    with info['component']['accordion']:
        for i in range(1, info['num'] + 1):
            i = str(i)
            info['component'][i] = {}
            info['component'][i]['label'] = gr.Accordion(f'第{i}题', visible=False)
            with info['component'][i]['label']:
                if label == '单选题':
                    info['component'][i]['question'] = gr.Radio(visible=True)
                elif label == '多选题':
                    info['component'][i]['question'] = gr.CheckboxGroup(visible=True)
                else:
                    info['component'][i]['question'] = gr.Radio(visible=True)
                info['component'][i]['submission'] = gr.Button("提交答案")
                info['component'][i]['answer'] = gr.State()
                info['component'][i]['answer_dialog'] = gr.Markdown(visible=False)
    return info


def load_section(subject, exam_paper, mode, section, exam_data, wrong_answers):
    question_data = exam_data.get(subject, {}).get(exam_paper, {}).get(section, {})
    question_nums = list(question_data.keys())

    if mode == '正常答题':
        required_questions = question_nums
    else:
        required_questions = wrong_answers.get(subject, {}).get(exam_paper, {}).get(section, [])
    print(mode, section, required_questions)

    updated_components = {}
    for num in question_nums:
        question = question_data[num]['question']
        choices = question_data[num].get('choices', ['对', '错'])
        answer = [choice for choice in choices for each in question_data[num]['answer'] if choice.startswith(each)]

        button = gr.Button(visible=True)
        accordion = gr.Accordion(visible=False)

        if num in required_questions:
            accordion = gr.Accordion(visible=True)

        if mode == '错题集':
            if section == '多选题':
                question = gr.CheckboxGroup(label=question,
                                            choices=choices,
                                            value=answer,
                                            interactive=False,
                                            visible=True)
            else:
                question = gr.Radio(label=question,
                                    choices=choices,
                                    value=answer[0],
                                    interactive=False,
                                    visible=True)
            button = gr.Button(visible=False)
        else:
            if section == '多选题':
                question = gr.CheckboxGroup(label=question,
                                            choices=choices,
                                            value=[],
                                            interactive=True,
                                            visible=True)
            else:
                question = gr.Radio(label=question,
                                    choices=choices,
                                    value=None,
                                    interactive=True,
                                    visible=True)

        updated_components[components[section]['component'][num]['label']] = accordion
        updated_components[components[section]['component'][num]['question']] = question
        updated_components[components[section]['component'][num]['submission']] = button
        updated_components[components[section]['component'][num]['answer']] = gr.State(value=answer)
        updated_components[components[section]['component'][num]['answer_dialog']] = gr.Markdown(visible=False)

    return updated_components


def load_sections(subject, exam_paper, mode):
    exam_data, wrong_answers = load_data(exam_data_path, wrong_answers_file)

    updated_components = {}
    for section in ['单选题', '多选题', '判断题']:
        tmp = load_section(subject, exam_paper, mode, section, exam_data, wrong_answers)
        updated_components.update(tmp)

    return updated_components


def load_components(components):
    result = []

    for section in components:
        questions = components[section]['component'].keys()
        for question in questions:
            if question != 'accordion':
                result.extend(list(components[section]['component'][question].values()))

    return result


def load_website(exam_data):
    global components
    with gr.Blocks() as demo:
        with gr.Row():
            subject_dropdown = gr.Dropdown(
                label="科目",
                choices=list(exam_data.keys()),
                value=list(exam_data.keys())[0],
                interactive=True
            )
            exam_paper_dropdown = gr.Dropdown(label="试卷",
                                              choices=list(exam_data[list(exam_data.keys())[0]].keys()),
                                              value=list(exam_data[list(exam_data.keys())[0]].keys())[0],
                                              interactive=True)
            mode_dropdown = gr.Dropdown(
                label="模式", choices=["正常答题", "错题重答", "错题集"], value="正常答题", interactive=True
            )
            load_button = gr.Button("加载试题")

        components = {'单选题': make_components(40, '单选题'),
                      '多选题': make_components(40, '多选题'),
                      '判断题': make_components(40, '判断题')}

        subject_dropdown.change(fn=lambda x: gr.Dropdown(choices=list(exam_data[x].keys())),
                                inputs=[subject_dropdown],
                                outputs=[exam_paper_dropdown])
        load_button.click(load_sections,
                          inputs=[subject_dropdown, exam_paper_dropdown, mode_dropdown],
                          outputs=load_components(components))

    demo.launch()


if __name__ == '__main__':
    exam_data_path = 'resource/exam.json'
    wrong_answers_file = 'resource/wrong_answers.json'
    exam_data, wrong_answers = load_data(exam_data_path, wrong_answers_file)
    load_website(exam_data)
