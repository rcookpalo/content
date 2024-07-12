import rasterize
from rasterize import *
import demistomock as demisto
from CommonServerPython import entryTypes
from tempfile import NamedTemporaryFile
import os
import logging
import http.server
import time
import threading
import pytest

# disable warning from urllib3. these are emitted when python driver can't connect to chrome yet
logging.getLogger("urllib3").setLevel(logging.ERROR)

RETURN_ERROR_TARGET = 'rasterize.return_error'


def util_read_tsv(filename):
    with open(filename) as file:
        ret_value = file.read()
        return ret_value


def util_generate_mock_info_file(info):
    from rasterize import write_file
    write_file("test_data/info.tsv", info, overwrite=True)


def test_rasterize_email_image(caplog, capfd, mocker):
    with capfd.disabled() and NamedTemporaryFile('w+') as f:
        f.write('<html><head><meta http-equiv=\"Content-Type\" content=\"text/html;charset=utf-8\">'
                '</head><body><br>---------- TEST FILE ----------<br></body></html>')
        path = os.path.realpath(f.name)
        f.flush()
        mocker.patch.object(rasterize, 'support_multithreading')
        perform_rasterize(path=f'file://{path}', width=250, height=250, rasterize_type=RasterizeType.PNG)
        caplog.clear()


def test_rasterize_email_image_array(caplog, capfd, mocker):
    with capfd.disabled() and NamedTemporaryFile('w+') as f:
        f.write('<html><head><meta http-equiv=\"Content-Type\" content=\"text/html;charset=utf-8\">'
                '</head><body><br>---------- TEST FILE ----------<br></body></html>')
        path = os.path.realpath(f.name)
        f.flush()
        mocker.patch.object(rasterize, 'support_multithreading')
        perform_rasterize(path=[f'file://{path}'], width=250, height=250, rasterize_type=RasterizeType.PNG)
        caplog.clear()


def test_rasterize_email_pdf(caplog, capfd, mocker):
    with capfd.disabled() and NamedTemporaryFile('w+') as f:
        f.write('<html><head><meta http-equiv=\"Content-Type\" content=\"text/html;charset=utf-8\">'
                '</head><body><br>---------- TEST FILE ----------<br></body></html>')
        path = os.path.realpath(f.name)
        f.flush()
        mocker.patch.object(rasterize, 'support_multithreading')
        perform_rasterize(path=f'file://{path}', width=250, height=250, rasterize_type=RasterizeType.PDF)
        caplog.clear()


def test_rasterize_email_pdf_offline(caplog, capfd, mocker):
    with capfd.disabled() and NamedTemporaryFile('w+') as f:
        f.write('<html><head><meta http-equiv=\"Content-Type\" content=\"text/html;charset=utf-8\">'
                '</head><body><br>---------- TEST FILE ----------<br></body></html>')
        path = os.path.realpath(f.name)
        f.flush()
        mocker.patch.object(rasterize, 'support_multithreading')
        perform_rasterize(path=f'file://{path}', width=250, height=250, rasterize_type=RasterizeType.PDF)
        caplog.clear()


def test_get_chrome_options():
    res = get_chrome_options(CHROME_OPTIONS, '')
    assert res == CHROME_OPTIONS

    res = get_chrome_options(CHROME_OPTIONS, '[--disable-dev-shm-usage],--disable-auto-reload, --headless')
    assert '--disable-dev-shm-usage' not in res
    assert '--no-sandbox' in res  # part of default options
    assert '--disable-auto-reload' in res
    assert len([x for x in res if x == '--headless']) == 1  # should have only one headless option

    res = get_chrome_options(CHROME_OPTIONS, r'--user-agent=test\,comma')
    assert len([x for x in res if x.startswith('--user-agent')]) == 1
    assert '--user-agent=test,comma' in res

    res = get_chrome_options(CHROME_OPTIONS, r'[--user-agent]')  # remove user agent
    assert len([x for x in res if x.startswith('--user-agent')]) == 0


