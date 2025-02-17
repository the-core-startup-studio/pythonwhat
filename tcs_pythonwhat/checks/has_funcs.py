from tcs_protowhat.utils_messaging import get_ord
from tcs_pythonwhat.tasks import (
    getResultInProcess,
    getOutputInProcess,
    getErrorInProcess,
    ReprFail,
    isDefinedInProcess,
    getOptionFromProcess,
    UndefinedValue,
)
from tcs_pythonwhat.Test import EqualTest, DefinedCollTest
from tcs_protowhat.Feedback import Feedback, FeedbackComponent
from tcs_protowhat.failure import InstructorError, debugger
from tcs_pythonwhat import utils
from functools import partial
import re
import copy
import ast

evalCalls = {
    "value": getResultInProcess,
    "output": getOutputInProcess,
    "error": getErrorInProcess,
}


def has_part(state, name, msg, fmt_kwargs=None, index=None):
    d = {
        "sol_part": state.solution_parts,
        "stu_part": state.student_parts,
        **fmt_kwargs,
    }

    def verify(part, index):
        if index is not None:
            if isinstance(index, list):
                for ind in index:
                    part = part[ind]
            else:
                part = part[index]
        if part is None:
            raise KeyError

    # TODO: instructor error if msg is not str
    # Check if it's there in the solution
    try:
        verify(state.solution_parts[name], index)
    except (KeyError, IndexError):
        with debugger(state):
            err_msg = "SCT fails on solution: {}".format(msg)
            state.report(err_msg, d)

    try:
        verify(state.student_parts[name], index)
    except (KeyError, IndexError):
        state.report(msg, d)

    return state


def has_equal_part(state, name, msg):
    d = {
        "stu_part": state.student_parts,
        "sol_part": state.solution_parts,
        "name": name,
    }

    state.do_test(
        EqualTest(d["stu_part"][name], d["sol_part"][name], FeedbackComponent(msg, d))
    )

    return state


# TODO: shouldn't have to hardcode message
def has_equal_part_len(state, name, unequal_msg):
    """Verify that a part that is zoomed in on has equal length.

    Typically used in the context of ``check_function_def()``

    Arguments:
        name (str): name of the part for which to check the length to the corresponding part in the solution.
        unequal_msg (str): Message in case the lengths do not match.
        state (State): state as passed by the SCT chain. Don't specify this explicitly.

    :Examples:

        Student and solution code::

            def shout(word):
                return word + '!!!'

        SCT that checks number of arguments::

            Ex().check_function_def('shout').has_equal_part_len('args', 'not enough args!')
    """
    d = dict(
        stu_len=len(state.student_parts[name]), sol_len=len(state.solution_parts[name])
    )

    if d["stu_len"] != d["sol_len"]:
        state.report(unequal_msg, d)

    return state


# Expression tests -----------------------------------------------------------


