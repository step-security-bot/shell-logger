#!/usr/bin/env python3

from __future__ import annotations
from .classes import (Trace, StatsCollector, trace_collector, stats_collectors)
from .Shell import Shell
from .util import (nested_simplenamespace_to_dict, opening_html_text,
                   closing_html_text, append_html, html_message_card,
                   message_card, command_card, child_logger_card,
                   parent_logger_card_html)
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Iterator, List, Optional, Tuple, Union
from distutils import dir_util
import json
from multiprocessing.managers import SyncManager
import os
from pathlib import Path
import random
import shutil
import string
import tempfile
import time
from types import SimpleNamespace
try:
    import psutil
except ModuleNotFoundError:
    psutil = None


class ShellLoggerEncoder(json.JSONEncoder):
    """
    This is a helper class to make the :class:`ShellLogger` class JSON
    serializable.  It is used in the process of saving
    :class:`ShellLogger` objects to JSON.

    Usage::

        import json
        with open('path_to_json_file', 'w') as jf:
            json.dump(data, jf, cls=ShellLoggerEncoder)
    """

    def default(self, obj: object) -> object:
        """
        Serialize an object; that is, encode it in a string format.

        Parameters:
            obj:  Any Python object.

        Returns:
            The JSON serialization of the given object.
        """
        if isinstance(obj, ShellLogger):
            return {**{'__type__': 'ShellLogger'},
                    **{k: self.default(v) for k, v in obj.__dict__.items()}}
        elif isinstance(obj, (int, float, str, bytes)):
            return obj
        elif isinstance(obj, Mapping):
            return {k: self.default(v) for k, v in obj.items()}
        elif isinstance(obj, tuple):
            return {'__type__': 'tuple',
                    'items': obj}
        elif isinstance(obj, Iterable):
            return [self.default(x) for x in obj]
        elif isinstance(obj, datetime):
            return {'__type__': 'datetime',
                    'value': obj.strftime('%Y-%m-%d_%H:%M:%S:%f'),
                    'format': '%Y-%m-%d_%H:%M:%S:%f'}
        elif isinstance(obj, Path):
            return {'__type__': 'Path',
                    'value': str(obj)}
        elif obj is None:
            return None
        elif isinstance(obj, Shell):
            return {"__type__": "Shell",
                    "pwd": obj.pwd(),
                    "login_shell": obj.login_shell}
        else:
            return json.JSONEncoder.default(self, obj)


class ShellLoggerDecoder(json.JSONDecoder):
    """
    This is a helper class to make the :class:`ShellLogger` class JSON
    serializable.  It is used in the process of retrieving
    :class:`ShellLogger` objects from JSON.

    Usage::

        import json
        with open('path_to_json_file', 'r') as jf:
            logger = json.load(jf, cls=ShellLoggerDecoder)
    """

    def __init__(self):
        """
        Initialize the decoder.
        """
        json.JSONDecoder.__init__(self, object_hook=self.dict_to_object)

    @staticmethod
    def dict_to_object(obj: dict) -> object:
        """
        This converts data dictionaries given by the JSONDecoder into
        objects of type :class:`ShellLogger`, :class:`datetime`, etc.

        Parameters:
            obj:  The JSON-serialized representation of an object.

        Returns:
            The object represented by the JSON serialization.
        """
        if '__type__' not in obj:
            return obj
        elif obj['__type__'] == 'ShellLogger':
            logger = ShellLogger(obj["name"], obj["log_dir"],
                                 obj["stream_dir"], obj["html_file"],
                                 obj["indent"], obj["login_shell"],
                                 obj["log_book"], obj["init_time"],
                                 obj["done_time"], obj["duration"])
            return logger
        elif obj['__type__'] == 'datetime':
            return datetime.strptime(obj['value'], obj['format'])
        elif obj['__type__'] == 'Path':
            return Path(obj['value'])
        elif obj['__type__'] == 'tuple':
            return tuple(obj['items'])
        elif obj['__type__'] == 'Shell':
            return Shell(Path(obj['pwd']), obj["login_shell"])