def test_rasterize_large_html(capfd, mocker):
    with capfd.disabled():
        path = os.path.realpath('test_data/large.html')
        mocker.patch.object(rasterize, 'support_multithreading')
        res = perform_rasterize(path=f'file://{path}', width=250, height=250, rasterize_type=RasterizeType.PNG)
        assert res


def test_rasterize_html(mocker, capfd):
    with capfd.disabled():
        path = os.path.realpath('test_data/file.html')
        mocker.patch.object(demisto, 'args', return_value={'EntryID': 'test'})
        mocker.patch.object(demisto, 'getFilePath', return_value={"path": path})
        mocker.patch.object(os, 'rename')
        mocker.patch.object(os.path, 'realpath', return_value=f'{os.getcwd()}/test_data/file.html')
        mocker_output = mocker.patch('rasterize.return_results')
        mocker.patch.object(rasterize, 'support_multithreading')
        rasterize_html_command()
        assert mocker_output.call_args.args[0]['File'] == 'email.png'


@pytest.fixture
def http_wait_server():
    # Simple http handler which waits 10 seconds before responding
    class WaitHanlder(http.server.BaseHTTPRequestHandler):

        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()

        def do_GET(self):
            time.sleep(10)
            try:
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(bytes("<html><head><title>Test wait handler</title></head>"
                                       "<body><p>Test Wait</p></body></html>", 'utf-8'))
                self.flush_headers()
            except BrokenPipeError:  # ignore broken pipe as socket might have been closed
                pass

        # disable logging

        def log_message(self, format, *args):
            pass

    with http.server.ThreadingHTTPServer(('', 10888), WaitHanlder) as server:
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.start()
        yield
        server.shutdown()
        server_thread.join()


# Some web servers can block the connection after the http is sent
# In this case chromium will hang. An example for this is:
# curl -v -H 'user-agent: HeadlessChrome' --max-time 10  "http://www.grainger.com/"  # disable-secrets-detection
# This tests access a server which waits for 10 seconds and makes sure we timeout
@pytest.mark.filterwarnings('ignore::ResourceWarning')
def test_rasterize_url_long_load(mocker, http_wait_server, capfd):
    return_error_mock = mocker.patch(RETURN_ERROR_TARGET)
    time.sleep(1)  # give time to the servrer to start
    with capfd.disabled():
        mocker.patch.object(rasterize, 'support_multithreading')
        perform_rasterize('http://localhost:10888', width=250, height=250,
                          rasterize_type=RasterizeType.PNG, navigation_timeout=5)
        assert return_error_mock.call_count == 1
        # call_args last call with a tuple of args list and kwargs
        # err_msg = return_error_mock.call_args[0][0]
        # assert 'Timeout exception' in err_msg
        return_error_mock.reset_mock()
        # test that with a higher value we get a response
        assert perform_rasterize('http://localhost:10888', width=250, height=250, rasterize_type=RasterizeType.PNG)
        assert not return_error_mock.called


@pytest.mark.filterwarnings('ignore::ResourceWarning')
def test_rasterize_image_to_pdf(mocker):
    path = os.path.realpath('test_data/image.png')
    mocker.patch.object(demisto, 'args', return_value={'EntryID': 'test'})
    mocker.patch.object(demisto, 'getFilePath', return_value={"path": path})
    mocker.patch.object(demisto, 'results')
    mocker.patch.object(rasterize, 'support_multithreading')
    rasterize_image_command()
    assert demisto.results.call_count == 1
    # call_args is tuple (args list, kwargs). we only need the first one
    results = demisto.results.call_args[0]
    assert len(results) == 1
    assert results[0][0]['Type'] == entryTypes['entryInfoFile']


