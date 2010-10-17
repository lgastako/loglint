#!/usr/bin/env python

import logging
import optparse

from zillion.utils import cmdline

logger = logging.getLogger(__name__)


def main():
    parser = optparse.OptionParser()
    options, args = parser.parse_args()

    logger.debug("foo")
    logger.debug("foo", 1)
    logger.debug("foo: %s", 1)
    logger.debug("foo: %s %s", 2, 3, 4)
    logger.debug("foo: %s %s", 5)


cmdline.entry_point(__name__, main)
