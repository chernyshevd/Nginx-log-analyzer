#!/usr/bin/env python
# -*- coding: utf-8 -*-
import argparse
import datetime
import gzip
import json
import logging
import logging.config
import os
import pathlib
import re
import statistics
import string
import structlog
import sys
from typing import Dict, List, Optional, Any, Union
from collections import defaultdict


config = {
    'TEMPLATE_PATH': './reports/report.html',  # Шаблон исходного отчета
    'REPORT_SIZE': 100,  # Кол-во записей в итоговом отчете
    'REPORT_DIR': './reports',  # Путь куда пишется отчет
    'LOG_DIR': './log',  # Путь откуда читаются исходные логи
    'ERRORS_LIMIT_PERC': 5,  # Допустимая ошибка парсинга в %
    'SELF_LOG_PATH': './log/log_analyzer.log',  # Путь к собственныи логам программы
    'DEBUG_MODE': True,
    'TEST_SIZE': 1000
}


def parser_args() -> Dict[str, str]:
    """Парсер аргументов из командной строки"""

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='./config/config.json',
                        help='Parameter for passing the config, default=./config/config.json')
    args = parser.parse_args()

    return args.config


def get_result_config(default_config: Dict[str, str], config_path: str) -> Optional[Dict[str, str]]:
    """Получим результирующий конфиг"""
    try:
        with open(config_path, 'r') as config_file:
            result_config = json.load(config_file)
        return {**default_config, **result_config}  # Что бы не трогать дефолтный конфиг!
    except ValueError:
        return None

def logger_func(name: str, log_level: int = logging.DEBUG, stdout: bool = True, file: Optional[str] = None) -> logging.Logger:
    """
    Создаем логгер
    """
    # Настройка logging для записи в файл
    if file is not None:
        logging.basicConfig(filename=file, level=log_level)

    # Настройка structlog для вывода в sys.stdout
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer()
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logger = structlog.get_logger(name)

    # Создание обработчика для вывода в sys.stdout
    if stdout:
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(log_level)

    # Добавление обработчика к стандартному логгеру logging
    logging.getLogger().addHandler(stdout_handler)
    return logger

def search_last_log(log_dir: str, logger: logging.Logger) -> Optional[Dict[str, Any]]:
    '''
    Функция крайнего файла логгирования.

    Parameters
    ----------
    log_dir : str
        директория хранения логово.
    logger : logging.Logger
        логгер

    Returns
    -------
    result : Dict[str, str]
        Путь до файла лога
    '''

    logger.info(f'Search logs in directory {log_dir}')

    regex = re.compile(r'nginx-access-ui.log-([\d]{8})(.*)')

    max_dt = datetime.datetime(1, 1, 1)
    max_path = None
    max_file = None
    file_lst = os.listdir(log_dir)
    i = 0
    while i < len(file_lst):
        res = regex.search(file_lst[i])
        if (res is not None) and (res.group(2) == '.gz' or res.group(2) == ''):
            dt = datetime.datetime.strptime(res.group(1), '%Y%m%d')
            path = pathlib.Path(log_dir, file_lst[i])
            file = res.group(2)
            if dt > max_dt:
                max_dt = dt
                max_path = path
                max_file = file
        i += 1

    if max_path is not None:
        logger.info(f'The logs {max_path} was found')
        return {'log_path': max_path, 'log_date': max_dt, 'log_file': max_file}
    else:
        logger.info('The log file was not found!')
        return None


def get_report_path(report_dir, last_log, logger):
    '''
    Проверяем, существует ли отчет с таким именем в указанной dir.
    Если да, да парсинг выполнялся и прошел успешно возвращаем None, заканчиваем работу.
    Если нет, возвращаем path для записи отчета
    '''

    report_name = f"report-{last_log['log_date'].strftime('%Y.%m.%d')}.html"
    report_path = pathlib.Path(report_dir, report_name)
    if os.path.exists(report_path):
        logger.info(f"The {report_name} report already exists")
        return None
    else:
        logger.info(f"The report will be saved to the {report_name} file")
        return report_path


def parsing_line(line: str, logger: logging.Logger) -> Dict[str, Any]:
    regex = re.compile(r'(?:GET|POST|HEAD|PUT|OPTIONS|DELETE).(.*).HTTP/.* (\d{1,6}[.]\d+)')
    try:
        res_regex = regex.search(line)
    except UnicodeError:
        logger.exception(f'Recording decoding error: {line}')
        res = {'url': None, 'request_time': None, 'parsing_status': 'error'}
        return res

    if res_regex is None:
        logger.debug(f'Record parsing error: {line}')
        res = {'url': None, 'request_time': None, 'parsing_status': 'not_parsed'}
        return res

    url = res_regex.group(1).strip()
    request_time = float(res_regex.group(2).strip())
    res = {'url': url, 'request_time': request_time, 'parsing_status': 'success'}
    return res


