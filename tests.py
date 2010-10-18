import unittest
import tokenize

from StringIO import StringIO

from badlog import parse_args
from badlog import get_next_token
from badlog import examine_filelike
from badlog import BaseState
from badlog import InitialState
from badlog import PossibleLoggerStatementState
from badlog import LoggerFormatStringState
from badlog import CountingArgsState

TEST_FILENAME = "test.py"


class AbstractStateTest(unittest.TestCase):

    def setUp(self):
        self.writer = StringIO()
        self._output = None
        self.options, _args = parse_args()

    def init_test_state(self, state_class, *args, **kwargs):
        return state_class(TEST_FILENAME,
                           self.writer,
                           self.options,
                           *args,
                           **kwargs)

    @property
    def output(self):
        if not self._output:
            self._output = self.writer.getvalue()
        return self._output

    def assert_state(self, expected_state, transition):
        self.assertEquals(expected_state.NAME, transition.new_state_name)


class BaseStateTests(AbstractStateTest):

    def test_rewind(self):
        state = self.init_test_state(BaseState)

        expected_tokens = ["a", "b", "c", "d"]
        tokens = expected_tokens[:]

        state.consume_next_token(tokens)
        state.rewind(tokens)

        self.assertEquals(expected_tokens, tokens)

    def test_rewind_all(self):
        state = self.init_test_state(BaseState)

        expected_tokens = ["a", "b", "c", "d"]
        tokens = expected_tokens[:]

        state.consume_next_token(tokens)
        state.consume_next_token(tokens)
        state.consume_next_token(tokens)
        state.rewind_all(tokens)

        self.assertEquals(expected_tokens, tokens)


class InitialStateTests(AbstractStateTest):

    def test_state_transition_on_valid_logger(self):
        src = "logger.debug('hi there')"
        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        state = self.init_test_state(InitialState)
        transition = state.process(tokens)
        self.assert_state(PossibleLoggerStatementState, transition)
        self.assertEquals(".", transition.tokens[0][1])

    def test_state_transition_on_not_valid_logger(self):
        src = "foo('hi there')"
        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        state = self.init_test_state(InitialState)
        transition = state.process(tokens)
        self.assert_state(InitialState, transition)
        self.assertEquals("(", transition.tokens[0][1])


class PossibleLoggerStatementStateTests(AbstractStateTest):

    def test_state_transition_on_valid_logger(self):
        src = "logger.debug('hi there')"
        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        get_next_token(tokens)  # Eat the 'logger' token
        state = self.init_test_state(PossibleLoggerStatementState)
        transition = state.process(tokens)
        self.assert_state(LoggerFormatStringState, transition)
        self.assertEquals("'hi there'", transition.tokens[0][1])

    def test_state_transition_on_not_valid_logger(self):
        src = "logger('hi there')"
        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        get_next_token(tokens)  # Eat the 'logger' token
        state = self.init_test_state(PossibleLoggerStatementState)
        transition = state.process(tokens)
        self.assert_state(InitialState, transition)
        self.assertEquals("(", transition.tokens[0][1])

    def test_is_dot(self):
        src = "logger.debug('hi there')"
        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        get_next_token(tokens)  # Eat the 'logger' token
        state = self.init_test_state(PossibleLoggerStatementState)
        state.consume_next_token(tokens)
        self.assertEquals(True, state.is_dot())

    def test_is_open_paren(self):
        src = "logger.debug('hi there')"
        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        get_next_token(tokens)  # Eat the 'logger' token
        get_next_token(tokens)  # Eat the '.' token
        get_next_token(tokens)  # Eat the 'debug' token
        state = self.init_test_state(PossibleLoggerStatementState)
        state.consume_next_token(tokens)
        self.assertEquals(True, state.is_open_paren())

    def test_is_format_string(self):
        src = "logger.debug('hi there')"
        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        get_next_token(tokens)  # Eat the 'logger' token
        get_next_token(tokens)  # Eat the '.' token
        get_next_token(tokens)  # Eat the 'debug' token
        get_next_token(tokens)  # Eat the '(' token
        state = self.init_test_state(PossibleLoggerStatementState)
        state.consume_next_token(tokens)
        self.assertEquals(True, state.is_format_string())

    def test_back_to_initial(self):
        src = "logger.debug('hi there')"
        sio = StringIO(src)
        expected_tokens = list(tokenize.generate_tokens(sio.readline))
        tokens = expected_tokens[:]
        state = self.init_test_state(PossibleLoggerStatementState)
        state.consume_next_token(tokens)  # Eat the 'logger' token
        state.consume_next_token(tokens)  # Eat the '.' token
        state.consume_next_token(tokens)  # Eat the 'debug' token
        state.consume_next_token(tokens)  # Eat the '(' token
        transition = state.back_to_initial(tokens)
        self.assert_state(InitialState, transition)
        self.assertEquals(expected_tokens, tokens)