class ShellLogger:
    """
    This class will keep track of commands run in the shell, their
    durations, descriptions, ``stdout``, ``stderr``, and
    ``return_code``.  When the :func:`finalize` method is called, the
    :class:`ShellLogger` object will aggregate all the data from its
    commands and child :class:`ShellLogger` objects (see example below)
    into both JSON and HTML files.

    Example::

        > Parent ShellLogger Object Name
            Duration: 18h 20m 35s
          > cmd1  (Click arrow '>' to expand for more details)
            Duration: 0.25s
          > Child ShellLogger Object Name (i.e. Trilinos)
            Duration: 3h 10m 0s
            > Child ShellLogger Object Name (i.e. Configure)
              Duration: 1m 3s
              > cmd1
        etc...

    Note:
        Because some ``stdout``/``stderr`` streams can be quite long,
        they will be written to files in a temporary directory
        (``log_dir/tmp/YYYY-MM-DD_hh:mm:ss/``).  Once the
        :func:`finalize` method is called, they will be aggregated in an
        HTML file (``log_dir/html_file``).  The JSON file
        (``log_dir/json_file``) will contain references to the
        ``stdout``/``stderr`` files so that an HTML file can be
        recreated again later if needed.

    Attributes:
        name (str):  The name of the :class:`ShellLogger` object.
        log_dir (Path):  Path to where the logs are stored for the
            parent :class:`ShellLogger` and all its children.
        stream_dir (Path):  Path to directory where
            ``stdout``/``stderr`` stream logs are stored.
        html_file (Path):  Path to main HTML file for the parent and
            child :class:`ShellLogger` objects.
        indent (int):  The indentation level of this
            :class:`ShellLogger` object.  The parent has a level 0.
            Each successive child's indent is increased by 1.
        login_shell (bool):  Whether or not the :class:`Shell` spawned
            should be a login shell.
        log_book (list):  A list containing log entries and child
            :class:`ShellLogger` objects in the order they were created.
        init_time (datetime):  The time this :class:`ShellLogger` object
            was created.
        done_time (datetime):  The time this :class:`ShellLogger` object
            is done with its commands/messages.
        duration (str):  The string-formatted duration of this
            :class:`ShellLogger`, updated when the :func:`finalize`
            method is called.
        shell (Shell):  The :class:`Shell` in which all commands will be
            run when logging.
    """

    @staticmethod
    def append(path: Path) -> ShellLogger:
        """
        Create a :class:`ShellLogger` to append to the HTML log file
        generated by a prior :class:`ShellLogger`.

        Parameters:
            path:  The location of the prior :class:`ShellLogger` 's
                output, either the log directory, or the HTML log file
                itself.

        Returns:
            A new :class:`ShellLogger` populated with the data from the
            prior one.
        """

        # Ensure the given `path` is valid.
        if path.is_dir():
            try:
                path = next(path.glob("*.html"))
            except StopIteration:
                raise RuntimeError(f"{path} does not have an html file.")
        if path.is_symlink():
            path = path.resolve(strict=True)
        if path.is_file() and path.name[-5:] == ".html":
            path = path.parent / (path.name[:-5] + ".json")

        # Deserialize the corresponding JSON object into a ShellLogger.
        with open(path, "r") as jf:
            loaded_logger = json.load(jf, cls=ShellLoggerDecoder)
        return loaded_logger

    def __init__(
            self,
            name: str,
            log_dir: Path = Path.cwd(),
            stream_dir: Optional[Path] = None,
            html_file: Optional[Path] = None,
            indent: int = 0,
            login_shell: bool = False,
            log: Optional[List[object]] = None,
            init_time: Optional[datetime] = None,
            done_time: Optional[datetime] = None,
            duration: Optional[str] = None
    ) -> None:
        """
        Initialize a :class:`ShellLogger` object.

        Parameters:
            name:  The name to give to this :class:`ShellLogger` object.
            log_dir:  Where to store the log files.
            stream_dir:  Where the ``stdout``/``stderr`` stream logs are
                stored.  This is helpful for parent :class:`ShellLogger`
                objects to give to child :class:`ShellLogger` objects in
                order to keep things in the same directory.
            html_file:  The path to the main HTML file for the parent
                and children :class:`ShellLogger` objects.  If omitted,
                this is the parent :class:`ShellLogger` object, and it
                will need to create the file.
            indent:  The indentation level of this :class:`ShellLogger`
                object.  The parent has a level 0.  Each successive
                child's indent is increased by 1.
            login_shell:  Whether or not the :class:`Shell` spawned
                should be a login shell.
            log:  Optionally provide an existing log list to the
                :class:`ShellLogger` object.
            init_time:  Optionally specify when this
                :class:`ShellLogger` was initialized.
            done_time:  Optionally specify when this
                :class:`ShellLogger` was finalized.
            duration:  A string representation of the total duration of
                the :class:`ShellLogger`.

        Note:
            The ``log``, ``init_time``, ``done_time``, and ``duration``
            parameters are mainly used when importing
            :class:`ShellLogger` objects from a JSON file, and can
            generally be omitted.
        """
        self.name = name
        self.log_book: List[Union[dict, ShellLogger]] = (
            log if log is not None else []
        )
        self.init_time = datetime.now() if init_time is None else init_time
        self.done_time = datetime.now() if done_time is None else done_time
        self.duration = duration
        self.indent = indent
        self.login_shell = login_shell
        self.shell = Shell(Path.cwd(), self.login_shell)

        # Create the log directory, if needed.
        self.log_dir = log_dir.resolve()
        if not self.log_dir.exists():
            self.log_dir.mkdir(parents=True, exist_ok=True)

        # If there isn't a `stream_dir` given by the parent ShellLogger, this
        # is the parent; create the `stream_dir`.
        if stream_dir is None:
            self.stream_dir = Path(tempfile.mkdtemp(
                dir=self.log_dir,
                prefix=self.init_time.strftime("%Y-%m-%d_%H.%M.%S.%f_")
            )).resolve()
        else:
            self.stream_dir = stream_dir.resolve()

        # Create (or append to) the HTML log file.
        if html_file is None:
            self.html_file = self.stream_dir / (self.name.replace(' ', '_')
                                                + '.html')
        else:
            self.html_file = html_file.resolve()
        if self.is_parent():
            if self.html_file.exists():
                with open(self.html_file, 'a') as f:
                    f.write(f"<!-- {self.init_time:} Append to log started "
                            "-->")
            else:
                self.html_file.touch()

    def is_parent(self) -> bool:
        """
        Determine whether or not this is the parent :class:`ShellLogger`
        object, as indicated by the object's :attr:`indent` attribute.

        Returns:
            ``True`` if this is the parent; ``False`` otherwise.
        """
        return self.indent == 0

    def update_done_time(self) -> None:
        """
        Allows the :attr:`done_time` to be updated before
        :func:`finalize` is called.  This is especially useful for child
        :class:`ShellLogger` objects who might finish their commands
        before the parent finalizes everything.
        """
        self.done_time = datetime.now()

    def __update_duration(self) -> None:
        """
        Updates the :attr:`duration` attribute with the time from the
        beginning of the :class:`ShellLogger` object's creation until
        now.
        """
        self.update_done_time()
        self.duration = self.strfdelta(self.done_time - self.init_time,
                                       "{hrs}h {min}m {sec}s")

    def check_duration(self) -> str:
        """
        Get the current duration from the beginning of the
        :class:`ShellLogger` object's creation until now.

        Returns:
            A string representation of the total duration.
        """
        return self.strfdelta(datetime.now() - self.init_time,
                              "{hrs}h {min}m {sec}s")

    def change_log_dir(self, new_log_dir: Path) -> None:
        """
        Change the :attr:`log_dir` of this :class:`ShellLogger` object
        and all children recursively.

        Parameters:
            new_log_dir (Path):  Path to the new :attr:`log_dir`.

        Raises:
            RuntimeError:  If this is called on a child
                :class:`ShellLogger`.
        """
        if not self.is_parent():
            raise RuntimeError("You should not change the log directory of a "
                               "child `ShellLogger`; only that of the parent.")

        # This only gets executed once by the top-level parent
        # `ShellLogger` object.
        if self.log_dir.exists():
            dir_util.copy_tree(str(self.log_dir), str(new_log_dir))
            shutil.rmtree(self.log_dir)

        # Change the `stream_dir`, `html_file`, and `log_dir` for every
        # child `ShellLogger` recursively.
        self.stream_dir = (new_log_dir
                           / self.stream_dir.relative_to(self.log_dir))
        self.html_file = new_log_dir / self.html_file.relative_to(self.log_dir)
        self.log_dir = new_log_dir.resolve()
        for log in self.log_book:
            if isinstance(log, ShellLogger):
                log.change_log_dir(self.log_dir)

    def add_child(self, child_name: str) -> ShellLogger:
        """
        Creates and returns a 'child' :class:`ShellLogger` object.  This
        will be one step indented in the tree of the output log (see
        the example in the class docstring).  The total time for this
        child will be recorded when the :func:`finalize` method is
        called in the child object.

        Parameters:
            child_name:  The name of the child :class:`ShellLogger`
                object.

        Returns:
            ShellLogger:  A child :class:`ShellLogger` object.
        """

        # Create the child object and add it to the list of children.
        child = ShellLogger(child_name, self.log_dir, self.stream_dir,
                            self.html_file, self.indent + 1, self.login_shell)
        self.log_book.append(child)
        return child

    @staticmethod
    def strfdelta(delta: timedelta, fmt: str) -> str:
        """
        Format a time delta object.  Use this like you would
        :func:`datetime.strftime`.

        Parameters:
            delta:  The time delta object.
            fmt:  The delta format string.

        Returns:
            A string representation of the time delta.
        """

        # Dictionary to hold time delta info.
        d = {'days': delta.days}
        microseconds_per_second = 10**6
        seconds_per_minute = 60
        minutes_per_hour = 60
        total_ms = delta.microseconds + (delta.seconds
                                         * microseconds_per_second)
        d['hrs'], rem = divmod(total_ms, (minutes_per_hour
                                          * seconds_per_minute
                                          * microseconds_per_second))
        d['min'], rem = divmod(rem, (seconds_per_minute
                                     * microseconds_per_second))
        d['sec'] = rem / microseconds_per_second

        # Round to 2 decimals
        d['sec'] = round(d['sec'], 2)

        # String template to help with recognizing the format.
        return fmt.format(**d)

    def print(self, msg: str, end: str = '\n') -> None:
        """
        Print a message and save it to the log.

        Parameters:
            msg:  The message to print and save to the log.
            end:  The string appended after the message:
        """
        print(msg, end=end)
        log = {
            'msg': msg,
            'timestamp': str(datetime.now()),
            'cmd': None
        }
        self.log_book.append(log)

    def html_print(self, msg: str, msg_title: str = "HTML Message") -> None:
        """
        Save a message to the log but don't print it in the console.

        Parameters:
            msg:  Message to save to the log.
            msg_title:  Title of the message to save to the log.
        """
        log = {
            'msg': msg,
            'msg_title': msg_title,
            'timestamp': str(datetime.now()),
            'cmd': None
        }
        self.log_book.append(log)

    def to_html(self) -> Union[Iterator[str], List[Iterator[str]]]:
        """
        This method iterates through each entry in this
        :class:`ShellLogger` object's log list and builds up a list of
        corresponding HTML snippets.  For each entry, the
        ``stdout``/``stderr`` are copied from their respective files in
        the :attr:`stream_dir`.

        Returns:
            A generator (or list of generators) that will lazily yield
            strings corresponding to the elements of the HTML file.
            This lazy evaluation was done to avoid loading *all* the
            data for the log file into memory at once.
        """
        html = []
        for log in self.log_book:

            # If this is a child ShellLogger...
            if isinstance(log, ShellLogger):

                # Update the duration of this ShellLogger's commands.
                if log.duration is None:
                    log.__update_duration()
                html.append(child_logger_card(log))

            # Otherwise, if this is a message being logged...
            elif log["cmd"] is None:
                if log.get("msg_title") is None:
                    html.append(message_card(log))
                else:
                    html.append(html_message_card(log))

            # Otherwise, if this is a command being logged...
            else:
                html.append(command_card(log, self.stream_dir))
        if self.is_parent():
            return parent_logger_card_html(self.name, html)
        else:
            return html

    def finalize(self) -> None:
        """
        Finalize the :class:`ShellLogger` object by writing the HTML log
        file.
        """
        if self.is_parent():
            html_text = opening_html_text() + "\n"
            with open(self.html_file, 'w') as f:
                f.write(html_text)

        for element in self.to_html():
            append_html(element, output=self.html_file)

        if self.is_parent():
            with open(self.html_file, 'a') as html:
                html.write(closing_html_text())
                html.write('\n')

            # Create a symlink in `log_dir` to the HTML file in
            # `stream_dir`.
            curr_html_file = self.html_file.name
            new_location = self.log_dir / curr_html_file
            temp_link_name = Path(tempfile.mktemp(dir=self.log_dir))
            temp_link_name.symlink_to(self.html_file)
            temp_link_name.replace(new_location)

            # Save everything to a JSON file in the timestamped
            # `stream_dir`.
            json_file = self.stream_dir / (self.name.replace(' ', '_')
                                           + '.json')
            with open(json_file, 'w') as jf:
                json.dump(self, jf, cls=ShellLoggerEncoder, sort_keys=True,
                          indent=4)

    def log(
            self,
            msg: str,
            cmd: str,
            cwd: Optional[Path] = None,
            live_stdout: bool = False,
            live_stderr: bool = False,
            return_info: bool = False,
            verbose: bool = False,
            stdin_redirect: bool = True,
            **kwargs
    ) -> dict:
        """
        Execute a command, and log the corresponding information.

        Parameters:
            msg:  A message to be recorded with the command.  This could
                be documentation of what your command is doing and why.
            cmd:  The shell command to be executed.
            cwd:  Where to execute the command.
            live_stdout:  Print ``stdout`` as it is being produced, as
                well as saving it to the file.
            live_stderr:  Print ``stderr`` as it is being produced, as
                well as saving it to the file.
            return_info:  If set to ``True``, ``stdout``, ``stderr``,
                and ``return_code`` will be stored and returned in a
                dictionary.  Consider leaving this set to ``False`` if
                you anticipate your command producing large
                ``stdout``/``stderr`` streams that could cause memory
                issues.
            verbose:  Print the command before it is executed.
            stdin_redirect:  Whether or not to redirect ``stdin`` to
                ``/dev/null``.  We do this by default to handle issues
                that arise when the ``cmd`` involves MPI; however, in
                some cases (e.g., involving ``bsub``) the redirect
                causes problems, and we need the flexibility to revert
                back to standard behavior.
            **kwargs:  Any other keyword arguments to pass on to
                :func:`_run`.

        Returns:
            A dictionary containing ``stdout``, ``stderr``, ``trace``,
            and ``return_code`` keys.  If ``return_info`` is set to
            ``False``, the ``stdout`` and ``stderr`` values will be
            ``None``.  If ``return_info`` is set to ``True`` and
            ``trace`` is specified in ``kwargs``, ``trace`` in the
            dictionary will contain the output of the specified trace;
            otherwise, it will be ``None``.

        Note:
            To conserve memory, ``stdout`` and ``stderr`` will be
            written to files as they are being generated.
        """
        start_time = datetime.now()

        # Create a unique command ID that will be used to find the
        # location of the `stdout`/`stderr` files in the temporary
        # directory during finalization.
        cmd_id = 'cmd_' + ''.join(random.choice(string.ascii_lowercase)
                                  for _ in range(9))

        # Create & open files for `stdout`, `stderr`, and trace data.
        time_str = start_time.strftime("%Y-%m-%d_%H%M%S")
        stdout_path = self.stream_dir / f"{time_str}_{cmd_id}_stdout"
        stderr_path = self.stream_dir / f"{time_str}_{cmd_id}_stderr"
        trace_path = (self.stream_dir / f"{time_str}_{cmd_id}_trace"
                      if kwargs.get("trace") else None)

        # Print the command to be executed.
        with open(stdout_path, 'a'), open(stderr_path, 'a'):
            if verbose:
                print(cmd)

        # Initialize the log information.
        log = {'msg': msg,
               'duration': None,
               'timestamp': start_time.strftime("%Y-%m-%d_%H%M%S"),
               'cmd': cmd,
               'cmd_id': cmd_id,
               'cwd': cwd,
               'return_code': 0}

        # Execute the command.
        result = self._run(cmd,
                           quiet_stdout=not live_stdout,
                           quiet_stderr=not live_stderr,
                           stdout_str=return_info,
                           stderr_str=return_info,
                           trace_str=return_info,
                           stdout_path=stdout_path,
                           stderr_path=stderr_path,
                           trace_path=trace_path,
                           devnull_stdin=stdin_redirect,
                           pwd=cwd,
                           **kwargs)

        # Update the log information and save it to the `log_book`.
        h = int(result.wall / 3600000)
        m = int(result.wall / 60000) % 60
        s = int(result.wall / 1000) % 60
        log["duration"] = f"{h}h {m}m {s}s"
        log["return_code"] = result.returncode
        log = {**log, **nested_simplenamespace_to_dict(result)}
        self.log_book.append(log)
        return {'return_code': log['return_code'],
                'stdout': result.stdout, 'stderr': result.stderr}

    def _run(self, command: str, **kwargs) -> SimpleNamespace:
        """
        Execute a command, capturing various information as you go.

        Parameters:
            command:  The command to execute.
            **kwargs:  Additional arguments to be passed on to the
                :class:`StatsCollector` s, :class:`Trace` s,
                :func:`shell.run`, etc.

        Returns:
            The command run, along with its output, and various metadata
            and diagnostic information captured while it ran.

        Todo:
            * Replace `**kwargs` with actual parameters.
        """
        completed_process, trace_output = None, None
        for key in ["stdout_str", "stderr_str", "trace_str"]:
            if key not in kwargs:
                kwargs[key] = True

        # Change to the directory in which to execute the command.
        old_pwd = Path(os.getcwd())
        if kwargs.get("pwd"):
            self.shell.cd(kwargs.get("pwd"))
        aux_info = self.auxiliary_information()

        # Stats collectors use a multiprocessing manager that creates
        # unix domain sockets with names determined by
        # `tempfile.mktemp`, which looks at `TMPDIR`.  If `TMPDIR` is
        # too long, it may result in the multiprocessing manager trying
        # to use a string too long for UNIX domain sockets, resulting in
        # "OSError: AF_UNIX path too long."  The typical maximum path
        # length on Linux is 108.  See: `grep '#define UNIX_PATH_MAX'
        # /usr/include/linux/un.h`.
        old_tmpdir = os.environ.get("TMPDIR")
        os.environ["TMPDIR"] = "/tmp"

        # Start up any stats or trace collectors the user has requested.
        collectors = stats_collectors(**kwargs)
        stats = {} if len(collectors) > 0 else None
        for collector in collectors:
            collector.start()
        if old_tmpdir is not None:
            os.environ["TMPDIR"] = old_tmpdir
        else:
            os.unsetenv("TMPDIR")
            del os.environ["TMPDIR"]
        if "trace" in kwargs:
            trace = trace_collector(**kwargs)
            command = trace.command(command)
            trace_output = trace.output_path

        # Run the command, and stop any collectors that were started.
        completed_process = self.shell.run(command, **kwargs)
        for collector in collectors:
            stats[collector.stat_name] = collector.finish()
        setattr(completed_process, "trace_path", trace_output)
        setattr(completed_process, "stats", stats)
        if kwargs.get("trace_str") and trace_output:
            with open(trace_output) as f:
                setattr(completed_process, "trace", f.read())
        else:
            setattr(completed_process, "trace", None)

        # Change back to the original directory and return the results.
        if kwargs.get("pwd"):
            self.shell.cd(old_pwd)
        return SimpleNamespace(**completed_process.__dict__,
                               **aux_info.__dict__)

    def auxiliary_information(self) -> SimpleNamespace:
        """
        Capture all sorts of auxiliary information before running a
        command.

        Returns:
            The working directory, environment, umask, hostname, user,
            group, shell, and ulimit.
        """
        pwd, _ = self.shell.auxiliary_command(posix="pwd", nt="cd", strip=True)
        environment, _ = self.shell.auxiliary_command(posix="env", nt="set")
        umask, _ = self.shell.auxiliary_command(posix="umask", strip=True)
        hostname, _ = self.shell.auxiliary_command(posix="hostname",
                                                   nt="hostname",
                                                   strip=True)
        user, _ = self.shell.auxiliary_command(posix="whoami",
                                               nt="whoami",
                                               strip=True)
        group, _ = self.shell.auxiliary_command(posix="id -gn", strip=True)
        shell, _ = self.shell.auxiliary_command(posix="printenv SHELL",
                                                strip=True)
        ulimit, _ = self.shell.auxiliary_command(posix="ulimit -a")
        return SimpleNamespace(pwd=pwd,
                               environment=environment,
                               umask=umask,
                               hostname=hostname,
                               user=user,
                               group=group,
                               shell=shell,
                               ulimit=ulimit)


