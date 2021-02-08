from inspect import stack
import json
import os
import pytest
import re
import sys
from pathlib import Path
build_script_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, build_script_dir / "logger")
from logger import Logger, LoggerDecoder

print(sys.path)


def test_initialization_creates_strm_dir():
    """
    Verify the initialization of a parent :class:`Logger` object creates a
    temporary directory (``log_dir/%Y-%m-%d_%H%M%S``<random string>) if not
    already created.
    """

    logger = Logger(stack()[0][3], Path.cwd())
    timestamp = logger.init_time.strftime("%Y-%m-%d_%H.%M.%S.%f")
    assert len(list(Path.cwd().glob(f"{timestamp}_*"))) == 1


def test_initialization_creates_html_file():
    """
    Verify the initialization of a parent :class:`Logger` object creates a
    starting HTML file in the :attr:`log_dir`.
    """

    logger = Logger(stack()[0][3], Path.cwd())
    timestamp = logger.init_time.strftime("%Y-%m-%d_%H.%M.%S.%f")
    strm_dir = next(Path.cwd().glob(f"{timestamp}_*"))
    assert (strm_dir / f'{stack()[0][3]}.html').exists()


@pytest.mark.parametrize('return_info', [True, False])
def test_log_method_return_info_works_correctly(return_info):
    """
    **@pytest.mark.parametrize('return_info', [True, False])**

    Verify that when ``return_info=True``, we receive a dictionary that
    contains the ``stdout`` and ``stderr`` of the command, as well as the
    ``return_code``, and when ``return_info=False``, we receive the
    ``return_code``, but ``stdout`` and ``stderr`` are ``None``.
    """

    logger = Logger(stack()[0][3], Path.cwd())

    #            stdout          ;        stderr
    cmd = "echo 'Hello world out'; echo 'Hello world error' 1>&2"
    result = logger.log("test cmd", cmd, Path.cwd(), return_info=return_info)

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

    logger = Logger(stack()[0][3], Path.cwd())

    #            stdout          ;        stderr
    cmd = "echo 'Hello world out'; echo 'Hello world error' 1>&2"
    logger.log("test cmd", cmd, Path.cwd(), live_stdout, live_stderr)
    out, err = capsys.readouterr()

    if live_stdout:
        assert re.search(r"^Hello world out(\r)?\n", out) is not None
    else:
        assert re.search(r"^Hello world out(\r)?\n", out) is None

    if live_stderr:
        assert re.search(r"^Hello world error(\r)?\n", err) is not None
    else:
        assert re.search(r"^Hello world error(\r)?\n", err) is None


def test_child_logger_duration_displayed_correctly_in_HTML(logger):
    """
    Verify that the overview of child loggers in the HTML file displays the
    correct child logger duration, not the entire log's duration.
    """

    child2 = logger.add_child("Child 2")
    child2.log("Wait 0.005s", ["sleep", "0.005"])

    child3 = logger.add_child("Child 3")
    child3.log("Wait 0.006s", ["sleep", "0.006"])

    logger.finalize()

    with open(logger.html_file, 'r') as hf:
        html_text = hf.read()

    assert child2.duration is not None
    assert f"<br>Duration: {child2.duration}\n" in html_text

    assert child3.duration is not None
    assert f"<br>Duration: {child3.duration}\n" in html_text


def test_finalize_creates_JSON_with_correct_information(logger):
    """
    Verify that the :func:`finalize` method creates a JSON file with the proper
    data.
    """

    logger.finalize()

    # Load from JSON.
    json_file = logger.strm_dir / "Parent.json"
    assert json_file.exists()
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
    html_file = logger.strm_dir / "Parent.html"
    assert html_file.exists()
    with open(html_file, 'r') as hf:
        html_text = hf.read()

    # Command info.
    assert "<b>test cmd</b>" in html_text
    assert f"Duration: {logger.log_book[0]['duration']}" in html_text
    assert f"Time:</b> {logger.log_book[0]['timestamp']}" in html_text
    assert "Command:</b> echo 'Hello world out'; "\
        "echo 'Hello world error' 1>&2" in html_text
    assert f"CWD:</b> {Path.cwd()}" in html_text
    assert "Return Code:</b> 0" in html_text

    # Print statement.
    assert "\n  <br>Hello world child" in html_text
    assert "<b>trace:</b>" in html_text
    assert "setlocale" in html_text
    assert "getenv" not in html_text
    assert "<b>Memory Usage:</b>" in html_text
    assert "<svg" in html_text
    assert "</svg>" in html_text
    assert "<b>CPU Usage:</b>" in html_text
    assert "<b>Disk Usage:</b>" in html_text
    assert "<li>Volume /:" in html_text

    # Child Logger
    assert "Child</font></b>\n" in html_text


def test_log_dir_HTML_symlinks_to_strm_dir_HTML(logger):
    """
    Verify that the :func:`finalize` method symlinks log_dir/html_file to
    strm_dir/html_file.
    """

    logger.finalize()

    # Load the HTML file.
    html_file = logger.strm_dir / "Parent.html"
    html_symlink = logger.log_dir / "Parent.html"
    assert html_file.exists()
    assert html_symlink.exists()

    assert html_symlink.resolve() == html_file