def has_equal_ast(state, incorrect_msg=None, code=None, exact=True, append=None):
    """Test whether abstract syntax trees match between the student and solution code.

    ``has_equal_ast()`` can be used in two ways:

    * As a robust version of ``has_code()``. By setting ``code``, you can look for the AST representation of ``code`` in the student's submission.
      But be aware that ``a`` and ``a = 1`` won't match, as reading and assigning are not the same in an AST.
      Use ``ast.dump(ast.parse(code))`` to see an AST representation of ``code``.
    * As an expression-based check when using more advanced SCT chain, e.g. to compare the equality of expressions to set function arguments.

    Args:
        incorrect_msg: message displayed when ASTs mismatch. When you specify ``code`` yourself, you have to specify this.
        code: optional code to use instead of the solution AST.
        exact: whether the representations must match exactly. If false, the solution AST
               only needs to be contained within the student AST (similar to using test student typed).
               Defaults to ``True``, unless the ``code`` argument has been specified.

    :Example:

        Student and Solution Code::

            dict(a = 'value').keys()

        SCT::

            # all pass
            Ex().has_equal_ast()
            Ex().has_equal_ast(code = "dict(a = 'value').keys()")
            Ex().has_equal_ast(code = "dict(a = 'value')", exact = False)

        Student and Solution Code::

            import numpy as np
            arr = np.array([1, 2, 3, 4, 5])
            np.mean(arr)

        SCT::

            # Check underlying value of arugment a of np.mean:
            Ex().check_function('numpy.mean').check_args('a').has_equal_ast()

            # Only check AST equality of expression used to specify argument a:
            Ex().check_function('numpy.mean').check_args('a').has_equal_ast()

    """
    if utils.v2_only():
        state.assert_is_not(["object_assignments"], "has_equal_ast", ["check_object"])
        state.assert_is_not(["function_calls"], "has_equal_ast", ["check_function"])

    if code and incorrect_msg is None:
        raise InstructorError.from_message(
            "Если вы вручную указываете код для сопоставления внутри has_equal_as(), "
            "вам необходимо явно задать аргумент `incorrect_msg`"
        )

    if (
        append is None
    ):  # if not specified, set to False if incorrect_msg was manually specified
        append = incorrect_msg is None
    if incorrect_msg is None:
        incorrect_msg = "Ожидалось `{{sol_str}}`, но было получено `{{stu_str}}`."

    def parse_tree(tree):
        # get contents of module.body if only 1 element
        crnt = (
            tree.body[0]
            if isinstance(tree, ast.Module) and len(tree.body) == 1
            else tree
        )

        # remove Expr if it exists
        return ast.dump(crnt.value if isinstance(crnt, ast.Expr) else crnt)

    stu_rep = parse_tree(state.student_ast)
    sol_rep = parse_tree(state.solution_ast if not code else ast.parse(code))

    fmt_kwargs = {
        "sol_str": state.solution_code if not code else code,
        "stu_str": state.student_code,
    }

    if exact and not code:
        state.do_test(
            EqualTest(
                stu_rep,
                sol_rep,
                FeedbackComponent(incorrect_msg, fmt_kwargs, append=append),
            )
        )
    elif sol_rep not in stu_rep:
        state.report(incorrect_msg, fmt_kwargs, append=append)

    return state


DEFAULT_INCORRECT_MSG = "Ожидалось {{test_desc}}`{{sol_eval}}`, но было получено `{{stu_eval}}`."
DEFAULT_ERROR_MSG = "Выполнение {{'кода' if parent['part'] else 'выделенного выражения'}} привело к ошибке: `{{stu_str}}`."
DEFAULT_ERROR_MSG_INV = "Выполнение {{'кода' if parent['part'] else 'выделенного выражения'}} не привело к ошибке:, но оно должно было!"
DEFAULT_UNDEFINED_NAME_MSG = "Выполнение {{'кода' if parent['part'] else 'выделенного выражения'}} должно определить переменную `{{name}}` без ошибок, но были получены ошибки."
DEFAULT_INCORRECT_NAME_MSG = (
    "Вы уверены, что присвоили правильное значение `{{name}}`?"
)
DEFAULT_INCORRECT_EXPR_CODE_MSG = (
    "Выполнение выражения `{{expr_code}}` не привело к ожидаемому результату."
)

