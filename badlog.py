#!/usr/bin/env python

import optparse
import tokenize
import logging
import sys
import os

logger = logging.getLogger(__name__)

# Not sure why 54 is not in token constants
IGNORED_TOKENS = set([tokenize.INDENT,
                      tokenize.NEWLINE,
                      54])


def get_next_token(tokens):
    while True:
        token = tokens.pop(0)
        logger.debug("Token: %s" % (token,))
        if token[0] not in IGNORED_TOKENS:
            break
    return token


class Transition(object):

    def __init__(self, new_state_name, tokens, *args, **kwargs):
        logger.debug("Transition: %s" % new_state_name)
        self.new_state_name = new_state_name
        self.tokens = tokens
        self.args = args
        self.kwargs = kwargs

    def __unicode__(self):
        return "Transition[new_state_name=%s]" % self.new_state_name

    def __str__(self):
        return unicode(self).encode("utf-8")


class BaseState(object):

    def __init__(self, filename, writer):
        self.filename = filename
        self.writer = writer
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
        self.writer.write(msg)
        self.writer.write("\n")

        row, _ = self.current_token[2]
        line = self.current_token[4].rstrip()

        self.writer.write("At line %d of '%s':\n" % (row, self.filename))
        self.writer.write("    %s\n\n" % line)

    @staticmethod
    def _matches_token_req(value, required_value):
        if required_value is None:
            return True
        if isinstance(required_value, (list, tuple, set)):
            return value in required_value
        return value == required_value


class UnreachableState(BaseState):

    NAME = "unreachable_state"

    def process(self, tokens):
        self.format_error("Got into a state we should never get into."
                          "  Don't know how to proceed.")
        return Transition("the_end", tokens)


class EndState(BaseState):

    NAME = "the_end"

    def process(self, _tokens):
        raise StopIteration


class TokenAnalysisMixin(object):

    def is_token(self, required_token_string=None, required_token_type=None):
        token_type, token_string = self.current_token[0:2]
        return (self._matches_token_req(token_type, required_token_type) and
                self._matches_token_req(token_string, required_token_string))

    def is_open_paren(self):
        return self.is_token("(", tokenize.OP)

    def is_close_paren(self):
        return self.is_token(")", tokenize.OP)

    def is_comma(self):
        return self.is_token(",", tokenize.OP)

    def is_dot(self):
        return self.is_token(".", tokenize.OP)

    def is_percent_sign(self):
        return self.is_token("%", tokenize.OP)

    def is_logger_method(self):
        return self.is_token(self.LOGGER_METHODS, tokenize.NAME)

    def is_fmt_string(self):
        return self.is_token(required_token_type=tokenize.STRING)

    def is_possible_logger_statement(self):
        return self.is_token(self.POSSIBLE_LOGGER_STRINGS, 1)


class CountingArgsState(BaseState, TokenAnalysisMixin):

    NAME = "counting_args"

    def __init__(self, filename, writer, expected_args, found_args):
        super(CountingArgsState, self).__init__(filename, writer)
        self.expected_args = expected_args
        self.found_args = found_args
        self.open_parens = 0

    def format_expected_actual_args_difference(self):
        self.format_error("Logger statement has %d format"
                          " specifiers but %d argument(s)." %
                          (self.expected_args,
                           self.found_args))

    def process(self, tokens):

        self.consume_next_token(tokens)

        # We first wind up in this state after processing the fmt
        # string and only if there were expected args... so if we land
        # here and right away there's a close paren we need to
        # bail...

        if self.found_args == 0 and self.is_close_paren():
            self.format_expected_actual_args_difference()
            return Transition("initial", tokens)

        # We need to handle the case where someone put a % after the
        # format string.  People shouldn't do this in logger
        # statements but unfortunately they do it all the time.
        if self.is_percent_sign():
            self.format_error("Logger statement uses % operator for"
                              " formatting instead of letting logger"
                              " handle it.")
            return Transition("initial", tokens)

        # Ok, so if we've made it here then we found something other
        # than a close paren which means it's an arg.. so we increment
        # the found count and now the problem is that it could be a
        # simple arg like "5" or it could be a complex nested arg like
        # "foo.bar(baz, bif(bam, lambda: 5))" so now we need to
        # basically just swallow everything checking for balanced
        # parens until we hit either a comma or a close paren.  If
        # it's a comma we increment the found count again and keep
        # going.  If it's a close paren then we need to check if
        # found_args matches expected_args and react accordingly.
        self.found_args += 1

        while True:
            self.consume_next_token(tokens)

            # Let's handle the simpliest case first:
            if self.is_comma() and self.open_parens <= 0:
                # We need to make sure that this isn't a 1-tuple argument
                # like so: foo(5,)
                # So we peek at the next token...
                self.consume_next_token(tokens)
                one_tuple = self.is_close_paren()
                self.rewind(tokens)

                if not one_tuple:
                    self.found_args += 1

            # Now the slightly more complicated case:
            elif self.is_close_paren():
                # The close paren case is simple if aren't in a nested
                # scope...we just exit the loop because we're done
                if self.open_parens <= 0:
                    break
                # If we're in a nested scope then we decrement the
                # nesting level and continue
                self.open_parens -= 1
            elif self.is_open_paren():
                self.open_parens += 1

        # If we're broken out of the loop then we reached the last matching
        # paren so now we just need to confirm whether we found the appropriate
        # number of args.
        if self.expected_args != self.found_args:
            self.format_expected_actual_args_difference()
        return Transition("initial", tokens)


