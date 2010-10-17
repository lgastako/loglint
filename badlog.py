#!/usr/bin/env python

import logging
import optparse
import os
import tokenize

logger = logging.getLogger(__name__)


def get_next_token(tokens):
    while True:
        token = tokens.pop(0)
        if token[0] not in (5, 54):
            break
    return token


class BaseState(object):

    def __init__(self, filename):
        self.filename = filename
        self.consumed_tokens = []

    @property
    def NAME(self):
        raise NotImplementedError

    def process(self, tokens):
        raise NotImplementedError

    def consume_next_token(self, tokens):
        next_token = get_next_token(tokens)
        self.consumed_tokens.append(next_token)

    def rewind(self, tokens):
        token = self.consumed_tokens.pop()
        tokens.insert(0, token)

    def rewind_all(self, tokens):
        while len(self.consumed_tokens):
            self.rewind(tokens)

    @property
    def current_token(self):
        return self.consumed_tokens[-1]

    def format_error(self, msg):
        print msg
        row, _ = self.current_token[2]
        line = self.current_token[4].rstrip()
        print "At line %d of '%s':" % (row, self.filename)
        print "    %s" % line
        print

    @staticmethod
    def _matches_token_req(value, required_value):
        if required_value is None:
            return True
        if isinstance(required_value, (list, tuple, set)):
            return value in required_value
        return value == required_value

    def is_token(self, required_token_string=None, required_token_type=None):
        token_type, token_string = self.current_token[0:2]
        return (self._matches_token_req(token_type, required_token_type) and
                self._matches_token_req(token_string, required_token_string))


class OpenParenMixin(object):

    def is_open_paren(self):
        return self.is_token("(", 51)


class LoggerFormatStringState(BaseState, OpenParenMixin):

    NAME = "logger_format_string"

    # TODO: Heavy unit tests.
    def count_format_specifiers(self, token):
        string = token[1]
        count = 0
        skip = False
        for index in xrange(len(string)):
            if skip:
                skip = False
            else:
                try:
                    if string[index] == "%":
                        if string[index + 1] == "%":
                            skip = True
                        else:
                            count += 1
                except IndexError:
                    pass
        return count

    def is_close_paren(self):
        return self.is_token(")", 51)

    def is_comma(self):
        # TODO: token_type
        return self.is_token(",")

    def process(self, tokens):
        # At this point the format string is going to be the first
        # token.  We need to parse it and figure out how many format
        # strings are in it.  If count > 0 then we need to pop the
        # args and make sure there are the right number before the
        # close paren, leaving tokens with everything through the
        # right paren consumed.  If it's 0 we just need to confirm
        # that the next token is the right paren (and consume it) If
        # there's a mismatch, print it (and move on)... either way we
        # should return to the initial state right after the close
        # paren.
        self.consume_next_token(tokens)
        count = self.count_format_specifiers(self.current_token)
        if count > 0:
            confirmed = 0
            open_parens = 0
            while confirmed < count:
                try:
                    self.consume_next_token(tokens)
                except IndexError:
                    self.format_error("ERROR! Ran out of tokens looking for"
                                      " a close paren.")
                    return None, None

                if self.is_comma():
                    continue

                if self.is_open_paren():
                    open_parens += 1
                elif self.is_close_paren():
                    if open_parens > 0:
                        open_parens -= 1
                        confirmed += 1
                    else:
                        self.format_error("Logger statement has %d format"
                                          " specifiers but only %d arguments" %
                                          (count, confirmed))
                        return "initial", tokens
                elif open_parens <= 0:
                    confirmed += 1

            # If we made it here that means that confirmed hit count, so
            # we are good and can go back to initial.
            return "initial", tokens
        else:
            # No format specifiers, so read the next token and confirm
            # that it's a close paren otherwise print a warning.
            self.consume_next_token(tokens)
            if not self.is_close_paren():
                self.format_error("Logger statement with no format specifiers "
                                  "but one or more args")
            return "initial", tokens
        return "OH SHIT HOW DID WE GET HERE?", None


class PossibleLoggerStatementState(BaseState, OpenParenMixin):

    NAME = "possible_logger_statement"

    # TODO: Are there others?
    LOGGER_METHODS = ["debug",
                      "info",
                      "warn",
                      "error",
                      "exception",
                      "critical"]

    def back_to_initial(self, tokens):
        self.rewind_all(tokens)
        return "initial", tokens

    def is_dot(self):
        return self.is_token(".", 51)

    def is_logger_method(self):
        return self.is_token(self.LOGGER_METHODS, 1)

    def is_fmt_string(self):
        return self.is_token(required_token_type=3)

    def process(self, tokens):
        # If we get here, the previous state has already swallowed the
        # statement that was the possible logger statement so we want
        # do everything we need to do to confirm that we are in a
        # logger statement... if we are successful then we want to
        # leave things in a state where the format string is the next
        # token and transition to the appropriate state to move
        # forward otherwise we want to put back all the tokens we
        # popped and return to the initial state.

        try:
            # Yeah, yeah, I know.  Refactor.
            self.consume_next_token(tokens)
            if not self.is_dot():
                return self.back_to_initial(tokens)

            self.consume_next_token(tokens)
            if not self.is_logger_method():
                return self.back_to_initial(tokens)

            self.consume_next_token(tokens)
            if not self.is_open_paren():
                return self.back_to_initial(tokens)

            self.consume_next_token(tokens)
            if not self.is_fmt_string():
                return self.back_to_initial(tokens)

            # If we made it here, we have popped a format string off,
            # so we want to put it back for the next state to access
            # and then transition to that state
            self.rewind(tokens)
            return "logger_format_string", tokens
        except StopIteration:
            return self.back_to_initial()


class InitialState(BaseState):

    NAME = "initial"

    POSSIBLE_LOGGER_STRINGS = set(["logger", "LOG", "log", "LOGGER"])

    def is_possible_logger_statement(self):
        token_type, token_string, _, _, _ = self.current_token
        return token_type == 1 and token_string in self.POSSIBLE_LOGGER_STRINGS

    def process(self, tokens):
        # In this state, if we encounter a possible logger statement
        # token we want to transition to the logger state, otherwise
        # just swallow the token and stay in the same state, that's
        # it.
        try:
            self.consume_next_token(tokens)
        except IndexError:
            return None, None
        if self.is_possible_logger_statement():
            return "possible_logger_statement", tokens
        return "initial", tokens


class BrokenLoggingDetectorStateMachine(object):

    def __init__(self):
        self.states = {}
        for state in [InitialState,
                      PossibleLoggerStatementState,
                      LoggerFormatStringState]:
            self.states[state.NAME] = state

    def consume(self, tokens, filename):
        state = InitialState(filename)
        while True:
            try:
                new_state_name, tokens = state.process(tokens)
                if new_state_name is None:
                    break
                state = self.states[new_state_name](filename)
            except StopIteration:
                break


def examine(filename):
    machine = BrokenLoggingDetectorStateMachine()
    with open(filename) as f:
        tokens = list(tokenize.generate_tokens(f.readline))
        machine.consume(tokens, filename)


def recursively_examine(filename):
    for root, dirs, files in os.walk(filename):
        for fn in files:
            if fn.endswith(".py"):
                full_path = os.path.join(root, fn)
                examine(full_path)


def main():
    parser = optparse.OptionParser()
    options, args = parser.parse_args()

    for filename in args:
        if os.path.isdir(filename):
            recursively_examine(filename)
        else:
            examine(filename)


if __name__ == '__main__':
    main()