args_string = """

    Args:
        incorrect_msg (str): feedback message if the {0} of the expression in the solution
          doesn't match the one of the student. This feedback message will be expanded if it is used
          in the context of another check function, like ``check_if_else``.
        error_msg (str): feedback message if there was an error when running the targeted student code.
          Note that when testing for an error, this message is displayed when none is raised.
        undefined_msg (str): feedback message if the ``name`` argument is defined, but a variable
          with that name doesn't exist after running the targeted student code.
        extra_env (dict): set variables to the extra environment. They will update the student and solution environment in
          the active state before the student/solution code in the active state is ran. This argument should contain a
          dictionary with the keys the names of the variables you want to set, and the values are the values of these variables.
          You can also use ``set_env()`` for this.
        context_vals (list): set variables which are bound in a ``for`` loop to certain values.
          This argument is only useful when checking a for loop (or list comprehensions).
          It contains a list with the values of the bound variables.
          You can also use ``set_context()`` for this.
        pre_code (str): the code in string form that should be executed before the expression is executed.
          This is the ideal place to set a random seed, for example.
        expr_code (str): If this argument is set, the expression in the student/solution code will not
          be ran. Instead, the given piece of code will be ran in the student as well as the solution environment
          and the result will be compared. However if the string contains one or more placeholders ``__focus__``,
          they will be substituted by the currently focused code.
        name (str): If this is specified, the {0} of running this expression after running the focused expression
          is returned, instead of the {0} of the focused expression in itself. This is typically used to inspect the
          {0} of an object after executing the body of e.g. a ``for`` loop.
        copy (bool): whether to try to deep copy objects in the environment, such as lists, that could
          accidentally be mutated. Disable to speed up SCTs. Disabling may lead to cryptic mutation issues.
        func (function): custom binary function of form f(stu_result, sol_result), for equality testing.
        override: If specified, this avoids the execution of the targeted code in the solution process. Instead, it
          will compare the {0} of the expression in the student process with the value specified in ``override``.
          Typically used in a ``SingleProcessExercise`` or if you want to allow for different solutions other than
          the one coded up in the solution.
    """


def has_expr(
    state,
    incorrect_msg=None,
    error_msg=None,
    undefined_msg=None,
    append=None,
    extra_env=None,
    context_vals=None,
    pre_code=None,
    expr_code=None,
    name=None,
    copy=True,
    func=None,
    override=None,
    test=None,  # todo: default or arg before state
):

    if (
        append is None
    ):  # if not specified, set to False if incorrect_msg was manually specified
        append = incorrect_msg is None
    if incorrect_msg is None:
        if name:
            incorrect_msg = DEFAULT_INCORRECT_NAME_MSG
        elif expr_code:
            incorrect_msg = DEFAULT_INCORRECT_EXPR_CODE_MSG
        else:
            incorrect_msg = DEFAULT_INCORRECT_MSG
    if undefined_msg is None:
        undefined_msg = DEFAULT_UNDEFINED_NAME_MSG
    if error_msg is None:
        if test == "error":
            error_msg = DEFAULT_ERROR_MSG_INV
        else:
            error_msg = DEFAULT_ERROR_MSG

    if state.solution_code is not None and isinstance(expr_code, str):
        expr_code = expr_code.replace("__focus__", state.solution_code)

    get_func = partial(
        evalCalls[test],
        extra_env=extra_env,
        context_vals=context_vals,
        pre_code=pre_code,
        expr_code=expr_code,
        name=name,
        copy=copy,
    )

    if override is not None:
        # don't bother with running expression and fetching output/value
        # eval_sol, str_sol = eval
        eval_sol, str_sol = override, str(override)
    else:
        eval_sol, str_sol = get_func(
            tree=state.solution_ast,
            process=state.solution_process,
            context=state.solution_context,
            env=state.solution_env,
        )

        if (test == "error") ^ isinstance(eval_sol, Exception):
            raise InstructorError.from_message(
                "Выполнение выражения solution-кода вызвало ошибку (или не вызвала, если тестирование проводилось для одного). "
                "Ошибка: {} - {}".format(type(eval_sol), str_sol)
            )
        if isinstance(eval_sol, ReprFail):
            raise InstructorError.from_message(
                "Не удалось извлечь значение для выделенного выражения из solution-кода:"
                + eval_sol.info
            )

    eval_stu, str_stu = get_func(
        tree=state.student_ast,
        process=state.student_process,
        context=state.student_context,
        env=state.student_env,
    )

    # kwargs ---
    fmt_kwargs = {
        "stu_part": state.student_parts,
        "sol_part": state.solution_parts,
        "name": name,
        "test": test,
        "test_desc": "" if test == "value" else "the %s " % test,
        "expr_code": expr_code,
    }

    fmt_kwargs["stu_eval"] = str(eval_stu)
    fmt_kwargs["sol_eval"] = str(eval_sol)

    # wrap in quotes if eval_sol or eval_stu are strings
    if test == "value":
        if isinstance(eval_stu, str):
            fmt_kwargs["stu_eval"] = '\'{}\''.format(fmt_kwargs["stu_eval"])
        if isinstance(eval_sol, str):
            fmt_kwargs["sol_eval"] = '\'{}\''.format(fmt_kwargs["sol_eval"])

    # reformat student evaluation string if it is too long
    fmt_kwargs["stu_eval"] = utils.shorten_string(fmt_kwargs["stu_eval"])

    # check if student or solution evaluations are too long or contain newlines
    if incorrect_msg == DEFAULT_INCORRECT_MSG and (
        len(fmt_kwargs["sol_eval"]) > 50 or
        utils.has_newline(fmt_kwargs["stu_eval"]) or
        utils.has_newline(fmt_kwargs["sol_eval"]) or
        fmt_kwargs["stu_eval"] == fmt_kwargs["sol_eval"]):
        fmt_kwargs["stu_eval"] = None
        fmt_kwargs["sol_eval"] = None
        incorrect_msg = "Ожидалось что-то другое."

    # tests ---
    # error in process
    if (test == "error") ^ isinstance(eval_stu, Exception):
        fmt_kwargs["stu_str"] = str_stu
        state.report(error_msg, fmt_kwargs, append=append)

    # name is undefined after running expression
    if isinstance(eval_stu, UndefinedValue):
        state.report(undefined_msg, fmt_kwargs, append=append)

    # test equality of results
    state.do_test(
        EqualTest(
            eval_stu,
            eval_sol,
            FeedbackComponent(incorrect_msg, fmt_kwargs, append=append),
            func,
        )
    )

    return state


