import json
import os
import pytest
import sys

build_script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, build_script_dir)
from logger import Logger, LoggerDecoder


def test_initialization_creates_strm_dir():
    """
    Verify the initialization of a parent :class:`Logger` object creates a
    temporary directory (``log_dir/%Y-%m-%d_%H%M%S``) if not already created.
    """

    cwd = os.getcwd()
    logger = Logger('test', cwd)
    timestamp = logger.init_time.strftime("%Y-%m-%d_%H%M%S")
    assert os.path.exists(os.path.join(cwd, timestamp))


def test_initialization_creates_html_file():
    """
    Verify the initialization of a parent :class:`Logger` object creates a
    starting HTML file in the :attr:`log_dir`.
    """

    Logger('test', os.getcwd())
    assert os.path.exists(os.path.join(os.getcwd(), 'test.html'))


@pytest.fixture()
def logger():
    """
    **@pytest.fixture()**

    This fixture creates a :class:`Logger` object with some sample data to be
    used in tests.  It first creates a sample :class:`Logger` object.  Then it
    logs a command (whose ``stdout`` is ``'Hello world'`` and ``stderr`` is
    ``'Hello world error'``).  Next, it adds a child :class:`Logger` object and
    prints something using that child logger.

    Returns:
        Logger:  The parent :class:`Logger` object described above.
    """

    # Initialize.
    logger = Logger('Parent', os.getcwd())

    # Run command.
    #            stdout          ;        stderr
    cmd = "echo 'Hello world out'; echo 'Hello world error' 1>&2"
    logger.log("test cmd", cmd, os.getcwd())

    # Add child and print statement.
    child_logger = logger.add_child("Child")
    child_logger.print("Hello world child")

    return logger


def test_log_method_creates_tmp_stdout_stderr_files(logger):
    """
    Verify that logging a command will create files in the :class:`Logger`
    object's :attr:`strm_dir` corresponding to the ``stdout`` and ``stderr`` of
    the command.
    """

    # Get the paths for the stdout/stderr files.
    cmd_id = logger.log_book[0]['cmd_id']
    cmd_ts = logger.log_book[0]['timestamp']
    stdout_file = os.path.join(logger.strm_dir, f"{cmd_ts}_{cmd_id}_stdout")
    stderr_file = os.path.join(logger.strm_dir, f"{cmd_ts}_{cmd_id}_stderr")

    assert os.path.exists(stdout_file)
    assert os.path.exists(stderr_file)

    # Make sure the information written to these files is correct.
    with open(stdout_file, 'r') as out, open(stderr_file, 'r') as err:
        out_txt = out.readline()
        err_txt = err.readline()

        assert 'Hello world out' in out_txt
        assert 'Hello world error' in err_txt


@pytest.mark.parametrize('return_info', [True, False])
def test_log_method_return_info_works_correctly(return_info):
    """
    **@pytest.mark.parametrize('return_info', [True, False])**

    Verify that when ``return_info=True``, we receive a dictionary that
    contains the ``stdout`` and ``stderr`` of the command, as well as the
    ``return_code``, and when ``return_info=False``, we receive the
    ``return_code``, but ``stdout`` and ``stderr`` are ``None``.
    """

    logger = Logger("Test", os.getcwd())

    #            stdout          ;        stderr
    cmd = "echo 'Hello world out'; echo 'Hello world error' 1>&2"
    result = logger.log("test cmd", cmd, os.getcwd(), return_info=return_info)

    if return_info:
        assert "Hello world out" in result['stdout']
        assert "Hello world error" in result['stderr']
        assert result['return_code'] == 0
    else:
        assert result['stdout'] is None
        assert result['stderr'] is None
        assert result['return_code'] == 0


@pytest.mark.parametrize('live_stdout', [True, False])
@pytest.mark.parametrize('live_stderr', [True, False])
def test_log_method_live_stdout_stderr_works_correctly(capsys, live_stdout,
                                                       live_stderr):
    """
    Verify that the ``live_stdout`` and ``live_stdout`` flags work as expected
    for the :func:`log` method.
    """

    logger = Logger("Test", os.getcwd())

    #            stdout          ;        stderr
    cmd = "echo 'Hello world out'; echo 'Hello world error' 1>&2"
    logger.log("test cmd", cmd, os.getcwd(), live_stdout, live_stderr)
    out, err = capsys.readouterr()

    if live_stdout:
        assert "\nHello world out\n" in out
    else:
        assert "\nHello world out\n" not in out

    if live_stderr:
        assert "Hello world error\n" in err
    else:
        assert "Hello world error\n" not in out