@Trace.subclass
class Strace(Trace):
    """
    An interface between :class:`ShellLogger` and the ``strace``
    command.
    """
    trace_name = "strace"

    def __init__(self, **kwargs) -> None:
        """
        Initialize the :class:`Strace` instance.
        """
        super().__init__(**kwargs)
        self.summary = True if kwargs.get("summary") else False
        self.expression = kwargs.get("expression")

    @property
    def trace_args(self) -> str:
        """
        Wraps a command in a ``strace`` command.
        """
        args = f"strace -f -o {self.output_path}"
        if self.summary:
            args += " -c"
        if self.expression:
            args += f" -e '{self.expression}'"
        return args


@Trace.subclass
class Ltrace(Trace):
    """
    An interface between :class:`ShellLogger` and the ``ltrace``
    command.
    """
    trace_name = "ltrace"

    def __init__(self, **kwargs):
        """
        Initialize the :class:`Ltrace` instance.
        """
        super().__init__(**kwargs)
        self.summary = True if kwargs.get("summary") else False
        self.expression = kwargs.get("expression")

    @property
    def trace_args(self):
        """
        Wraps a command in a ``ltrace`` command.
        """
        args = f"ltrace -C -f -o {self.output_path}"
        if self.summary:
            args += " -c"
        if self.expression:
            args += f" -e '{self.expression}'"
        return args


