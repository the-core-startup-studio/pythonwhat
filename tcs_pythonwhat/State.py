import asttokens

from functools import partialmethod
from collections.abc import Mapping

from tcs_protowhat.failure import debugger
from tcs_protowhat.Feedback import FeedbackComponent
from tcs_protowhat.selectors import DispatcherInterface
from tcs_protowhat.State import State as ProtoState
from tcs_protowhat.utils import parameters_attr
from tcs_pythonwhat import signatures
from tcs_pythonwhat.converters import get_manual_converters
from tcs_pythonwhat.feedback import Feedback
from tcs_pythonwhat.parsing import (
    TargetVars,
    FunctionParser,
    ObjectAccessParser,
    parser_dict,
)
from tcs_pythonwhat.utils_ast import wrap_in_module


class Context(Mapping):
    def __init__(self, context=None, prev=None):
        self.context = context if context else TargetVars()
        self.prev = prev if prev else {}

        self._items = {**self.prev, **self.context.defined_items()}

    def update_ctx(self, new_ctx):
        return self.__class__(new_ctx, self._items)

    def __getitem__(self, x):
        return self._items[x]

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)


@parameters_attr
class State(ProtoState):
    """State of the SCT environment.

    This class holds all information relevevant to test the correctness of an exercise.
    It is coded suboptimally and it will be refactored soon, and documented thouroughly
    after that.

    kwargs:
    ...
     - reporter

    """

    feedback_cls = Feedback

    def __init__(
        self,
        student_code,
        solution_code,
        pre_exercise_code,
        student_process,
        solution_process,
        raw_student_output,
        # solution output
        reporter,
        force_diagnose=False,
        highlight=None,
        highlight_offset=None,
        highlighting_disabled=None,
        feedback_context=None,
        creator=None,
        student_ast=None,
        solution_ast=None,
        student_ast_tokens=None,
        solution_ast_tokens=None,
        student_parts=None,
        solution_parts=None,
        student_context=Context(),
        solution_context=Context(),
        student_env=Context(),
        solution_env=Context(),
    ):
        args = locals().copy()
        self.debug = False

        for k, v in args.items():
            if k != "self":
                setattr(self, k, v)

        self.ast_dispatcher = self.get_dispatcher()

        # Parse solution and student code
        # if possible, not done yet and wanted (ast arguments not False)
        if isinstance(self.student_code, str) and student_ast is None:
            self.student_ast = self.parse(student_code)
        if isinstance(self.solution_code, str) and solution_ast is None:
            with debugger(self):
                self.solution_ast = self.parse(solution_code)

        if highlight is None:  # todo: check parent_state? (move check to reporting?)
            self.highlight = self.student_ast

        self.converters = get_manual_converters()  # accessed only from root state

        self.manual_sigs = None

    def get_manual_sigs(self):
        if self.manual_sigs is None:
            self.manual_sigs = signatures.get_manual_sigs()

        return self.manual_sigs

    def to_child(self, append_message=None, node_name="", **kwargs):
        """Dive into nested tree.

        Set the current state as a state with a subtree of this syntax tree as
        student tree and solution tree. This is necessary when testing if statements or
        for loops for example.
        """
        bad_parameters = set(kwargs) - set(self.parameters)
        if bad_parameters:
            raise ValueError(
                "Недопустимые параметры инициализации для State: %s" % ", ".join(bad_parameters)
            )

        base_kwargs = {
            attr: getattr(self, attr)
            for attr in self.parameters
            if hasattr(self, attr) and attr not in ["ast_dispatcher", "highlight"]
        }

        if append_message and not isinstance(append_message, FeedbackComponent):
            append_message = FeedbackComponent(append_message)
        kwargs["feedback_context"] = append_message
        kwargs["creator"] = {"type": "to_child", "args": {"state": self}}

        def update_kwarg(name, func):
            kwargs[name] = func(kwargs[name])

        def update_context(name):
            update_kwarg(name, getattr(self, name).update_ctx)

        for ast_arg in ["student_ast", "solution_ast"]:
            if isinstance(kwargs.get(ast_arg), list):
                update_kwarg(ast_arg, wrap_in_module)

        if kwargs.get("student_ast") and kwargs.get("student_code") is None:
            kwargs["student_code"] = self.student_ast_tokens.get_text(
                kwargs["student_ast"]
            )
        if kwargs.get("solution_ast") and kwargs.get("solution_code") is None:
            kwargs["solution_code"] = self.solution_ast_tokens.get_text(
                kwargs["solution_ast"]
            )

        for context in [
            "student_context",
            "solution_context",
            "student_env",
            "solution_env",
        ]:
            if context in kwargs:
                if kwargs[context] is not None:
                    update_context(context)
                else:
                    kwargs.pop(context)

        klass = self.SUBCLASSES[node_name] if node_name else State
        init_kwargs = {**base_kwargs, **kwargs}
        child = klass(**init_kwargs)

        extra_attrs = set(vars(self)) - set(self.parameters)
        for attr in extra_attrs:
            # don't copy attrs set on new instances in init
            # the cached manual_sigs is passed
            if attr not in {"ast_dispatcher", "converters"}:
                setattr(child, attr, getattr(self, attr))

        return child

    def has_different_processes(self):
        # process classes have an _identity field that is a tuple
        try:
            return (
                self.student_process._identity[0] != self.solution_process._identity[0]
            )
        except:
            # play it safe (most common)
            return True

    def assert_execution_root(self, fun, extra_msg=""):
        if not (self.is_root or self.is_creator_type("run")):
            with debugger(self):
                self.report(
                    "`%s()` следует вызывать только для полной цепочки, следующей за `Ex()` или `run()`. %s"
                    % (fun, extra_msg)
                )

    def is_creator_type(self, type):
        return self.creator and self.creator.get("type") == type

    def assert_is(self, klasses, fun, prev_fun):
        if self.__class__.__name__ not in klasses:
            with debugger(self):
                self.report(
                    "`%s()` может быть вызван только для  %s."
                    % (fun, " or ".join(["`%s()`" % pf for pf in prev_fun]))
                )

    def assert_is_not(self, klasses, fun, prev_fun):
        if self.__class__.__name__ in klasses:
            with debugger(self):
                self.report(
                    "`%s()` может быть вызван только для %s."
                    % (fun, " or ".join(["`%s()`" % pf for pf in prev_fun]))
                )

    def parse_external(self, code):
        res = (None, None)
        try:
            return self.ast_dispatcher.parse(code)
        except IndentationError as e:
            e.filename = "script.py"
            # no line info for now
            self.report(
                "Ваш код не может быть распаршен из-за ошибки в отступе:<br>`%s.`"
                % str(e)
            )

        except SyntaxError as e:
            e.filename = "script.py"
            # no line info for now
            self.report(
                "Ваш код не может быть выполнен из-за синтаксической ошибки:<br>`%s.`" % str(e)
            )

        # Can happen, can't catch this earlier because we can't differentiate between
        # TypeError in parsing or TypeError within code (at runtime).
        except:
            self.report("Что-то пошло не так при парсинге вашего кода.")

        return res

    def parse_internal(self, code):
        try:
            return self.ast_dispatcher.parse(code)
        except Exception as e:
            self.report(
                "Что-то пошло не так при парсинге solution-кода: %s" % str(e)
            )

    def parse(self, text):
        if self.debug:
            parse_method = self.parse_internal
            token_attr = "solution_ast_tokens"
        else:
            parse_method = self.parse_external
            token_attr = "student_ast_tokens"

        tokens, ast = parse_method(text)
        setattr(self, token_attr, tokens)

        return ast

    def get_dispatcher(self):
        try:
            return Dispatcher(self.pre_exercise_code)
        except Exception as e:
            with debugger(self):
                self.report("Что-то пошло не так при парсинге PEC: %s" % str(e))


