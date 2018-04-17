""" Collection of regular expressions. """

import re

# regular expressions for api-retriever configuration
URI_TEMPLATE_VARS_REGEX = re.compile(r'{(.+?)}')
RANGE_VAR_REGEX = re.compile(r'(.+\|\d+;\d+;\d+)')
FLATTEN_OPERATOR_REGEX = re.compile(r'^(.+)\._$')

# regular expressions to normalize Java files (see callback_helpers.py)
IMPORT_STATEMENT_REGEX = re.compile(r'^\s*import')
PACKAGE_DECLARATION_REGEX = re.compile(r'^\s*package')
PLACEHOLDER_REGEX = re.compile(r'^\s*\.+\s*$')
LINE_COMMENT_REGEX = re.compile(r'(^.*?)(//.*)$')
MULTILINE_COMMENT_REGEX = re.compile(r'(/\*.*?\*/)')
WHITESPACE_REGEX = re.compile(r'\s+')
