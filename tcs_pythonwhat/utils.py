from types import ModuleType
import copy
import os


def include_v1():
    return os.environ.get("PYTHONWHAT_V2_ONLY", "") != "1"


def v2_only():
    return not include_v1()

def shorten_string(text):
    if len(text) > 50:
        text = text[0:45] + "..."
    return text

def has_newline(text):
    return "\n" in text


def copy_env(env):
    mutableTypes = (tuple, list, dict)
    # One list comprehension to filter list. Might need some cleaning, but it
    # works
    ipy_ignore = ["In", "Out", "get_ipython", "quit", "exit"]
    update_env = {
        key: copy.deepcopy(value)
        for key, value in env.items()
        if not any(
            (key.startswith("_"), isinstance(value, ModuleType), key in ipy_ignore)
        )
        and isinstance(value, mutableTypes)
    }
    updated_env = dict(env)
    updated_env.update(update_env)
    return updated_env


def first_lower(s):
    return s[:1].lower() + s[1:] if s else ""


def check_str(x):
    assert isinstance(x, str), "объект не является строкой там, где ожидается строка."
    return x


def check_dict(x):
    assert isinstance(x, dict), "объект не является словарем там, где ожидается словарь."
    return x


def check_process(x):
    assert "Process" in x.__class__.__name__
    return x