TEST_DATA = [
    (
        'test_data/many_pages.pdf',
        21,
        21,
        None
    ),
    (
        'test_data/many_pages.pdf',
        20,
        20,
        None
    ),
    (
        'test_data/many_pages.pdf',
        '*',
        51,
        None
    ),
    (
        'test_data/test_pw_mathias.pdf',
        '*',
        1,
        'mathias',
    )
]


@pytest.mark.parametrize('file_path, max_pages, expected_length, pw', TEST_DATA)
def test_convert_pdf_to_jpeg(file_path, max_pages, expected_length, pw):
    res = convert_pdf_to_jpeg(file_path, max_pages, pw)

    assert type(res) == list
    assert len(res) == expected_length


@pytest.mark.parametrize('width, height, expected_width, expected_height', [
    (8001, 700, 8000, 700),
    (700, 80001, 700, 8000),
    (700, 600, 700, 600)
])
def test_get_width_height(width, height, expected_width, expected_height):
    """
        Given:
            1. A width that is larger than the safeguard limit, and a valid height
            2. A height that is larger than the safeguard limit, and a valid width
            3. Valid width and height
        When:
            - Running the 'heck_width_and_height' function.
        Then:
            Verify that:
            1. The resulted width is the safeguard limit (8000px) and the height remains as it was.
            2. The resulted height is the safeguard limit (8000px) and the width remains as it was.
            3. Both width and height remain as they were.
    """
    args = {
        'width': str(width),
        'height': str(height)
    }
    w, h = get_width_height(args)
    assert w == expected_width
    assert h == expected_height


class TestRasterizeIncludeUrl:
    class MockChromeOptions:

        def __init__(self) -> None:
            self.options = []

        def add_argument(self, arg):
            self.options.append(arg)

    class MockChrome:

        def __init__(self, options, service) -> None:
            self.options = options.options
            self.page_source = ''
            self.session_id = 'session_id'

        def set_page_load_timeout(self, max_page_load_time):
            pass

        def get(self, path):
            pass

        def maximize_window(self):
            pass

        def implicitly_wait(self, arg):
            pass

        def set_window_size(self, width, height):
            pass

        def get_screenshot_as_png(self):
            return 'image'

        def quit(self):
            pass

    @pytest.mark.parametrize('include_url', [False, True])
    def test_sanity_rasterize_with_include_url(self, mocker, include_url, capfd):
        """
            Given:
                - A parameter that mention whether to include the URL bar in the screenshot.
            When:
                - Running the 'rasterize' function.
            Then:
                - Verify that it runs as expected.
        """
        mocker.patch('os.remove')

        with capfd.disabled(), NamedTemporaryFile('w+') as f:
            f.write('<html><head><meta http-equiv=\"Content-Type\" content=\"text/html;charset=utf-8\">'
                    '</head><body><br>---------- TEST FILE ----------<br></body></html>')
            path = os.path.realpath(f.name)
            f.flush()

            mocker.patch.object(rasterize, 'support_multithreading')
            image = perform_rasterize(path=f'file://{path}', width=250, height=250, rasterize_type=RasterizeType.PNG,
                                      include_url=include_url)
            assert image


def test_log_warning():
    """
    Given   pypdf's logger instance
    When    checking the logger's level.
    Then    make sure the level is ERROR
    """
    import logging
    from rasterize import pypdf_logger
    assert pypdf_logger.level == logging.ERROR
    assert pypdf_logger.level == logging.ERROR


def test_excepthook_recv_loop(mocker):
    """
    Given   Exceptions that might happen after the tab was closed.
    When    A chromium tab is closed.
    Then    make sure the right info is logged.
    """
    mock_args = type('mock_args', (), dict.fromkeys(('exc_type', 'exc_value')))
    demisto_info = mocker.patch.object(demisto, 'info')

    excepthook_recv_loop(mock_args)

    demisto_info.assert_any_call('Unsuppressed Exception in _recv_loop: args.exc_type=None')
    demisto_info.assert_any_call('Unsuppressed Exception in _recv_loop: args.exc_type=None, empty exc_value')


