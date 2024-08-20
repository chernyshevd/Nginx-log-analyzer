import datetime
import os
import sys
CUR_PATH = os.path.dirname(__file__)
sys.path.append(os.path.join(CUR_PATH, '..'))
from log_analyzer import logger_func, search_last_log, parsing_line, get_report_path

logger = logger_func('test')

def test_search_last_log():
    expected_log_path = 'tests/latest_log/nginx-access-ui.log-20180730'
    expected_date = datetime.datetime(2018, 7, 30, 0, 0)
    log_dict = search_last_log('tests/latest_log', logger)
    log_path = str(log_dict['log_path'])
    log_date = log_dict['log_date']
    log_file = log_dict['log_file']
    assert expected_log_path == log_path
    assert expected_date == log_date
    assert '' == log_file

def test_parsing_line():

    test_line = '''1.199.4.96 -  - [29/Jun/2017:03:50:22 +0300]\
    "GET /api/v2/slot/4705/groups HTTP/1.1" 200 2613"-" \
    "Lynx/2.8.8dev.9 libwww-FM/2.14 SSL-MM/1.4.1 GNUTLS/2.10.5" \
    "-" "1498697422-3800516057-4708-9752745" "2a828197ae235b0b3cb" 0.704\n'''

    expected_data = {'url': '/api/v2/slot/4705/groups', 'request_time': 0.704, 'parsing_status': 'success'}
    output_data = parsing_line(test_line, logger)
    assert output_data == expected_data


def test_get_report_path():
    report_dir = 'latest_log'
    last_log = {'log_date': datetime.datetime(2018, 7, 30, 0, 0)}
    expected_report_name = 'latest_log/report-2018.07.30.html'
    output_report_name = get_report_path(report_dir, last_log, logger)
    assert str(output_report_name) == expected_report_name
