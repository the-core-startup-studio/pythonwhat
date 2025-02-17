from tcs_protowhat.Feedback import FeedbackComponent
from tcs_pythonwhat.checks.check_funcs import part_to_child
from tcs_pythonwhat.tasks import getSignatureInProcess
from tcs_protowhat.utils_messaging import get_ord, get_times
from tcs_protowhat.failure import debugger
from tcs_pythonwhat.parsing import IndexedDict
from functools import partial


def bind_args(signature, args_part):
    pos_args = []
    kw_args = {}
    for k, arg in args_part.items():
        if isinstance(k, int):
            pos_args.append(arg)
        else:
            kw_args[k] = arg

    bound_args = signature.bind(*pos_args, **kw_args)
    return IndexedDict(bound_args.arguments)


def get_mapped_name(name, mappings):
    # get name by splitting on periods
    if "." in name:
        for orig, full_name in mappings.items():
            if name.startswith(full_name):
                return name.replace(full_name, orig)
    return name


MISSING_MSG = "Вы вызвали функцию `{{mapped_name}}()`{{' ' + times if index>0}}?"
SIG_ISSUE_MSG = (
    "Вы указали аргументы для функции `{{mapped_name}}()`, используя корректный синтаксис?"
)
PREPEND_MSG = "Проверьте {{ord + ' ' if index>0}} вызов `{{mapped_name}}()`. "


def check_function(
    state,
    name,
    index=0,
    missing_msg=None,
    params_not_matched_msg=None,
    expand_msg=None,
    signature=True,
):
    """Check whether a particular function is called.

    ``check_function()`` is typically followed by:

    - ``check_args()`` to check whether the arguments were specified.
      In turn, ``check_args()`` can be followed by ``has_equal_value()`` or ``has_equal_ast()``
      to assert that the arguments were correctly specified.
    - ``has_equal_value()`` to check whether rerunning the function call coded by the student
      gives the same result as calling the function call as in the solution.

    Checking function calls is a tricky topic. Please visit the
    `dedicated article <articles/checking_function_calls.html>`_ for more explanation,
    edge cases and best practices.

    Args:
        name (str): the name of the function to be tested. When checking functions in packages, always
            use the 'full path' of the function.
        index (int): index of the function call to be checked. Defaults to 0.
        missing_msg (str): If specified, this overrides an automatically generated feedback message in case
            the student did not call the function correctly.
        params_not_matched_msg (str): If specified, this overrides an automatically generated feedback message
            in case the function parameters were not successfully matched.
        expand_msg (str): If specified, this overrides any messages that are prepended by previous SCT chains.
        signature (Signature): Normally, check_function() can figure out what the function signature is,
            but it might be necessary to use ``sig_from_params()`` to manually build a signature and pass this along.
        state (State): State object that is passed from the SCT Chain (don't specify this).

    :Examples:

        Student code and solution code::

            import numpy as np
            arr = np.array([1, 2, 3, 4, 5])
            np.mean(arr)

        SCT::

            # Verify whether arr was correctly set in np.mean
            Ex().check_function('numpy.mean').check_args('a').has_equal_value()

            # Verify whether np.mean(arr) produced the same result
            Ex().check_function('numpy.mean').has_equal_value()
    """

    append_missing = missing_msg is None
    append_params_not_matched = params_not_matched_msg is None
    if missing_msg is None:
        missing_msg = MISSING_MSG
    if expand_msg is None:
        expand_msg = PREPEND_MSG
    if params_not_matched_msg is None:
        params_not_matched_msg = SIG_ISSUE_MSG

    stu_out = state.ast_dispatcher.find("function_calls", state.student_ast)
    sol_out = state.ast_dispatcher.find("function_calls", state.solution_ast)

    student_mappings = state.ast_dispatcher.find("mappings", state.student_ast)

    fmt_kwargs = {
        "times": get_times(index + 1),
        "ord": get_ord(index + 1),
        "index": index,
        "mapped_name": get_mapped_name(name, student_mappings),
    }

    # Get Parts ----
    # Copy, otherwise signature binding overwrites sol_out[name][index]['args']
    with debugger(state):
        try:
            sol_parts = {**sol_out[name][index]}
        except KeyError:
            state.report(
                "`check_function()` не удается найти вызов `%s()` в solution-коде. Убедитесь, что вы правильно составили ожидания для кода!"
                % name
            )
        except IndexError:
            state.report(
                "`check_function()` не удается найти %s вызовы `%s()` в solution-коде."
                % (index + 1, name)
            )

    try:
        # Copy, otherwise signature binding overwrites stu_out[name][index]['args']
        stu_parts = {**stu_out[name][index]}
    except (KeyError, IndexError):
        state.report(missing_msg, fmt_kwargs, append=append_missing)

    # Signatures -----
    if signature:
        signature = None if isinstance(signature, bool) else signature
        get_sig = partial(
            getSignatureInProcess,
            name=name,
            signature=signature,
            manual_sigs=state.get_manual_sigs(),
        )

        try:
            sol_sig = get_sig(
                mapped_name=sol_parts["name"], process=state.solution_process
            )
            sol_parts["args"] = bind_args(sol_sig, sol_parts["args"])
        except Exception as e:
            with debugger(state):
                state.report(
                    "`check_function()` не удается сопоставить %s вызовы `%s` их сигнатурам:\n%s "
                    % (get_ord(index + 1), name, e)
                )

        try:
            stu_sig = get_sig(
                mapped_name=stu_parts["name"], process=state.student_process
            )
            stu_parts["args"] = bind_args(stu_sig, stu_parts["args"])
        except Exception:
            state.to_child(highlight=stu_parts["node"]).report(
                params_not_matched_msg, fmt_kwargs, append=append_params_not_matched
            )

    # three types of parts: pos_args, keywords, args (e.g. these are bound to sig)
    append_message = FeedbackComponent(expand_msg, fmt_kwargs)
    child = part_to_child(
        stu_parts, sol_parts, append_message, state, node_name="function_calls"
    )
    return child