def test_poppler_version():
    import pdf2image
    poppler_version = pdf2image.pdf2image._get_poppler_version("pdftoppm")
    assert poppler_version[0] > 20


def test_get_list_item():
    from rasterize import get_list_item

    my_list = ['a', 'b', 'c']

    assert get_list_item(my_list, 0, "FOO") == 'a'
    assert get_list_item(my_list, 1, "FOO") == 'b'
    assert get_list_item(my_list, 2, "FOO") == 'c'
    assert get_list_item(my_list, 3, "FOO") == 'FOO'
    assert get_list_item(my_list, 4, "FOO") == 'FOO'


def test_add_filename_suffix():
    from rasterize import add_filename_suffix

    my_list = ['a', 'b', 'c']
    my_list_with_suffix = add_filename_suffix(my_list, 'sfx')

    assert len(my_list) == len(my_list_with_suffix)
    for current_element_index, _ in enumerate(my_list):
        assert f'{my_list[current_element_index]}.sfx' == my_list_with_suffix[current_element_index]


def test_get_output_filenames():
    from rasterize import get_list_item, add_filename_suffix

    file_name = ['foo_01', 'foo_02', 'foo_03']
    file_names = argToList(file_name)
    file_names = add_filename_suffix(file_names, 'png')

    assert get_list_item(file_names, 0, "FOO.png") == 'foo_01.png'
    assert get_list_item(file_names, 1, "FOO.png") == 'foo_02.png'
    assert get_list_item(file_names, 2, "FOO.png") == 'foo_03.png'
    assert get_list_item(file_names, 3, "FOO.png") == 'FOO.png'
    assert get_list_item(file_names, 4, "FOO.png") == 'FOO.png'


def test_chrome_manager_case_chrome_instances_file_is_empty(mocker):
    """
    Given   instance id and chrome options
    When    chrome instances file is empty
    Then    make sure code running into case 1 calling generate_new_chrome_instance which return browser and chrome port.
    """
    from rasterize import chrome_manager

    instance_id = "new_instance_id"
    chrome_options = "new_chrome_options"

    mock_context = {
        'context': {
            'IntegrationInstanceID': instance_id
        }
    }

    params = {
        'chrome_options': chrome_options
    }

    mocker.patch.object(demisto, 'callingContext', mock_context)
    mocker.patch.object(demisto, 'params', return_value=params)
    mocker.patch.object(rasterize, 'read_file', return_value=None)
    mocker.patch.object(rasterize, 'get_chrome_instances_contents_dictionaries', return_value=[{}, {}, {}, {}])
    generate_new_chrome_instance_mocker = mocker.patch.object(rasterize, 'generate_new_chrome_instance',
                                                              return_value=["browser_object", "chrome_port"])
    terminate_chrome_mocker = mocker.patch.object(rasterize, 'terminate_chrome', return_value=None)
    browser, chrome_port = chrome_manager()

    assert generate_new_chrome_instance_mocker.call_count == 1
    assert generate_new_chrome_instance_mocker.called_with(instance_id, chrome_options)
    assert terminate_chrome_mocker.call_count == 0
    assert browser == "browser_object"
    assert chrome_port == "chrome_port"