class Dispatcher(DispatcherInterface):
    _context_cache = dict()

    def __init__(self, context_code=""):
        self._parser_cache = dict()
        context_ast = getattr(self._context_cache, context_code, None)
        if context_ast is None:
            context_ast = self._context_cache[context_code] = self.parse(context_code)[
                1
            ]
        self.context_mappings = self._getx(FunctionParser, "mappings", context_ast)

    def find(self, name, node, *args, **kwargs):
        return getattr(self, name)(node)

    def parse(self, code):
        res = asttokens.ASTTokens(code, parse=True)
        return res, res.tree

    # add methods for retrieving parser outputs --------------------------
    def _getx(self, Parser, ext_attr, tree):
        """getter for Parser outputs"""
        # return cached output if possible
        cache_key = Parser.__name__ + str(hash(tree))
        if self._parser_cache.get(cache_key):
            p = self._parser_cache[cache_key]
        else:
            # otherwise, run parser over tree
            p = Parser()
            # set mappings for parsers that inspect attribute access
            if ext_attr != "mappings" and Parser in [
                FunctionParser,
                ObjectAccessParser,
            ]:
                p.mappings = self.context_mappings.copy()
            # run parser
            p.visit(tree)
            # cache
            self._parser_cache[cache_key] = p
        return getattr(p, ext_attr)


# put a function on the dispatcher
for k, Parser in parser_dict.items():
    setattr(Dispatcher, k, partialmethod(Dispatcher._getx, Parser, "out"))

# mappings from ObjectAccessParser
prop_oa_map = partialmethod(Dispatcher._getx, ObjectAccessParser, "mappings")
setattr(Dispatcher, "oa_mappings", prop_oa_map)

# mappings from FunctionParser
prop_map = partialmethod(Dispatcher._getx, FunctionParser, "mappings")
setattr(Dispatcher, "mappings", prop_map)


# State subclasses based on parsed output -------------------------------------
State.SUBCLASSES = {
    node_name: type(node_name, (State,), {}) for node_name in parser_dict
}


# global setters on State -----------------------------------------------------
def set_converter(key, fundef):
    # note that root state is set on the State class in test_exercise
    State.root_state.converters[key] = fundef
