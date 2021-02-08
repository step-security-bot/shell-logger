#!/usr/bin/env python3
from collections.abc import Iterable, Mapping
from io import StringIO
import itertools
import numpy as np
import matplotlib.pyplot as pyplot
import os
from queue import Queue
import subprocess
import sys
import tempfile
import time
from threading import Thread
from types import SimpleNamespace

def checkIfProgramExistsInPath(program):
    if os.name == "posix":
        subprocess.run(f"command -V {program}", shell=True, check=True)
    elif os.name == "nt":
        subprocess.run(f"where {program}", shell=True, check=True)

def runCommandWithConsole(command, **kwargs):
    with Console(**kwargs) as console:
        start = round(time.time() * 1000)
        stdin = None if not kwargs.get("devnull_stdin") else subprocess.DEVNULL
        popen = subprocess.Popen(command,
                                 shell=True,
                                 stdin=stdin,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
        console.attach(popen.stdout, popen.stderr)
        popen.wait()
        finish = round(time.time() * 1000)
        return SimpleNamespace(
            returncode = popen.returncode,
            args = popen.args,
            stdout = console.stdout.getvalue(),
            stderr = console.stderr.getvalue(),
            console = console.console.getvalue(),
            start = start,
            finish = finish,
            wall = finish - start
        )

def makeSVGLineChart(data):
    fig = pyplot.figure()
    pyplot.plot(*zip(*data))
    pyplot.yticks(np.arange(0, 110, 10))
    stringIO = StringIO()
    fig.savefig(stringIO, format='svg')
    pyplot.close(fig)
    stringIO.seek(0)
    lines = stringIO.readlines()
    svg = "".join(itertools.dropwhile(lambda line: "<svg" not in line, lines))
    return svg

def nestedSimpleNamespaceToDict(object):
    if "_asdict" in dir(object):
        return nestedSimpleNamespaceToDict(object._asdict())
    elif isinstance(object, (str, bytes, tuple)):
        return object
    elif isinstance(object, Mapping):
        return { k:nestedSimpleNamespaceToDict(v) for k, v in object.items() }
    elif isinstance(object, Iterable):
        return [ nestedSimpleNamespaceToDict(x) for x in object ]
    elif isinstance(object, SimpleNamespace):
        return nestedSimpleNamespaceToDict(object.__dict__)
    else:
        return object

class Console():
    class Console(StringIO):
        def __init__(self, file, console):
            super().__init__()
            self.console = console
            self.file = file
        def write(self, string):
            if type(string) == bytes:
                string = string.decode()
            super().write(string)
            self.file.write(string)
            self.console.combined.put(string)
    def __init__(self, **kwargs):
        stdoutFile = open(os.devnull, "w") if kwargs.get("quietStdout") else sys.stdout
        stderrFile = open(os.devnull, "w") if kwargs.get("quietStderr") else sys.stderr
        self.stdout = Console.Console(stdoutFile, self)
        self.stderr = Console.Console(stderrFile, self)
        self.combined = Queue()
    def close(self):
        if self.stdout.file != sys.stdout:
            self.stdout.file.close()
        if self.stderr.file != sys.stderr:
            self.stderr.file.close()
    def __enter__(self):
        return self
    def __exit__(self, type, value, traceback):
        self.close()
    @property
    def console(self):
        return StringIO("".join(self.combined.queue))
    def attach(self, stdout, stderr):
        def tee(file, output):
            with file:
                for line in iter(file.readline, b""):
                    output.write(line)
        threads = [
            Thread(target=tee, args=(stdout, self.stdout)),
            Thread(target=tee, args=(stderr, self.stderr)),
        ]
        for thread in threads:
            thread.daemon = True
            thread.start()
        for thread in threads:
            thread.join()