def test_chrome_manager_case_chromes_options_exist_and_instance_id_not_linked(mocker):
    """
    Given   instance id that does not exist and chrome options that exist in the chrome instances file
    When    chrome instances file is not empty and instance id is not linked to the chrome options
    Then    make sure code running into case 2 and calling generate_new_chrome_instance which return browser and chrome port.
    """
    from rasterize import chrome_manager
    from rasterize import get_chrome_instances_contents_dictionaries

    instance_id = "instance_id_that_does_not_exist"
    chrome_options = "chrome_options2"  # exist

    mock_context = {
        'context': {
            'IntegrationInstanceID': instance_id
        }
    }

    params = {
        'chrome_options': chrome_options
    }

    mock_file_content = util_read_tsv("test_data/info.tsv")
    mock_file_content_edited = mock_file_content.replace('\\t', '\t')
    instance_id_to_chrome_options, instance_id_to_port, instances_id, chromes_options = \
        get_chrome_instances_contents_dictionaries(mock_file_content_edited)
    mocker.patch.object(demisto, 'callingContext', mock_context)
    mocker.patch.object(demisto, 'params', return_value=params)
    mocker.patch.object(rasterize, 'read_file', return_value=mock_file_content_edited)
    mocker.patch.object(rasterize, 'get_chrome_instances_contents_dictionaries',
                        return_value=[instance_id_to_chrome_options, instance_id_to_port, instances_id, chromes_options])
    generate_new_chrome_instance_mocker = mocker.patch.object(rasterize, 'generate_new_chrome_instance',
                                                              return_value=["browser_object", "chrome_port"])
    terminate_chrome_mocker = mocker.patch.object(rasterize, 'terminate_chrome', return_value=None)
    browser, chrome_port = chrome_manager()

    assert generate_new_chrome_instance_mocker.call_count == 1
    assert generate_new_chrome_instance_mocker.called_with(instance_id, chrome_options)
    assert terminate_chrome_mocker.call_count == 0
    assert browser == "browser_object"
    assert chrome_port == "chrome_port"


def test_chrome_manager_case_new_chrome_options_and_instance_id(mocker):
    """
    Given   instance id and chrome options does not exist in the chrome instances file
    When    chrome instances file is not empty
    Then    make sure code running into case 3 and calling generate_new_chrome_instance which return browser and chrome port.
    """
    from rasterize import chrome_manager

    instance_id = "instance_id_that_does_not_exist"
    chrome_options = "chrome_options_that_does_not_exist"

    mock_context = {
        'context': {
            'IntegrationInstanceID': instance_id
        }
    }

    params = {
        'chrome_options': chrome_options
    }

    mock_file_content = util_read_tsv("test_data/info.tsv")
    mock_file_content_edited = mock_file_content.replace('\\t', '\t')
    instance_id_to_chrome_options, instance_id_to_port, instances_id, chromes_options = \
        get_chrome_instances_contents_dictionaries(mock_file_content_edited)
    mocker.patch.object(demisto, 'callingContext', mock_context)
    mocker.patch.object(demisto, 'params', return_value=params)
    mocker.patch.object(rasterize, 'read_file', return_value=mock_file_content_edited)
    mocker.patch.object(rasterize, 'get_chrome_instances_contents_dictionaries',
                        return_value=[instance_id_to_chrome_options, instance_id_to_port, instances_id, chromes_options])
    generate_new_chrome_instance_mocker = mocker.patch.object(rasterize, 'generate_new_chrome_instance',
                                                              return_value=["browser_object", "chrome_port"])
    terminate_chrome_mocker = mocker.patch.object(rasterize, 'terminate_chrome', return_value=None)
    browser, chrome_port = chrome_manager()

    assert generate_new_chrome_instance_mocker.call_count == 1
    assert generate_new_chrome_instance_mocker.called_with(instance_id, chrome_options)
    assert terminate_chrome_mocker.call_count == 0
    assert browser == "browser_object"
    assert chrome_port == "chrome_port"