has_equal_value = partial(has_expr, test="value")
has_equal_value.__name__ = "has_equal_value"
has_equal_value.__doc__ = (
    """Run targeted student and solution code, and compare returned value.

    When called on an SCT chain, ``has_equal_value()`` will execute the student and solution
    code that is 'zoomed in on' and compare the returned values.
    """
    + args_string.format("returned value", "value")
    + """
    :Example:

        Student code and solution code::

            import numpy as np
            arr = np.array([1, 2, 3, 4, 5])
            np.mean(arr)

        SCT::

            # Verify equality of arr:
            Ex().check_object('arr').has_equal_value()

            # Verify whether arr was correctly set in np.mean
            Ex().check_function('numpy.mean').check_args('a').has_equal_value()

            # Verify whether np.mean(arr) produced the same result
            Ex().check_function('numpy.mean').has_equal_value()

    """
)


has_equal_output = partial(has_expr, test="output")
has_equal_output.__name__ = "has_equal_output"
has_equal_output.__doc__ = """Run targeted student and solution code, and compare output.

    When called on an SCT chain, ``has_equal_output()`` will execute the student and solution
    code that is 'zoomed in on' and compare the output.
    """ + args_string.format(
    "output"
)

has_equal_error = partial(has_expr, test="error")
has_equal_error.__name__ = "has_equal_error"
has_equal_error.__doc__ = """Run targeted student and solution code, and compare generated errors.

    When called on an SCT chain, ``has_equal_error()`` will execute the student and solution
    code that is 'zoomed in on' and compare the errors that they generate.
    """ + args_string.format(
    "error"
)

## Various has tests ----------------------------------------------------------

from tcs_pythonwhat.Test import StringContainsTest