class LoggerFormatStringStateTests(AbstractStateTest):

    def make_state(self, src):
        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        state = self.init_test_state(LoggerFormatStringState)
        state.consume_next_token(tokens)  # Eat the 'logger' token
        state.consume_next_token(tokens)  # Eat the '.' token
        state.consume_next_token(tokens)  # Eat the 'debug' to ken
        state.consume_next_token(tokens)  # Eat the '(' token
        state.consume_next_token(tokens)  # Eat the fmt string
        return state

    def test_count_format_specifiers_none(self):
        state = self.make_state("logger.debug('foo')")
        self.assertEquals(0, state.count_format_specifiers())

    def test_count_format_specifiers_one(self):
        state = self.make_state("logger.debug('foo: %s')")
        self.assertEquals(1, state.count_format_specifiers())

    def test_count_format_specifiers_two(self):
        state = self.make_state("logger.debug('foo: %s %d')")
        self.assertEquals(2, state.count_format_specifiers())

    def test_count_format_specifiers_with_escaped_percent(self):
        state = self.make_state("logger.debug('foo: %s 50%% %d')")
        self.assertEquals(2, state.count_format_specifiers())


class MiscTests(AbstractStateTest):

    def test_multiple_lines(self):
        src = """
                  logger.debug('hi %s',
                               'there')
               """
        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        state = self.init_test_state(InitialState)
        transition = state.process(tokens)
        self.assert_state(PossibleLoggerStatementState, transition)
        self.assertEquals(transition.tokens[0][1], ".")
        state = self.init_test_state(PossibleLoggerStatementState)
        transition = state.process(tokens)
        self.assert_state(LoggerFormatStringState, transition)
        self.assertEquals(transition.tokens[0][1], "'hi %s'")
        state = self.init_test_state(LoggerFormatStringState)
        transition = state.process(tokens)
        self.assert_state(CountingArgsState, transition)
        state = self.init_test_state(CountingArgsState, 0, 0)
        transition = state.process(tokens)
        self.assert_state(InitialState, transition)

    def test_ignore_newlines(self):
        src = """
                  logger.debug("hi there")
              """

        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        state = self.init_test_state(InitialState)
        transition = state.process(tokens)
        self.assert_state(PossibleLoggerStatementState, transition)