def test_chrome_manager_case_instance_id_exist_but_new_chrome_options(mocker):
    """
    Given   instance id exist and chrome options does not exist in the chrome instances file
    When    chrome instances file is not empty and instance id has different chrome options
    Then    make sure code running into case 4, terminating old chrome port, generating new one,
            and update the chrome instances file.
    """
    from rasterize import chrome_manager

    instance_id = "22222222-2222-2222-2222-222222222222"  # exist
    chrome_options = "chrome_options_that_does_not_exist"

    mock_context = {
        'context': {
            'IntegrationInstanceID': instance_id
        }
    }

    params = {
        'chrome_options': chrome_options
    }

    mock_file_content = util_read_tsv("test_data/info.tsv")
    mock_file_content_edited = mock_file_content.replace('\\t', '\t')
    instance_id_to_chrome_options, instance_id_to_port, instances_id, chromes_options = \
        get_chrome_instances_contents_dictionaries(mock_file_content_edited)
    mocker.patch.object(demisto, 'callingContext', mock_context)
    mocker.patch.object(demisto, 'params', return_value=params)
    mocker.patch.object(rasterize, 'read_file', return_value=mock_file_content_edited)
    mocker.patch.object(rasterize, 'get_chrome_instances_contents_dictionaries',
                        return_value=[instance_id_to_chrome_options, instance_id_to_port, instances_id, chromes_options])
    mocker.patch.object(rasterize, 'get_chrome_browser', return_value=None)
    terminate_chrome_mocker = mocker.patch.object(rasterize, 'terminate_chrome', return_value=None)
    mocker.patch.object(rasterize, 'delete_row_with_old_chrome_configurations_from_chrome_instances_file', return_value=None)
    generate_new_chrome_instance_mocker = mocker.patch.object(rasterize, 'generate_new_chrome_instance',
                                                              return_value=["browser_object", "chrome_port"])
    browser, chrome_port = chrome_manager()

    assert terminate_chrome_mocker.call_count == 1
    assert generate_new_chrome_instance_mocker.call_count == 1
    assert generate_new_chrome_instance_mocker.called_with(instance_id, chrome_options)
    assert browser == "browser_object"
    assert chrome_port == "chrome_port"


def test_chrome_manager_case_instance_id_and_chrome_options_exist_and_linked(mocker):
    """
    Given   instance id and chrome options
    When    chrome instances file is not empty, and instance id and chrome options linked.
    Then    make sure code running into case 5 and using the browser that already in used.
    """
    from rasterize import chrome_manager

    instance_id = "22222222-2222-2222-2222-222222222222"  # exist
    chrome_options = "chrome_options2"

    mock_context = {
        'context': {
            'IntegrationInstanceID': instance_id
        }
    }

    params = {
        'chrome_options': chrome_options
    }

    mock_file_content = util_read_tsv("test_data/info.tsv")
    mock_file_content_edited = mock_file_content.replace('\\t', '\t')
    instance_id_to_chrome_options, instance_id_to_port, instances_id, chromes_options = \
        get_chrome_instances_contents_dictionaries(mock_file_content_edited)
    mocker.patch.object(demisto, 'callingContext', mock_context)
    mocker.patch.object(demisto, 'params', return_value=params)
    mocker.patch.object(rasterize, 'read_file', return_value=mock_file_content_edited)
    mocker.patch.object(rasterize, 'get_chrome_instances_contents_dictionaries',
                        return_value=[instance_id_to_chrome_options, instance_id_to_port, instances_id, chromes_options])
    mocker.patch.object(rasterize, 'get_chrome_browser', return_value="browser_object")
    terminate_chrome_mocker = mocker.patch.object(rasterize, 'terminate_chrome', return_value=None)
    generate_new_chrome_instance_mocker = mocker.patch.object(rasterize, 'generate_new_chrome_instance',
                                                              return_value=["browser_object", "chrome_port"])
    browser, chrome_port = chrome_manager()

    assert terminate_chrome_mocker.call_count == 0
    assert generate_new_chrome_instance_mocker.call_count == 0
    assert browser == "browser_object"
    assert chrome_port == "2222"


def test_generate_chrome_port():
    """
    Given   first_chrome_port and max_chromes_count
    When    needed to generate new chrome port
    Then    make sure the function generate valid chrome port.
    """
    from rasterize import generate_chrome_port
    port = generate_chrome_port()
    assert 0 <= len(port) <= 5