def has_code(state, text, pattern=True, not_typed_msg=None):
    """Test the student code.

    Tests if the student typed a (pattern of) text. It is advised to use ``has_equal_ast()`` instead of ``has_code()``,
    as it is more robust to small syntactical differences that don't change the code's behavior.

    Args:
        text (str): the text that is searched for
        pattern (bool): if True (the default), the text is treated as a pattern. If False, it is treated as plain text.
        not_typed_msg (str): feedback message to be displayed if the student did not type the text.

    :Example:

        Student code and solution code::

            y = 1 + 2 + 3

        SCT::

            # Verify that student code contains pattern (not robust!!):
            Ex().has_code(r"1\\s*\\+2\\s*\\+3")

    """
    if not not_typed_msg:
        if pattern:
            not_typed_msg = "Не удалось найти правильный шаблон в вашем коде."
        else:
            not_typed_msg = "Не удалось найти следующий текст в вашем коде: %r" % text

    student_code = state.student_code

    state.do_test(StringContainsTest(student_code, text, pattern, not_typed_msg))

    return state


def has_import(
    state,
    name,
    same_as=False,
    not_imported_msg="Вы импортировали `{{pkg}}`?",
    incorrect_as_msg="Вы импортировали `{{pkg}}` как `{{alias}}`?",
):
    """Checks whether student imported a package or function correctly.

    Python features many ways to import packages.
    All of these different methods revolve around the ``import``, ``from`` and ``as`` keywords.
    ``has_import()`` provides a robust way to check whether a student correctly imported a certain package.

    By default, ``has_import()`` allows for different ways of aliasing the imported package or function.
    If you want to make sure the correct alias was used to refer to the package or function that was imported,
    set ``same_as=True``.

    Args:
        name (str): the name of the package that has to be checked.
        same_as (bool): if True, the alias of the package or function has to be the same. Defaults to False.
        not_imported_msg (str): feedback message when the package is not imported.
        incorrect_as_msg (str): feedback message if the alias is wrong.

    :Example:

        Example 1, where aliases don't matter (defaut): ::

            # solution
            import matplotlib.pyplot as plt

            # sct
            Ex().has_import("matplotlib.pyplot")

            # passing submissions
            import matplotlib.pyplot as plt
            from matplotlib import pyplot as plt
            import matplotlib.pyplot as pltttt

            # failing submissions
            import matplotlib as mpl

        Example 2, where the SCT is coded so aliases do matter: ::

            # solution
            import matplotlib.pyplot as plt

            # sct
            Ex().has_import("matplotlib.pyplot", same_as=True)

            # passing submissions
            import matplotlib.pyplot as plt
            from matplotlib import pyplot as plt

            # failing submissions
            import matplotlib.pyplot as pltttt

    """
    student_imports = state.ast_dispatcher.find("imports", state.student_ast)
    solution_imports = state.ast_dispatcher.find("imports", state.solution_ast)

    if name not in solution_imports:
        raise InstructorError.from_message(
            "`has_import()` не смог найти импортирование библиотеки %s в solution-коде."
            % name
        )

    fmt_kwargs = {"pkg": name, "alias": solution_imports[name]}

    state.do_test(
        DefinedCollTest(
            name, student_imports, FeedbackComponent(not_imported_msg, fmt_kwargs)
        )
    )

    if same_as:
        state.do_test(
            EqualTest(
                solution_imports[name],
                student_imports[name],
                FeedbackComponent(incorrect_as_msg, fmt_kwargs),
            )
        )

    return state


def has_output(state, text, pattern=True, no_output_msg=None):
    """Search student output for a pattern.

    Among the student and solution process, the student submission and solution code as a string,
    the ``Ex()`` state also contains the output that a student generated with his or her submission.

    With ``has_output()``, you can access this output and match it against a regular or fixed expression.

    Args:
        text (str): the text that is searched for
        pattern (bool): if True (default), the text is treated as a pattern. If False, it is treated as plain text.
        no_output_msg (str): feedback message to be displayed if the output is not found.

    :Example:

        As an example, suppose we want a student to print out a sentence: ::

            # Print the "This is some ... stuff"
            print("This is some weird stuff")

        The following SCT tests whether the student prints out ``This is some weird stuff``: ::

            # Using exact string matching
            Ex().has_output("This is some weird stuff", pattern = False)

            # Using a regular expression (more robust)
            # pattern = True is the default
            msg = "Print out ``This is some ... stuff`` to the output, " + \\
                  "fill in ``...`` with a word you like."
            Ex().has_output(r"This is some \w* stuff", no_output_msg = msg)

    """
    if not no_output_msg:
        no_output_msg = "Вы не вывели ожидаемый результат."

    state.do_test(
        StringContainsTest(state.raw_student_output, text, pattern, no_output_msg)
    )

    return state