def test_JSON_file_can_reproduce_HTML_file(logger):
    """
    Verify that a JSON file can properly recreate the original HTML file
    created when :func:`finalize` is called.
    """

    logger.finalize()

    # Load the original HTML file's contents.
    html_file = logger.log_dir / "Parent.html"
    assert html_file.exists()
    with open(html_file, 'r') as hf:
        original_html = hf.read()

    # Delete the HTML file.
    html_file.unlink()

    # Load the JSON data.
    json_file = logger.strm_dir / "Parent.json"
    assert json_file.exists()
    with open(json_file, 'r') as jf:
        loaded_logger = json.load(jf, cls=LoggerDecoder)

    # Call finalize on the loaded Logger object.
    loaded_logger.finalize()

    # Load the new HTML file's contents and compare.
    assert html_file.exists()
    with open(html_file, 'r') as hf:
        new_html = hf.read()

    assert original_html == new_html

def test_stdout():
    logger = Logger(stack()[0][3], Path.cwd())
    assert logger.run(":").stdout == ""
    assert logger.run("echo hello").stdout == "hello\n"

def test_returncode():
    logger = Logger(stack()[0][3], Path.cwd())
    assert logger.run(":").returncode == 0

def test_args():
    logger = Logger(stack()[0][3], Path.cwd())
    assert logger.run("echo hello").args == "echo hello"

def test_stderr():
    logger = Logger(stack()[0][3], Path.cwd())
    command = "echo hello 1>&2"
    assert logger.run(command).stderr == "hello\n"
    assert logger.run(command).stdout == ""

def test_console():
    logger = Logger(stack()[0][3], Path.cwd())
    command = "echo stdout ; echo stderr 1>&2"
    if os.name == "posix":
        command = "echo stdout ; echo stderr 1>&2"
    elif os.name == "nt":
        command = "echo stdout & echo stderr 1>&2"
    else:
        print(f"Warning: os.name is unrecognized: {os.name}; test may fail.")
    assert logger.run(command).console == "stdout\nstderr\n"

def test_consoleBackwards():
    logger = Logger(stack()[0][3], Path.cwd())
    command = "echo stderr 1>&2 ; echo stdout"
    if os.name == "posix":
        command = "echo stderr 1>&2 ; echo stdout"
    elif os.name == "nt":
        command = "echo stderr 1>&2 & echo stdout"
    else:
        print(f"Warning: os.name is unrecognized: {os.name}; test may fail.")
    assert logger.run(command).console == "stderr\nstdout\n"

def test_timing():
    logger = Logger(stack()[0][3], Path.cwd())
    command = "sleep 1"
    if os.name == "posix":
        command = "sleep 1"
    elif os.name == "nt":
        command = "timeout /nobreak /t 1"
    else:
        print(f"Warning: os.name is unrecognized: {os.name}; test may fail.")
    result = logger.run(command)
    assert result.wall >= 1000
    assert result.wall < 2000
    assert result.finish >= result.start

def test_auxiliaryData():
    logger = Logger(stack()[0][3], Path.cwd())
    result = logger.run("pwd")
    assert result.pwd == result.stdout.strip()
    result = logger.run(":")
    assert "PATH=" in result.environment
    assert logger.run("whoami").stdout.strip() == result.user
    if os.name == "posix":
        assert len(result.umask) == 3 or len(result.umask) == 4
        assert logger.run("id -gn").stdout.strip() == result.group
        assert logger.run("printenv SHELL").stdout.strip() == result.shell
        assert logger.run("ulimit -a").stdout == result.ulimit
    else:
        print(f"Warning: os.name is not 'posix': {os.name}; umask, "
               "group, shell, and ulimit not tested.")

def test_workingDirectory():
    logger = Logger(stack()[0][3], Path.cwd())
    command = "pwd"
    directory = "/tmp"
    if os.name == "posix":
        command = "pwd"
        directory = "/tmp"
    elif os.name == "nt":
        command = "cd"
        directory = "C:\\Users"
    else:
        print(f"Warning: os.name is unrecognized: {os.name}; test may fail.")
    result = logger.run(command, pwd=directory)
    assert result.stdout.strip() == directory
    assert result.pwd == directory

def test_trace():
    logger = Logger(stack()[0][3], Path.cwd())
    if os.uname().sysname == "Linux":
        result = logger.run("echo letter", trace="ltrace")
        assert 'getenv("POSIXLY_CORRECT")' in result.trace
        echoLocation = logger.run("which echo").stdout.strip()
        result = logger.run("echo hello", trace="strace")
        assert f'execve("{echoLocation}' in result.trace
    else:
        print(f"Warning: uname is not 'Linux': {os.uname()}; strace/ltrace "
               "not tested.")

