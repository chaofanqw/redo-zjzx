import gradio as gr

import os
import json

import pandas as pd


def load_data(exam_data_path, wrong_answers_file):
    exam_data = open(exam_data_path, 'r', encoding='utf-8')
    exam_data = json.load(exam_data)
    if os.path.exists(wrong_answers_file):
        with open(wrong_answers_file, 'r', encoding='utf-8') as f:
            wrong_answers = json.load(f)
    else:
        wrong_answers = {}
    return exam_data, wrong_answers


def submit_answer(question, answer):
    _, wrong_answers = load_data(exam_data_path, wrong_answers_file)
    answer = answer.value
    previous_state = wrong_answers.get(answer['subject'], {}).get(answer['exam_paper'], {}).get(answer['section'], {})
    correct_list = previous_state.get('正确', [])
    correct_answer = answer['answer'] if answer['section'] != '多选题' else ''.join([i[0] for i in answer['answer']])
    question = sorted(question) if isinstance(question, list) else question

    if question == answer['answer']:
        dialog = f"<p style='color:green'>正确，答案：{correct_answer}</p>"
        correct_list.append(answer['num'])
    else:
        dialog = f"<p style='color:red'>错误，答案：{correct_answer}</p>"
        if answer['num'] in correct_list:
            correct_list.remove(answer['num'])

    wrong_answers.setdefault(answer['subject'], {}) \
        .setdefault(answer['exam_paper'], {}) \
        [answer['section']] = {'正确': correct_list}
    with open(wrong_answers_file, 'w', encoding='utf-8') as f:
        json.dump(wrong_answers, f, ensure_ascii=False, indent=4)

    return gr.HTML(dialog, visible=True)


def make_components(num, label):
    info = {'label': label, 'num': num, 'component': {}}
    info['component']['accordion'] = gr.Accordion(label=info['label'], visible=False)
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
                info['component'][i]['answer_dialog'] = gr.HTML(visible=False)

            info['component'][i]['submission'].click(submit_answer,
                                                     inputs=[info['component'][i]['question'],
                                                             info['component'][i]['answer']],
                                                     outputs=[info['component'][i]['answer_dialog']])
    return info


def load_section(subject, exam_paper, mode, section, exam_data, wrong_answers):
    question_data = exam_data.get(subject, {}).get(exam_paper, {}).get(section, {})
    question_nums = list(question_data.keys())

    if mode == '正常答题':
        required_questions = question_nums
    else:
        tmp = wrong_answers.get(subject, {}).get(exam_paper, {}).get(section, {}).get('正确', [])
        required_questions = [num for num in question_nums if num not in tmp]

    if len(required_questions) == 0:
        return {components[section]['component']['accordion']: gr.Accordion(visible=False)}

    updated_components = {components[section]['component']['accordion']: gr.Accordion(visible=True)}
    for num in question_nums:
        question = question_data[num]['question']
        choices = question_data[num].get('choices', ['对', '错'])
        answer = [choice for choice in choices for each in question_data[num]['answer'] if choice.startswith(each)]

        button = gr.Button(visible=True)
        accordion = gr.Accordion(visible=False)
        state = gr.State(value={'subject': subject, 'exam_paper': exam_paper, 'section': section, 'num': num,
                                'answer': answer if section == '多选题' else answer[0]})

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
        updated_components[components[section]['component'][num]['answer']] = state
        updated_components[components[section]['component'][num]['answer_dialog']] = gr.HTML(visible=False)

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
        result.extend([components[section]['component']['accordion']])
        for question in questions:
            if question != 'accordion':
                result.extend(list(components[section]['component'][question].values()))

    return result


def offload_markdown(output_path='./resource/output/'):
    if not os.path.exists(output_path):
        os.mkdir(output_path)
    exam_data, wrong_answers = load_data(exam_data_path, wrong_answers_file)

    for subject in exam_data:
        # make dataframe with following info 试卷|题型|题号|题目|选项|答案|曾回答正确
        rows = []

        # make a markdown table with question, choices, answer, and correctness
        markdown = '试卷|题型|题号|题目|选项|答案|曾回答正确|\n'
        markdown += '|----|----|----|----|----|----|----|\n'  # Separator line

        for exam_paper in exam_data[subject]:
            for section in exam_data[subject][exam_paper]:
                question_data = exam_data[subject][exam_paper][section]
                question_nums = list(question_data.keys())
                correct_list = wrong_answers.get(subject, {}).get(exam_paper, {}).get(section, {}).get('正确', [])
                for num in question_nums:
                    question = question_data[num]['question']
                    choices = question_data[num].get('choices', [])
                    answer = question_data[num]['answer']
                    correct = '<p style="color:green">是</p>' if num in correct_list else '<p style="color:red">否</p>'

                    # Escape special characters
                    question = question.replace('|', '\\|').replace('\n', ' ')
                    choices = ' '.join(choices).replace('|', '\\|').replace('\n', ' ')
                    answer = str(answer).replace('|', '\\|').replace('\n', ' ')

                    # Append to markdown
                    markdown += f"|{exam_paper}|{section}|{num}|{question}|{choices}|{answer}|{correct}|\n"
                    rows.append({'试卷': exam_paper, '题型': section, '题号': num, '题目': question, '选项': choices,
                                 '答案': answer, '曾回答正确': '是' if num in correct_list else '否'})

        with open(f'{output_path}{subject}.md', 'w', encoding='utf-8') as f:
            f.write(markdown)
        pd.DataFrame(rows, columns=['试卷', '题型', '题号', '题目', '选项', '答案', '曾回答正确']). \
            to_excel(f'{output_path}{subject}.xlsx', index=False)

    gr.Info("Markdown, Excel导出成功")


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
            offload_button = gr.Button("导出Markdown")

        components = {'单选题': make_components(40, '单选题'),
                      '多选题': make_components(40, '多选题'),
                      '判断题': make_components(40, '判断题')}

        subject_dropdown.change(fn=lambda x: gr.Dropdown(choices=list(exam_data[x].keys())),
                                inputs=[subject_dropdown],
                                outputs=[exam_paper_dropdown])
        load_button.click(load_sections,
                          inputs=[subject_dropdown, exam_paper_dropdown, mode_dropdown],
                          outputs=load_components(components))
        offload_button.click(offload_markdown)

    demo.launch()


if __name__ == '__main__':
    exam_data_path = 'resource/exam.json'
    wrong_answers_file = 'resource/wrong_answers.json'
    exam_data, wrong_answers = load_data(exam_data_path, wrong_answers_file)
    load_website(exam_data)