class LoggerFormatStringState(BaseState, TokenAnalysisMixin):

    NAME = "logger_format_string"

    def count_format_specifiers(self):
        string = self.current_token[1]
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
        count = self.count_format_specifiers()

        # Now we have the first format specifier string, but there
        # could be others concatenated or separated with explicit
        # continuation characters, so we need to peek ahead until
        # we stop getting strings.  As long as we do get strings
        # we have to add their counts.

        while True:
            self.consume_next_token(tokens)
            if self.is_fmt_string():
                count += self.count_format_specifiers()
            else:
                # Since it wasn't another string we have to put it back
                self.rewind(tokens)
                break

        if count > 0:
            return Transition("counting_args", tokens, count, 0)
        else:
            # No format specifiers, so read the next token and confirm
            # that it's a close paren.
            return self.confirm_close_paren(tokens, count, 0)
        return Transition("unreachable_state", tokens)

    def format_diff_error(self, count, confirmed):
        self.format_error("Logger statement has %d format"
                          " specifiers but %d argument(s)." %
                          (count,
                           confirmed))

    def confirm_close_paren(self, tokens, count, confirmed):
        self.consume_next_token(tokens)
        if self.is_close_paren():
            return Transition("initial", tokens)
        else:
            self.rewind(tokens)
            return Transition("counting_args", tokens, 0, 0)


class PossibleLoggerStatementState(BaseState, TokenAnalysisMixin):

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
        return Transition("initial", tokens)

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
            return Transition("logger_format_string", tokens)
        except StopIteration:
            return self.back_to_initial()


class InitialState(BaseState, TokenAnalysisMixin):

    NAME = "initial"

    POSSIBLE_LOGGER_STRINGS = set(["logger", "LOG", "log", "LOGGER"])

    def process(self, tokens):
        # In this state, if we encounter a possible logger statement
        # token we want to transition to the logger state, otherwise
        # just swallow the token and stay in the same state, that's
        # it.
        try:
            self.consume_next_token(tokens)
        except IndexError:
            return Transition("the_end", tokens)
        if self.is_possible_logger_statement():
            return Transition("possible_logger_statement", tokens)
        return Transition("initial", tokens)


class BrokenLoggingDetectorStateMachine(object):

    def __init__(self):
        self.states = {}
        for state in [InitialState,
                      PossibleLoggerStatementState,
                      LoggerFormatStringState,
                      CountingArgsState,
                      EndState]:
            self.states[state.NAME] = state

    def make_new_state(self, filename, writer, transition):
        new_state_class = self.states[transition.new_state_name]
        new_state = new_state_class(*([filename,
                                       writer] + list(transition.args)),
                                     **transition.kwargs)
        return new_state

    def consume(self, tokens, filename, writer):
        state = InitialState(filename, writer)
        while True:
            try:
                transition = state.process(tokens)
                state = self.make_new_state(filename, writer, transition)
            except StopIteration:
                break


def examine_filelike(filename, filelike, writer=sys.stdout):
    tokens = list(tokenize.generate_tokens(filelike.readline))
    machine = BrokenLoggingDetectorStateMachine()
    machine.consume(tokens, filename, writer)


def examine(filename, verbose, writer=sys.stdout):
    if verbose:
        writer.write("Checking file: %s\n" % filename)
    try:
        with open(filename) as f:
            examine_filelike(filename, f, writer=writer)
    except IOError, ex:
        args = ex.args
        if isinstance(args, tuple):
            if args[0] != 2:  # No such file or directory
                raise


def recursively_examine(filename, verbose, writer=sys.stdout):
    for root, dirs, files in os.walk(filename):
        for fn in files:
            if fn.endswith(".py"):
                full_path = os.path.join(root, fn)
                examine(full_path, verbose, writer=writer)


def main():
    parser = optparse.OptionParser()
    parser.add_option("-v", "--verbose",
                      help="enable verbose output",
                      action="store_true")
    parser.add_option("-d", "--debug",
                      help="enable debugging output",
                      action="store_true")
    options, args = parser.parse_args()

    if options.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    for filename in args:
        if os.path.isdir(filename):
            recursively_examine(filename, options.verbose)
        else:
            examine(filename, options.verbose)


if __name__ == '__main__':
    main()