if psutil is not None:
    @StatsCollector.subclass
    class DiskStatsCollector(StatsCollector):
        """
        A means of running commands while collecting disk usage
        statistics.
        """
        stat_name = "disk"

        def __init__(self, interval: float, manager: SyncManager) -> None:
            """
            Initialize the :class:`DiskStatsCollector` object.

            Parameters:
                interval:  How many seconds to sleep between polling.
                manager:  The multiprocessing manager used to control
                    the process used to collect the statistics.
            """
            super().__init__(interval, manager)
            self.stats = manager.dict()
            self.mount_points = [
                p.mountpoint for p in psutil.disk_partitions()
            ]
            for location in ["/tmp",
                             "/dev/shm",
                             f"/var/run/user/{os.getuid()}"]:
                if (location not in self.mount_points
                        and Path(location).exists()):
                    self.mount_points.append(location)
            for m in self.mount_points:
                self.stats[m] = manager.list()

        def collect(self) -> None:
            """
            Poll the disks to determine how much free space they have.
            """
            milliseconds_per_second = 10**3
            timestamp = round(time.time() * milliseconds_per_second)
            for m in self.mount_points:
                self.stats[m].append((timestamp, psutil.disk_usage(m).percent))

        def unproxied_stats(self) -> dict:
            """
            Translate the statistics from the multiprocessing
            ``SyncManager`` 's data structure to a ``dict``.

            Returns:
                A mapping from the disk mount points to tuples of
                timestamps and percent of disk space free.
            """
            return {k: list(v) for k, v in self.stats.items()}

    @StatsCollector.subclass
    class CPUStatsCollector(StatsCollector):
        """
        A means of running commands while collecting CPU usage
        statistics.
        """
        stat_name = "cpu"

        def __init__(self, interval: float, manager: SyncManager) -> None:
            """
            Initialize the :class:`CPUStatsCollector` object.

            Parameters:
                interval:  How many seconds to sleep between polling.
                manager:  The multiprocessing manager used to control
                    the process used to collect the statistics.
            """
            super().__init__(interval, manager)
            self.stats = manager.list()

        def collect(self) -> None:
            """
            Determine how heavily utilized the CPU is at the moment.
            """
            milliseconds_per_second = 10**3
            timestamp = round(time.time() * milliseconds_per_second)
            self.stats.append((timestamp, psutil.cpu_percent(interval=None)))

        def unproxied_stats(self) -> List[Tuple[float, float]]:
            """
            Translate the statistics from the multiprocessing
            ``SyncManager`` 's data structure to a ``list``.

            Returns:
                A list of (timestamp, % CPU used) data points.
            """
            return list(self.stats)

    @StatsCollector.subclass
    class MemoryStatsCollector(StatsCollector):
        """
        A means of running commands while collecting memory usage
        statistics.
        """
        stat_name = "memory"

        def __init__(self, interval: float, manager: SyncManager) -> None:
            """
            Initialize the :class:`MemoryStatsCollector` object.

            Parameters:
                interval:  How many seconds to sleep between polling.
                manager:  The multiprocessing manager used to control
                    the process used to collect the statistics.
            """
            super().__init__(interval, manager)
            self.stats = manager.list()

        def collect(self) -> None:
            """
            Determine how much memory is currently being used.
            """
            milliseconds_per_second = 10**3
            timestamp = round(time.time() * milliseconds_per_second)
            self.stats.append((timestamp, psutil.virtual_memory().percent))

        def unproxied_stats(self) -> List[Tuple[float, float]]:
            """
            Translate the statistics from the multiprocessing
            ``SyncManager`` 's data structure to a ``list``.

            Returns:
                A list of (timestamp, % memory used) data points.
            """
            return list(self.stats)