def test_finalize_keeps_tmp_stdout_stderr_files(logger):
    """
    Verify that the :func:`finalize` method does not delete the temporary
    ``stdout``/``stderr`` files.  We want to keep these for a bit in case the
    HTML file needs to be recreated.
    """

    # Get the paths for the stdout/stderr files.
    cmd_id = logger.log_book[0]['cmd_id']
    cmd_ts = logger.log_book[0]['timestamp']
    stdout_file = os.path.join(logger.strm_dir, f"{cmd_ts}_{cmd_id}_stdout")
    stderr_file = os.path.join(logger.strm_dir, f"{cmd_ts}_{cmd_id}_stderr")

    # Make sure they exist before finalize is called.
    assert os.path.exists(stdout_file)
    assert os.path.exists(stderr_file)

    logger.finalize()

    # Make sure they exist after finalize is called.
    assert os.path.exists(stdout_file)
    assert os.path.exists(stderr_file)


def test_finalize_creates_JSON_with_correct_information(logger):
    """
    Verify that the :func:`finalize` method creates a JSON file with the proper
    data.
    """

    logger.finalize()

    # Load from JSON.
    json_file = os.path.join(logger.strm_dir, 'Parent.json')
    assert os.path.exists(json_file)
    with open(json_file, 'r') as jf:
        loaded_logger = json.load(jf, cls=LoggerDecoder)

    # Parent Logger
    assert logger.log_dir == loaded_logger.log_dir
    assert logger.strm_dir == loaded_logger.strm_dir
    assert logger.html_file == loaded_logger.html_file
    assert logger.indent == loaded_logger.indent
    assert logger.name == loaded_logger.name
    assert logger.init_time == loaded_logger.init_time
    assert logger.done_time == loaded_logger.done_time
    assert logger.log_book[0] == loaded_logger.log_book[0]

    # Child Logger
    child = logger.log_book[1]
    loaded_child = loaded_logger.log_book[1]
    assert child.log_dir == loaded_child.log_dir
    assert child.strm_dir == loaded_child.strm_dir
    assert child.html_file == loaded_child.html_file
    assert child.indent == loaded_child.indent
    assert child.name == loaded_child.name
    assert child.init_time == loaded_child.init_time
    assert child.done_time == loaded_child.done_time
    assert child.log_book[0] == loaded_child.log_book[0]


def test_finalize_creates_HTML_with_correct_information(logger):
    """
    Verify that the :func:`finalize` method creates an HTML file with the
    proper data.
    """

    logger.finalize()

    # Load the HTML file.
    html_file = os.path.join(logger.strm_dir, 'Parent.html')
    assert os.path.exists(html_file)
    with open(html_file, 'r') as hf:
        html_text = hf.read()

    # Command info.
    assert "<b>test cmd</b>" in html_text
    assert f"Duration: {logger.log_book[0]['duration']}" in html_text
    assert f"Time:</b> {logger.log_book[0]['timestamp']}" in html_text
    assert "Command:</b> echo 'Hello world out'; "\
        "echo 'Hello world error' 1>&2" in html_text
    assert f"CWD:</b> {os.getcwd()}" in html_text
    assert "Return Code:</b> 0" in html_text

    # Print statement.
    assert "\n  <br>Hello world child" in html_text

    # Child Logger
    assert "Child</font></b>\n" in html_text


def test_log_dir_HTML_symlinks_to_strm_dir_HTML(logger):
    """
    Verify that the :func:`finalize` method symlinks log_dir/html_file to
    strm_dir/html_file.
    """

    logger.finalize()

    # Load the HTML file.
    html_file = os.path.join(logger.strm_dir, 'Parent.html')
    html_symlink = os.path.join(logger.log_dir, 'Parent_latest_run.html')
    assert os.path.exists(html_file)
    assert os.path.exists(html_symlink)

    assert os.path.realpath(html_symlink) == html_file


def test_JSON_file_can_reproduce_HTML_file(logger):
    """
    Verify that a JSON file can properly recreate the original HTML file
    created when :func:`finalize` is called.
    """

    logger.finalize()

    # Load the original HTML file's contents.
    html_file = os.path.join(logger.log_dir, 'Parent.html')
    assert os.path.exists(html_file)
    with open(html_file, 'r') as hf:
        original_html = hf.read()

    # Delete the HTML file.
    os.remove(html_file)

    # Load the JSON data.
    json_file = os.path.join(logger.strm_dir, 'Parent.json')
    assert os.path.exists(json_file)
    with open(json_file, 'r') as jf:
        loaded_logger = json.load(jf, cls=LoggerDecoder)

    # Call finalize on the loaded Logger object.
    loaded_logger.finalize()

    # Load the new HTML file's contents and compare.
    assert os.path.exists(html_file)
    with open(html_file, 'r') as hf:
        new_html = hf.read()

    assert original_html == new_html
