""" Collection of data processing functions. """
import re

from util.regex import IMPORT_STATEMENT_REGEX, PACKAGE_DECLARATION_REGEX, PLACEHOLDER_REGEX, LINE_COMMENT_REGEX, \
    WHITESPACE_REGEX, MULTILINE_COMMENT_REGEX


def get_value_from_nested_dictionary(dictionary, access_path):
    """
    Use an access path (e.g., ["user", "first_name"]) to filter a nested dictionary.
    :param dictionary: the dictionary to filter
    :param access_path: a list with keys for filtering the nested dictionary
    :return: the resulting value
    :raises: KeyError if filtering using access_path is not possible in dictionary
    """

    # start with whole dictionary
    result = dictionary

    # loop through access path and filter dictionary accordingly
    for step in access_path:
        result = result[step]

    return result


def normalize_java(source_code):
    """
    Normalize a string with Java source code.
    (e.g., remove comments, imports, package declarations, whitespaces, etc.)
    :param source_code: string with Java code
    :return: normalized source code
    """

    # TODO: add test cases

    normalized_code_block = ""

    # start with line-based normalization
    lines = source_code.split('\n')
    for line in lines:
        # first convert line to lower case
        normalized_line = line.lower()

        # ignore import statements, package declarations, and lines like "..."
        if IMPORT_STATEMENT_REGEX.match(normalized_line) \
                or PACKAGE_DECLARATION_REGEX.match(normalized_line) \
                or PLACEHOLDER_REGEX.match(normalized_line):
            continue

        # remove line comments
        match = re.search(LINE_COMMENT_REGEX, normalized_line)
        if match:
            normalized_line = str(match.group(1))

        # remove special characters
        normalized_line = normalized_line.replace("{", "")
        normalized_line = normalized_line.replace("}", "")
        normalized_line = normalized_line.replace(";", "")
        normalized_line = normalized_line.replace("(", "")
        normalized_line = normalized_line.replace(")", "")

        # remove whitespaces
        normalized_line = re.sub(WHITESPACE_REGEX, '', normalized_line)

        # ignore empty lines
        if normalized_line:
            if not normalized_code_block:  # empty
                normalized_code_block = normalized_line
            else:  # append normalized line separated by blank
                normalized_code_block += " " + normalized_line

    # further normalization on whole string
    # remove multiline comments
    normalized_code_block = re.sub(MULTILINE_COMMENT_REGEX, '', normalized_code_block)
    # remove remaining blanks between normalized lines
    normalized_code_block = re.sub(WHITESPACE_REGEX, '', normalized_code_block)

    return normalized_code_block


def get_added_lines(patch):
    """
    Get lines added with a patch.
    (e.g., git diff between two versions of a file)
    :param patch: the content of the patch
    :return: the lines added by the patch
    """

    added_lines = ""

    lines = patch.split('\n')
    for line in lines:
        if line.startswith("+"):
            if not added_lines:  # empty
                added_lines = line[1:]
            else:  # append
                added_lines += line[1:] + "\n"

    return added_lines