def test_traceExpression():
    logger = Logger(stack()[0][3], Path.cwd())
    if os.uname().sysname == "Linux":
        result = logger.run("echo hello",
                         trace="ltrace",
                         expression='getenv')
        assert 'getenv("POSIXLY_CORRECT")' in result.trace
        assert result.trace.count('\n') == 2
    else:
        print(f"Warning: uname is not 'Linux': {os.uname()}; ltrace "
               "expression not tested.")

def test_traceSummary():
    logger = Logger(stack()[0][3], Path.cwd())
    if os.uname().sysname == "Linux":
        result = logger.run("echo hello", trace="ltrace", summary=True)
        assert 'getenv("POSIXLY_CORRECT")' not in result.trace
        assert "getenv" in result.trace
        echoLocation = logger.run("which echo").stdout.strip()
        result = logger.run("echo hello", trace="strace", summary=True)
        assert f'execve("{echoLocation}' not in result.trace
        assert "execve" in result.trace
    else:
        print(f"Warning: uname is not 'Linux': {os.uname()}; strace/ltrace "
               "summary not tested.")

def test_traceExpressionAndSummary():
    logger = Logger(stack()[0][3], Path.cwd())
    if os.uname().sysname == "Linux":
        echoLocation = logger.run("which echo").stdout.strip()
        result = logger.run("echo hello",
                         trace="strace",
                         expression="execve",
                         summary=True)
        assert f'execve("{echoLocation}' not in result.trace
        assert "execve" in result.trace
        assert "getenv" not in result.trace
        result = logger.run("echo hello",
                         trace="ltrace",
                         expression="getenv",
                         summary=True)
        assert 'getenv("POSIXLY_CORRECT")' not in result.trace
        assert "getenv" in result.trace
        assert "strcmp" not in result.trace
    else:
        print(f"Warning: uname is not 'Linux': {os.uname()}; strace/ltrace "
               "expression+summary not tested.")

def test_stats():
    logger = Logger(stack()[0][3], Path.cwd())
    result = logger.run("sleep 1", measure=["cpu", "memory", "disk"], interval=0.1)
    assert len(result.stats["memory"].data) > 8
    assert len(result.stats["memory"].data) < 30
    assert len(result.stats["cpu"].data) > 8
    assert len(result.stats["cpu"].data) < 30
    if os.name == "posix":
        assert len(result.stats["disk"]["/"].data) > 8
        assert len(result.stats["disk"]["/"].data) < 30
    else:
        print(f"Warning: os.name is not 'posix': {os.name}; disk usage not fully tested.")

def test_traceAndStats():
    logger = Logger(stack()[0][3], Path.cwd())
    if os.uname().sysname == "Linux":
        result = logger.run("sleep 1",
                         measure=["cpu", "memory", "disk"],
                         interval=0.1,
                         trace="ltrace",
                         expression="setlocale",
                         summary=True)
        assert "setlocale" in result.trace
        assert "sleep" not in result.trace
        assert len(result.stats["memory"].data) > 8
        assert len(result.stats["memory"].data) < 30
        assert len(result.stats["cpu"].data) > 8
        assert len(result.stats["cpu"].data) < 30
        assert len(result.stats["disk"]["/"].data) > 8
        assert len(result.stats["disk"]["/"].data) < 30
    else:
        print(f"Warning: uname is not 'Linux': {os.uname()}; ltrace not tested.")

def test_svg():
    logger = Logger(stack()[0][3], Path.cwd())
    result = logger.run("sleep 1", measure=["cpu"], interval=0.1)
    assert "<svg " in result.stats["cpu"].svg
    assert "</svg>" in result.stats["cpu"].svg

def test_log_book_traceAndStats():
    if os.uname().sysname == "Linux":
        logger = Logger(stack()[0][3], Path.cwd())
        result = logger.log("Sleep",
                            "sleep 1",
                            measure=["cpu", "memory", "disk"],
                            interval=0.1,
                            trace="ltrace",
                            expression="setlocale",
                            summary=True)
        assert "setlocale" in logger.log_book[0]["trace"]
        assert "sleep" not in logger.log_book[0]["trace"]
        assert len(logger.log_book[0]["stats"]["memory"]["data"]) > 8
        assert len(logger.log_book[0]["stats"]["memory"]["data"]) < 30
        assert len(logger.log_book[0]["stats"]["cpu"]["data"]) > 8
        assert len(logger.log_book[0]["stats"]["cpu"]["data"]) < 30
        assert len(logger.log_book[0]["stats"]["disk"]["/"]["data"]) > 8
        assert len(logger.log_book[0]["stats"]["disk"]["/"]["data"]) < 30
    else:
        print(f"Warning: uname is not 'Linux': {os.uname()}; ltrace not tested.")

def test_log_book_svg():
    logger = Logger(stack()[0][3], Path.cwd())
    result = logger.log("Sleep", "sleep 1", measure=["cpu"], interval=0.1)
    assert "<svg " in logger.log_book[0]["stats"]["cpu"]["svg"]
    assert "</svg>" in logger.log_book[0]["stats"]["cpu"]["svg"]