# If we don't have `psutil`, return null objects.
else:
    @StatsCollector.subclass
    class DiskStatsCollector(StatsCollector):
        """
        A phony :class:`DiskStatsCollector` used when ``psutil`` is
        unavailable.  This collects no disk statistics.
        """
        stat_name = "disk"

        def __init__(self, interval: float, manager: SyncManager) -> None:
            """
            Initialize the object via the parent's constructor.

            Parameters:
                interval:  How many seconds to sleep between polling.
                manager:  The multiprocessing manager used to control
                    the process used to collect the statistics.
            """
            super().__init__(interval, manager)

        def collect(self) -> None:
            """
            Don't collect any disk statistics.
            """
            pass

        def unproxied_stats(self) -> None:
            """
            If asked for the disk statistics, don't provide any.

            Returns:
                None
            """
            return None

    @StatsCollector.subclass
    class CPUStatsCollector(StatsCollector):
        """
        A phony :class:`CPUStatsCollector` used when ``psutil`` is
        unavailable.  This collects no CPU statistics.
        """
        stat_name = "cpu"

        def __init__(self, interval: float, manager: SyncManager) -> None:
            """
            Initialize the object via the parent's constructor.

            Parameters:
                interval:  How many seconds to sleep between polling.
                manager:  The multiprocessing manager used to control
                    the process used to collect the statistics.
            """
            super().__init__(interval, manager)

        def collect(self) -> None:
            """
            Don't collect any CPU statistics.
            """
            pass

        def unproxied_stats(self) -> None:
            """
            If asked for CPU statistics, don't provide any.

            Returns:
                None
            """
            return None

    @StatsCollector.subclass
    class MemoryStatsCollector(StatsCollector):
        """
        A phony :class:`MemoryStatsCollector` used when ``psutil`` is
        unavailable.  This collects no memory statistics.
        """
        stat_name = "memory"

        def __init__(self, interval: float, manager: SyncManager) -> None:
            """
            Initialize the object via the parent's constructor.

            Parameters:
                interval:  How many seconds to sleep between polling.
                manager:  The multiprocessing manager used to control
                    the process used to collect the statistics.
            """
            super().__init__(interval, manager)

        def collect(self) -> None:
            """
            Don't collect any memory statistics.
            """
            pass

        def unproxied_stats(self) -> None:
            """
            If asked for memory statistics, don't provide any.

            Returns:
                None
            """
            return None