def has_printout(
    state, index, not_printed_msg=None, pre_code=None, name=None, copy=False
):
    """Check if the right printouts happened.

    ``has_printout()`` will look for the printout in the solution code that you specified with ``index`` (0 in this case), rerun the ``print()`` call in
    the solution process, capture its output, and verify whether the output is present in the output of the student.

    This is more robust as ``Ex().check_function('print')`` initiated chains as students can use as many
    printouts as they want, as long as they do the correct one somewhere.

    Args:
        index (int): index of the ``print()`` call in the solution whose output you want to search for in the student output.
        not_printed_msg (str): if specified, this overrides the default message that is generated when the output
          is not found in the student output.
        pre_code (str): Python code as a string that is executed before running the targeted student call.
          This is the ideal place to set a random seed, for example.
        copy (bool): whether to try to deep copy objects in the environment, such as lists, that could
          accidentally be mutated. Disabled by default, which speeds up SCTs.
        state (State): state as passed by the SCT chain. Don't specify this explicitly.

    :Example:

        Suppose you want somebody to print out 4: ::

            print(1, 2, 3, 4)

        The following SCT would check that: ::

            Ex().has_printout(0)

        All of the following SCTs would pass: ::

            print(1, 2, 3, 4)
            print('1 2 3 4')
            print(1, 2, '3 4')
            print("random"); print(1, 2, 3, 4)

    :Example:

        Watch out: ``has_printout()`` will effectively **rerun** the ``print()`` call in the solution process after the entire solution script was executed.
        If your solution script updates the value of `x` after executing it, ``has_printout()`` will not work.

        Suppose you have the following solution: ::

            x = 4
            print(x)
            x = 6

        The following SCT will not work: ::

            Ex().has_printout(0)

        Why? When the ``print(x)`` call is executed, the value of ``x`` will be 6, and pythonwhat will look for the output `'6`' in the output the student generated.
        In cases like these, ``has_printout()`` cannot be used.

    :Example:

        Inside a for loop ``has_printout()``

        Suppose you have the following solution: ::

            for i in range(5):
                print(i)

        The following SCT will not work: ::

            Ex().check_for_loop().check_body().has_printout(0)

        The reason is that ``has_printout()`` can only be called from the root state. ``Ex()``.
        If you want to check printouts done in e.g. a for loop, you have to use a `check_function('print')` chain instead: ::

            Ex().check_for_loop().check_body().\\
                set_context(0).check_function('print').\\
                check_args(0).has_equal_value()

    """

    extra_msg = "Если вы хотетите проверить вывод данных внутри цикла, то вы должны использовать выражение`check_function('print')`."
    state.assert_execution_root("has_printout", extra_msg=extra_msg)

    if not_printed_msg is None:
        not_printed_msg = (
            "Вы использовали `{{sol_call}}` чтобы сделать вывод соответствующего результата?"
        )

    try:
        sol_call_ast = state.ast_dispatcher.find("function_calls", state.solution_ast)[
            "print"
        ][index]["node"]
    except (KeyError, IndexError):
        raise InstructorError.from_message(
            "`has_printout({})` не смог найти вызов {} для вывода соответствующего результата в solution-коде.".format(
                index, get_ord(index + 1)
            )
        )

    out_sol, str_sol = getOutputInProcess(
        tree=sol_call_ast,
        process=state.solution_process,
        context=state.solution_context,
        env=state.solution_env,
        pre_code=pre_code,
        copy=copy,
    )

    sol_call_str = state.solution_ast_tokens.get_text(sol_call_ast)

    if isinstance(str_sol, Exception):
        with debugger(state):
            state.report(
                "Evaluating the solution expression {} raised error in solution process."
                "Error: {} - {}".format(sol_call_str, type(out_sol), str_sol)
            )

    has_output(
        state,
        out_sol.strip(),
        pattern=False,
        no_output_msg=FeedbackComponent(not_printed_msg, {"sol_call": sol_call_str}),
    )

    return state


