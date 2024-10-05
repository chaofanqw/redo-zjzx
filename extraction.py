import os

import requests
from bs4 import BeautifulSoup

import json


def extract_html(base_url, url, stored_dir='./resource/web'):
    stored_path = os.path.join(stored_dir, url)
    url = base_url + url
    if os.path.exists(stored_path):
        with open(stored_path, 'r', encoding='gbk') as f:
            return f.read()
    else:
        response = requests.get(url)
        content = response.content
        with open(stored_path, 'wb') as f:
            f.write(content)
        return content


def extract_content(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')

    # Extract exam sheet number
    exam_sheet_select = soup.find('select', {'id': 'drop2'})
    selected_option = exam_sheet_select.find('option', {'selected': 'selected'})
    exam_sheet_number = selected_option.text.strip()

    # Extract single choice questions
    single_choice_questions = {}
    gridview1 = soup.find('table', {'id': 'GridView1'})
    if gridview1:
        rows = gridview1.find_all('tr')[1:]  # Skip header row
        for row in rows:
            tds = row.find_all('td')
            if tds:
                question_table = tds[0].find('table', {'class': 't1'})
                if question_table:
                    q_number = question_table.find('span', id=lambda x: x and x.endswith('Label11')).text.strip().strip(
                        '、')
                    question_text = question_table.find('span', class_='ques').text.strip()
                    answer_span = question_table.find('span', id=lambda x: x and x.endswith('Label6'))
                    answer = answer_span.text.strip() if answer_span else ''
                    choices = []
                    options = question_table.find_all('span', id=lambda x: x and x.endswith(
                        ('Label2', 'Label3', 'Label4', 'Label5')))
                    for option in options:
                        choices.append(option.text.strip())
                    single_choice_questions[q_number] = {
                        'question': question_text,
                        'answer': answer,
                        'choices': choices
                    }

    # Extract multiple choice questions
    multiple_choice_questions = {}
    gridview2 = soup.find('table', {'id': 'GridView2'})
    if gridview2:
        rows = gridview2.find_all('tr')[1:]  # Skip header row
        for row in rows:
            tds = row.find_all('td')
            if tds:
                question_table = tds[0].find('table', {'class': 't1'})
                if question_table:
                    q_number = question_table.find('span', id=lambda x: x and x.endswith('Label14')).text.strip().strip(
                        '、')
                    question_text = question_table.find('span', id=lambda x: x and x.endswith('Label15')).text.strip()
                    answer_span = question_table.find('span', id=lambda x: x and x.endswith('Label16'))
                    answer = answer_span.text.strip() if answer_span else ''
                    choices = []
                    options = question_table.find_all('span', id=lambda x: x and x.endswith(
                        ('Label17', 'Label18', 'Label19', 'Label20', 'Label21', 'Label22')))
                    for option in options:
                        choice_text = option.text.strip()
                        if choice_text:
                            choices.append(choice_text)
                    multiple_choice_questions[q_number] = {
                        'question': question_text,
                        'answer': answer,
                        'choices': choices
                    }

    # Extract true/false questions
    true_false_questions = {}
    gridview3 = soup.find('table', {'id': 'GridView3'})
    if gridview3:
        rows = gridview3.find_all('tr')[1:]  # Skip header row
        for row in rows:
            tds = row.find_all('td')
            if tds:
                question_table = tds[0].find('table', id='t3')
                if question_table:
                    q_number = question_table.find('span', id=lambda x: x and x.endswith('Label39')).text.strip().strip(
                        '、')
                    question_text = question_table.find('span', id=lambda x: x and x.endswith('Label40')).text.strip()
                    answer_span = question_table.find('span', id=lambda x: x and x.endswith('Label41'))
                    answer = answer_span.text.strip() if answer_span else ''
                    true_false_questions[q_number] = {
                        'number': q_number,
                        'question': question_text,
                        'answer': answer
                    }

    return exam_sheet_number, {
        '单选题': single_choice_questions,
        '多选题': multiple_choice_questions,
        '判断题': true_false_questions
    }


def extract_form(html_content):
    # Extract all forms named as 'form1'
    soup = BeautifulSoup(html_content, 'html.parser')
    forms = soup.find_all('form', {'name': 'form1'})
    results = {}
    for form in forms:
        exam_num, result = extract_content(form.prettify())
        results[exam_num] = result
    return results


def extract_htmls(base_url, urls, stored_dir='./resource/web'):
    results = {}
    for url in urls.keys():
        result = extract_html(base_url, url, stored_dir)
        results[urls[url]] = extract_form(result)

    # Save the results to a file as utf-8 encoding
    with open('./resource/exam.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=4)


if __name__ == '__main__':
    base_url = 'http://www.hzwolf.com/'
    URLS = {'dxxlx.htm': '大学心理学',
            'gdjyfg.htm': '高等教育法规',
            'gdjyx.htm': '高等教育学',
            'jsllx.htm': '教师伦理学'}

    extract_htmls(base_url, URLS)