def test_generate_chrome_port_no_port_available(mocker):
    """
    Given   first_chrome_port and max_chromes_count that creates empty range
    When    needed to generate new chrome port
    Then    make sure the function will raise an error and return None
    """
    from rasterize import generate_chrome_port
    rasterize.FIRST_CHROME_PORT = 0
    rasterize.MAX_CHROMES_COUNT = 0
    mock_return_error = mocker.patch.object(demisto, 'error', return_value=None)
    port = generate_chrome_port()
    assert mock_return_error.call_count == 1
    assert not port


def test_get_chrome_instances_contents_dictionaries():
    """
    Given   chrome instances file with content
    When    extract the data from it and parse it for 2 dictionaries and 2 lists:
                - instance_id_to_chrome_options (dict): A dictionary mapping instance ID to Chrome options.
                - instance_id_to_port (dict): A dictionary mapping instance ID to Chrome port.
                - instances_id (list): A list of instances ID extracted from instance_id_to_port keys.
                - chromes_options (list): A list of Chrome options extracted from instance_id_to_chrome_options values.
    Then    make sure the data are extracted correctly according the mock data file content.
    """
    from rasterize import get_chrome_instances_contents_dictionaries
    mock_file_content = util_read_tsv("test_data/info.tsv")
    mock_file_content_edited = mock_file_content.replace('\\t', '\t')
    instance_id_to_chrome_options, instance_id_to_port, instances_id, chromes_options = \
        (get_chrome_instances_contents_dictionaries(mock_file_content_edited))
    assert instance_id_to_chrome_options == {'22222222-2222-2222-2222-222222222222': 'chrome_options2',
                                             '33333333-3333-3333-3333-333333333333': 'chrome_options3',
                                             '44444444-4444-4444-4444-444444444444': 'chrome_options4'}
    assert instance_id_to_port == {'22222222-2222-2222-2222-222222222222': '2222', '33333333-3333-3333-3333-333333333333': '3333',
                                   '44444444-4444-4444-4444-444444444444': '4444'}
    assert instances_id
    assert instances_id == ['22222222-2222-2222-2222-222222222222', '33333333-3333-3333-3333-333333333333',
                            '44444444-4444-4444-4444-444444444444']
    assert chromes_options
    assert chromes_options == ['chrome_options2', 'chrome_options3', 'chrome_options4']


def test_delete_row_with_old_chrome_configurations_from_info_file():
    """
    Given   chrome instances file with content
    When    need to delete row with old chrome configurations from the file
    Then    make sure it delete the specific row should be deleted
    """
    from rasterize import delete_row_with_old_chrome_configurations_from_chrome_instances_file

    rasterize.CHROME_INSTANCES_FILE_PATH = "test_data/info.tsv"

    mock_info = """2222\t22222222-2222-2222-2222-222222222222\tchrome_options2
    3333\t33333333-3333-3333-3333-333333333333\tchrome_options3
    test\ttesttest-test-test-test-testtesttest\tchrome_options0
    4444\t44444444-4444-4444-4444-444444444444\tchrome_options4
    """
    util_generate_mock_info_file(mock_info)
    chrome_port_to_delete = "test"
    instance_id_to_delete = "testtest-test-test-test-testtesttest"

    delete_row_with_old_chrome_configurations_from_chrome_instances_file(
        mock_info, instance_id_to_delete, chrome_port_to_delete)

    mock_file_content = util_read_tsv("test_data/info.tsv")
    mock_file_content_edited = mock_file_content.replace('\\t', '\t')

    expected_mock_file_content = """2222\t22222222-2222-2222-2222-222222222222\tchrome_options2
    3333\t33333333-3333-3333-3333-333333333333\tchrome_options3
    4444\t44444444-4444-4444-4444-444444444444\tchrome_options4
    """.strip()

    assert expected_mock_file_content == mock_file_content_edited