class IntegrationTests(AbstractStateTest):

    def examine_str(self, s):
        sio = StringIO(s)
        examine_filelike("__TESTS__", sio, self.options, writer=self.writer)

    def test_no_fmt_no_args(self):
        src = """logger.debug('foo')"""
        self.examine_str(src)
        self.assertEquals("", self.output)

    def test_one_fmt_one_arg(self):
        src = """logger.debug('foo: %s', 1)"""
        self.examine_str(src)
        self.assertEquals("", self.output)

    def test_one_fmt_zero_args(self):
        src = """logger.debug('foo: %s')"""
        self.examine_str(src)
        self.assertEquals("ERROR: Logger statement has 1 format"
                          " specifiers but"
                          " 0 argument(s).\nAt line 1 of '__TESTS__':"
                          "\n    logger.debug('foo: %s')\n\n", self.output)

    def test_one_fmt_two_args(self):
        src = """logger.debug('foo: %s', 1, 2)"""
        self.examine_str(src)
        self.assertEquals("ERROR: Logger statement has 1 format"
                          " specifiers but 2"
                          " argument(s).\nAt line 1 of '__TESTS__':\n "
                          "   logger.debug('foo: %s', 1, 2)\n\n",
                          self.output)

    def test_two_fmt_one_args(self):
        src = """logger.debug('foo: %s %s', 1)"""
        self.examine_str(src)
        self.assertEquals("ERROR: Logger statement has 2 format"
                          " specifiers but 1 "
                          "argument(s).\nAt line 1 of '__TESTS__':\n    l"
                          "ogger.debug('foo: %s %s', 1)\n\n", self.output)

    def test_no_fmt_one_args(self):
        src = """logger.debug('foo.', 1)"""
        self.examine_str(src)
        self.assertEquals("ERROR: Logger statement has 0 format"
                          " specifiers but 1"
                          " argument(s).\nAt line 1 of '__TESTS__':\n    "
                          "logger.debug('foo.', 1)\n\n", self.output)

    def test_multiline_no_fmt_no_args(self):
        src = """
                 logger.debug('foo'),
              """
        self.examine_str(src)
        self.assertEquals("", self.output)

    def test_multiline_one_fmt_one_arg(self):
        src = """
                 logger.debug('foo: %s',
                              1)
              """
        self.examine_str(src)
        self.assertEquals("", self.output)

    def test_multiline_one_fmt_two_args(self):
        src = """
                 logger.debug('foo: %s',
                              1, 2)
              """
        self.examine_str(src)
        self.assertEquals("ERROR: Logger statement has 1 format"
                          " specifiers but 2"
                          " argument(s).\nAt line 3 of '__TESTS__':\n "
                          "                                 1, 2)\n\n",
                          self.output)

    def test_multiline_two_fmt_one_args(self):
        src = """
                 logger.debug('foo: %s %s.',
                              1)
              """
        self.examine_str(src)
        self.assertEquals("ERROR: Logger statement has 2 format"
                          " specifiers but 1 "
                          "argument(s).\nAt line 3 of '__TESTS__':\n   "
                          "                               1)\n\n", self.output)

    def test_multiple_concatenated_strings_as_fmt_string(self):
        src = """
                logger.debug("a "
                             "b")
        """
        self.examine_str(src)
        self.assertEquals("", self.output)

    def test_explicit_continuation_character_in_fmt_string(self):
        src = """
                logger.debug("a " \
                             "b")
        """
        self.examine_str(src)
        self.assertEquals("", self.output)

    def test_proper_paren_matching(self):
        src = """
            logger.debug("Attempting to merge model lists A(%d models) "
                         "and B(%d models)", len(a), len(b))
        """
        self.examine_str(src)
        self.assertEquals("", self.output)

    def test_nested_commas(self):
        src = """
                logger.info("blah: [%s]",
                            ",".join(map(str, stuff)))
        """
        self.examine_str(src)
        self.assertEquals("", self.output)

    def test_percent_after_fmt(self):
        src = "logger.debug('foo: %s' % s)"
        self.examine_str(src)
        self.assertEquals("ERROR: Logger statement uses % operator"
                          " for formatting"
                          " instead of letting logger handle it.\nAt line "
                          "1 of '__TESTS__':\n    logger.debug('foo: %s' %"
                          " s)\n\n", self.output)

    def test_multiplied_string(self):
        src = "logger.debug('-' * 30)"
        self.examine_str(src)
        self.assertEquals("", self.output)

    def test_format_string_with_dot_format(self):
        src = "logger.debug('blah: {blah1}'.format(**some_dict))"
        self.examine_str(src)
        self.assertEquals("", self.output)


if __name__ == '__main__':
    unittest.main()
