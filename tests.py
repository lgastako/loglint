import unittest
import tokenize

from StringIO import StringIO

from badlog import get_next_token
from badlog import BaseState
from badlog import InitialState
from badlog import PossibleLoggerStatementState
from badlog import LoggerFormatStringState

TEST_FILENAME = "test.py"


class BaseStateTests(unittest.TestCase):

    def test_rewind(self):
        state = BaseState(TEST_FILENAME)

        expected_tokens = ["a", "b", "c", "d"]
        tokens = expected_tokens[:]

        state.consume_next_token(tokens)
        state.rewind(tokens)

        self.assertEquals(expected_tokens, tokens)

    def test_rewind_all(self):
        state = BaseState(TEST_FILENAME)

        expected_tokens = ["a", "b", "c", "d"]
        tokens = expected_tokens[:]

        state.consume_next_token(tokens)
        state.consume_next_token(tokens)
        state.consume_next_token(tokens)
        state.rewind_all(tokens)

        self.assertEquals(expected_tokens, tokens)


class InitialStateTests(unittest.TestCase):

    def test_state_transition_on_valid_logger(self):
        src = "logger.debug('hi there')"
        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        state = InitialState(TEST_FILENAME)
        new_state, tokens = state.process(tokens)
        self.assertEquals(PossibleLoggerStatementState.NAME, new_state)
        self.assertEquals(tokens[0][1], ".")

    def test_state_transition_on_not_valid_logger(self):
        src = "foo('hi there')"
        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        state = InitialState(TEST_FILENAME)
        new_state, tokens = state.process(tokens)
        self.assertEquals(InitialState.NAME, new_state)
        self.assertEquals(tokens[0][1], "(")


class PossibleLoggerStatementStateTests(unittest.TestCase):

    def test_state_transition_on_valid_logger(self):
        src = "logger.debug('hi there')"
        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        get_next_token(tokens)  # Eat the 'logger' token
        state = PossibleLoggerStatementState(TEST_FILENAME)
        new_state, tokens = state.process(tokens)
        self.assertEquals(LoggerFormatStringState.NAME, new_state)
        self.assertEquals(tokens[0][1], "'hi there'")

    def test_state_transition_on_not_valid_logger(self):
        src = "logger('hi there')"
        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        get_next_token(tokens)  # Eat the 'logger' token
        state = PossibleLoggerStatementState(TEST_FILENAME)
        new_state, tokens = state.process(tokens)
        self.assertEquals(InitialState.NAME, new_state)
        self.assertEquals(tokens[0][1], "(")

    def test_is_dot(self):
        src = "logger.debug('hi there')"
        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        get_next_token(tokens)  # Eat the 'logger' token
        state = PossibleLoggerStatementState(TEST_FILENAME)
        state.consume_next_token(tokens)
        self.assertEquals(True, state.is_dot())

    def test_is_open_paren(self):
        src = "logger.debug('hi there')"
        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        get_next_token(tokens)  # Eat the 'logger' token
        get_next_token(tokens)  # Eat the '.' token
        get_next_token(tokens)  # Eat the 'debug' token
        state = PossibleLoggerStatementState(TEST_FILENAME)
        state.consume_next_token(tokens)
        self.assertEquals(True, state.is_open_paren())

    def test_is_fmt_string(self):
        src = "logger.debug('hi there')"
        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        get_next_token(tokens)  # Eat the 'logger' token
        get_next_token(tokens)  # Eat the '.' token
        get_next_token(tokens)  # Eat the 'debug' token
        get_next_token(tokens)  # Eat the '(' token
        state = PossibleLoggerStatementState(TEST_FILENAME)
        state.consume_next_token(tokens)
        self.assertEquals(True, state.is_fmt_string())

    def test_back_to_initial(self):
        src = "logger.debug('hi there')"
        sio = StringIO(src)
        expected_tokens = list(tokenize.generate_tokens(sio.readline))
        tokens = expected_tokens[:]
        state = PossibleLoggerStatementState(TEST_FILENAME)
        state.consume_next_token(tokens)  # Eat the 'logger' token
        state.consume_next_token(tokens)  # Eat the '.' token
        state.consume_next_token(tokens)  # Eat the 'debug' token
        state.consume_next_token(tokens)  # Eat the '(' token
        new_state, tokens = state.back_to_initial(tokens)
        self.assertEquals("initial", new_state)
        self.assertEquals(expected_tokens, tokens)


class LoggerFormatStringStateTests(unittest.TestCase):

    def make_state(self, src):
        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        state = LoggerFormatStringState(TEST_FILENAME)
        state.consume_next_token(tokens)  # Eat the 'logger' token
        state.consume_next_token(tokens)  # Eat the '.' token
        state.consume_next_token(tokens)  # Eat the 'debug' to ken
        state.consume_next_token(tokens)  # Eat the '(' token
        state.consume_next_token(tokens)  # Eat the fmt string
        return state

    def test_count_format_specifiers_none(self):
        state = self.make_state("logger.debug('foo')")
        self.assertEquals(0,
                          state.count_format_specifiers(state.current_token))

    def test_count_format_specifiers_one(self):
        state = self.make_state("logger.debug('foo: %s')")
        self.assertEquals(1,
                          state.count_format_specifiers(state.current_token))

    def test_count_format_specifiers_two(self):
        state = self.make_state("logger.debug('foo: %s %d')")
        self.assertEquals(2,
                          state.count_format_specifiers(state.current_token))

    def test_count_format_specifiers_with_escaped_percent(self):
        state = self.make_state("logger.debug('foo: %s 50%% %d')")
        self.assertEquals(2,
                          state.count_format_specifiers(state.current_token))


class IntegrationTests(unittest.TestCase):

    def test_multiple_lines(self):
        src = """
                  logger.debug('hi %s',
                               'there')
               """
        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        state = InitialState(TEST_FILENAME)
        new_state, tokens = state.process(tokens)
        self.assertEquals(PossibleLoggerStatementState.NAME, new_state)
        self.assertEquals(tokens[0][1], ".")
        state = PossibleLoggerStatementState(TEST_FILENAME)
        new_state, tokens = state.process(tokens)

    def test_ignore_newlines(self):
        src = """
                  logger.debug("hi there")
              """

        sio = StringIO(src)
        tokens = list(tokenize.generate_tokens(sio.readline))
        state = InitialState(TEST_FILENAME)
        new_state, tokens = state.process(tokens)
        self.assertEquals(PossibleLoggerStatementState.NAME, new_state)


if __name__ == '__main__':
    unittest.main()
