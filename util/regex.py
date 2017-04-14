""" Collection of regular expressions. """

import re

URI_TEMPLATE_VARS_REGEX = re.compile(r'{(.+?)}')

# regular expressions to normalize Java files
IMPORT_STATEMENT_REGEX = re.compile(r'^\s*import')
PACKAGE_DECLARATION_REGEX = re.compile(r'^\s*package')
PLACEHOLDER_REGEX = re.compile(r'^\s*\.+\s*$')
LINE_COMMENT_REGEX = re.compile(r'(^.*?)(\/\/.*)$')
MULTILINE_COMMENT_REGEX = re.compile(r'(\/\*.*?\*\/)')
WHITESPACE_REGEX = re.compile(r'\s+')