def log_statistic_calc(latest_log: Dict, result_config: Dict, logger: logging.Logger) -> Optional[List[Dict]]:

    log_path = latest_log['log_path']
    log_file = latest_log['log_file']

    not_parsed_line = 0
    time_sum_all_req = 0
    logs_cnt = 0
    url_time_list = defaultdict(list)

    try:
        opening_func = gzip.open if log_file == '.gz' else open
    except OSError:
        logger.error(f'The {log_path} file does not open')

    with opening_func(log_path, 'rb') as log_file:
        for line in log_file:

            if result_config['DEBUG_MODE'] and logs_cnt == result_config['TEST_SIZE']:
                break
            logs_cnt += 1
            line = line.decode('utf-8')
            parsed_line = parsing_line(line, logger)
            if parsed_line['parsing_status'] == 'error':
                logger.error('Error parsing logs')
                return None
            elif parsed_line['parsing_status'] == 'not_parsed':
                not_parsed_line += 1
                continue

            url = parsed_line['url']
            request_time = parsed_line['request_time']
            time_sum_all_req += request_time

            url_time_list[url].append(request_time)
    url_stat = {}

    logger.info(f'{logs_cnt} logs were found in the file {log_path}')
    logger.info(f'{not_parsed_line} logs were not parsed')

    for url in url_time_list:
        url_stat_temp = {}
        url_stat_temp['url'] = url
        url_stat_temp['count'] = len(url_time_list[url])
        url_stat_temp['count_perc'] = round(url_stat_temp['count'] / logs_cnt * 100, 3)
        url_stat_temp['time_avg'] = round(statistics.mean(url_time_list[url]), 3)
        url_stat_temp['time_max'] = round(max(url_time_list[url]), 3)
        url_stat_temp['time_med'] = round(statistics.median(url_time_list[url]), 3)
        url_stat_temp['time_sum'] = round(sum(url_time_list[url]), 3)
        url_stat_temp['time_perc'] = round(url_stat_temp['time_sum'] / time_sum_all_req * 100, 3)
        url_stat[url] = url_stat_temp

    res_list = list(url_stat.values())
    res_list = sorted(res_list, key=lambda x: x['time_sum'], reverse=True)
    return res_list


def html_report_writer(result_config: str, report_path: str, logs_statistic: List[Dict], logger: logging.Logger) -> bool:
    """
    Dump the statistics into a json string.
    Copy the report template to the dir specified in config with the desired name
    Rendering the report
    """

    table_json = json.dumps(logs_statistic[:result_config['REPORT_SIZE']])
    template_path = result_config['TEMPLATE_PATH']

    with open(report_path, 'w', encoding='utf-8') as report, open(template_path, 'r', encoding='utf-8') as tmpl:
        tmpl_obj = string.Template(tmpl.read())
        try:
            render_html = tmpl_obj.safe_substitute(table_json=table_json)
        except Exception:
            logger.error('The template could not be rendered!')
            return False
        report.write(render_html)
        logger.info(f'The report {report_path} has been generated!')
    return True


def main():
    '''
    1. Получаем результирующий config
    2. Создаем логера
    3. Проверяем параметры результирующего config
    4. Ищем файл последнего лога, если не находим конец
    5. Проверяем есть ли уже отчет в указанной папке, если находим конец
    6. Получаем статистику по логам
    7. Создаем отчет
    '''

    config_path = parser_args()


    result_config = get_result_config(config, config_path)

    # log_path = result_config.get('SELF_LOG_PATH')

    logger = logger_func(__name__, file=result_config['SELF_LOG_PATH'])
    logger.info(f'Config path {config_path}')
    logger.info(f'DEBUG_MODE {result_config["DEBUG_MODE"]}')

    latest_log = search_last_log(result_config['LOG_DIR'], logger)

    if latest_log is not None:

        report_path = get_report_path(result_config["REPORT_DIR"], latest_log, logger)

        if report_path is not None:

            try:
                logs_statistic = log_statistic_calc(latest_log, result_config, logger)

                if logs_statistic is None:
                    logger.debug('Statistics are empty!')
                else:
                    html_report_writer(result_config, report_path, logs_statistic, logger)

            except Exception:
                logger.error('Emergency termination of the program!!!')



if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt as err:
        logging.exception(err)
    except Exception as err:
        logging.exception(err)