def has_no_error(
    state,
    incorrect_msg="Взгляните на консоль: ваш код содержит ошибку. Исправьте это и попробуйте еще раз!",
):
    """Check whether the submission did not generate a runtime error.

    If all SCTs for an exercise pass, before marking the submission as correct pythonwhat will automatically check whether
    the student submission generated an error. This means it is not needed to use ``has_no_error()`` explicitly.

    However, in some cases, using ``has_no_error()`` explicitly somewhere throughout your SCT execution can be helpful:

    - If you want to make sure people didn't write typos when writing a long function name.
    - If you want to first verify whether a function actually runs, before checking whether the arguments were specified correctly.
    - More generally, if, because of the content, it's instrumental that the script runs without
      errors before doing any other verifications.

    Args:
        incorrect_msg: if specified, this overrides the default message if the student code generated an error.

    :Example:

        Suppose you're verifying an exercise about model training and validation: ::

            # pre exercise code
            import numpy as np
            from sklearn.model_selection import train_test_split
            from sklearn import datasets
            from sklearn import svm

            iris = datasets.load_iris()
            iris.data.shape, iris.target.shape

            # solution
            X_train, X_test, y_train, y_test = train_test_split(
                iris.data, iris.target, test_size=0.4, random_state=0)

        If you want to make sure that ``train_test_split()`` ran without errors,
        which would check if the student typed the function without typos and used
        sensical arguments, you could use the following SCT: ::

            Ex().has_no_error()
            Ex().check_function('sklearn.model_selection.train_test_split').multi(
                check_args(['arrays', 0]).has_equal_value(),
                check_args(['arrays', 0]).has_equal_value(),
                check_args(['options', 'test_size']).has_equal_value(),
                check_args(['options', 'random_state']).has_equal_value()
            )

        If, on the other hand, you want to fall back onto pythonwhat's built in behavior,
        that checks for an error before marking the exercise as correct, you can simply
        leave of the ``has_no_error()`` step.

    """
    state.assert_execution_root("has_no_error")

    if state.reporter.errors:
        state.report(incorrect_msg, {"error": str(state.reporter.errors[0])})

    return state


MC_VAR_NAME = "selected_option"


def has_chosen(state, correct, msgs):
    """Test multiple choice exercise.

    Test for a MultipleChoiceExercise. The correct answer (as an integer) and feedback messages
    are passed to this function.

    Args:
        correct (int): the index of the correct answer (should be an instruction). Starts at 1.
        msgs (list(str)): a list containing all feedback messages belonging to each choice of the
                          student. The list should have the same length as the number of options.
    """
    if not issubclass(type(correct), int):
        raise InstructorError.from_message(
            "Внутри `has_chosen()` аргумент 'correct' должен быть целым числом."
        )

    student_process = state.student_process
    if not isDefinedInProcess(MC_VAR_NAME, student_process):
        raise InstructorError.from_message(
            "Опция не доступна в student-коде"
        )
    else:
        selected_option = getOptionFromProcess(student_process, MC_VAR_NAME)
        if not issubclass(type(selected_option), int):
            raise InstructorError.from_message("selected_option должен быть целым числом")

        if selected_option < 1 or correct < 1:
            raise InstructorError.from_message(
                "selected_option and correct должны быть больше нуля"
            )

        if selected_option > len(msgs) or correct > len(msgs):
            raise InstructorError.from_message(
                "определено недостаточно сообщений обратной связи."
            )

        feedback_msg = msgs[selected_option - 1]

        state.reporter.success_msg = msgs[correct - 1]

        state.do_test(EqualTest(selected_option, correct, feedback_msg))
