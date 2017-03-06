'''This module contains functions related to raw metrics.

The main function is :func:`~radon.raw.analyze`, and should be the only one
that is used.
'''

import tokenize
import operator
import collections
try:
    import StringIO as io
except ImportError:  # pragma: no cover
    import io


__all__ = ['OP', 'COMMENT', 'TOKEN_NUMBER', 'NL', 'EM', 'Module', '_generate',
           '_less_tokens', '_find', '_logical', 'analyze']

COMMENT = tokenize.COMMENT
OP = tokenize.OP
NL = tokenize.NL
EM = tokenize.ENDMARKER

# Helper for map()
TOKEN_NUMBER = operator.itemgetter(0)

# A module object. It contains the following data:
#   loc = Lines of Code (total lines)
#   lloc = Logical Lines of Code
#   comments = Comments lines
#   multi = Multi-line strings (assumed to be docstrings)
#   blank = Blank lines (or whitespace-only lines)
#   single_comments = Single-line comments or docstrings
Module = collections.namedtuple('Module', ['loc', 'lloc', 'sloc',
                                           'comments', 'multi', 'blank',
                                           'single_comments'])


def _generate(code):
    '''Pass the code into `tokenize.generate_tokens` and convert the result
    into a list.
    '''
    return list(tokenize.generate_tokens(io.StringIO(code).readline))


def _less_tokens(tokens, remove):
    '''Process the output of `tokenize.generate_tokens` removing
    the tokens specified in `remove`.
    '''
    for values in tokens:
        if values[0] in remove:
            continue
        yield values


def _find(tokens, token, value):
    '''Return the position of the last token with the same (token, value)
    pair supplied. The position is the one of the rightmost term.
    '''
    for index, token_values in enumerate(reversed(tokens)):
        if (token, value) == token_values[:2]:
            return len(tokens) - index - 1
    raise ValueError('(token, value) pair not found')


def _split_tokens(tokens, token, value):
    '''Split a list of tokens on the specified token pair (token, value),
    where *token* is the token type (i.e. its code) and *value* its actual
    value in the code.
    '''
    res = [[]]
    for token_values in tokens:
        if (token, value) == token_values[:2]:
            res.append([])
            continue
        res[-1].append(token_values)
    return res


def _get_all_tokens(line, lines):
    '''Starting from *line*, generate the necessary tokens which represent the
    shortest tokenization possible. This is done by catching
    :exc:`tokenize.TokenError` when a multi-line string or statement is
    encountered.
    :returns: tokens, lines
    '''
    used_lines = [line]
    while True:
        try:
            tokens = _generate(line)
        except tokenize.TokenError:
            # A multi-line string or statement has been encountered:
            # start adding lines and stop when tokenize stops complaining
            pass
        else:
            if not any(t[0] == tokenize.ERRORTOKEN for t in tokens):
                return tokens, used_lines

        # Add another line
        next_line = next(lines)
        line = line + '\n' + next_line
        used_lines.append(next_line)


def _logical(tokens):
    '''Find how many logical lines are there in the current line.

    Normally 1 line of code is equivalent to 1 logical line of code,
    but there are cases when this is not true. For example::

        if cond: return 0

    this line actually corresponds to 2 logical lines, since it can be
    translated into::

        if cond:
            return 0

    Examples::

        if cond:  -> 1

        if cond: return 0  -> 2

        try: 1/0  -> 2

        try:  -> 1

        if cond:  # Only a comment  -> 1

        if cond: return 0  # Only a comment  -> 2
    '''
    def aux(sub_tokens):
        '''The actual function which does the job.'''
        # Get the tokens and, in the meantime, remove comments
        processed = list(_less_tokens(sub_tokens, [COMMENT]))
        try:
            # Verify whether a colon is present among the tokens and that
            # it is the last token.
            token_pos = _find(processed, OP, ':')
            return 2 - (token_pos == len(processed) - 2)
        except ValueError:
            # The colon is not present
            # If the line is only composed by comments, newlines and endmarker
            # then it does not count as a logical line.
            # Otherwise it count as 1.
            if not list(_less_tokens(processed, [NL, EM])):
                return 0
            return 1
    return sum(aux(sub) for sub in _split_tokens(tokens, OP, ';'))


def analyze(source):
    '''Analyze the source code and return a namedtuple with the following
    fields:

        * **loc**: The number of lines of code (total)
        * **lloc**: The number of logical lines of code
        * **sloc**: The number of source lines of code (not necessarily
            corresponding to the LLOC)
        * **comments**: The number of Python comment lines
        * **multi**: The number of lines which represent multi-line strings
        * **single_comments**: The number of lines which are just comments with no code
        * **blank**: The number of blank lines (or whitespace-only ones)

    The equation :math:`sloc + blanks + multi + single_comments = loc` should always hold.
    Multiline strings are not counted as comments, since, to the Python
    interpreter, they are not comments but strings.
    '''
    lloc = comments = single_comments = multi = blank = sloc = 0
    lines = (l.strip() for l in source.splitlines())
    for lineno, line in enumerate(lines, 1):
        try:
            # Process a logical line that spans on multiple lines
            tokens, parsed_lines = _get_all_tokens(line, lines)
        except StopIteration:
            raise SyntaxError('SyntaxError at line: {0}'.format(lineno))

        # Identify single line comments
        for token_type, _, (start_row, start_col), (end_row, end_col), _ in tokens:
            if token_type == tokenize.COMMENT:
                if start_col == 0:  # Single line comments start on column 0
                    single_comments += (end_row - start_row + 1)
                comments += 1

        # Identify docstrings
        if tokens[0][0] == tokenize.STRING:
            if (tokens[1][0] == tokenize.ENDMARKER or all(
                    t[0] in (tokenize.STRING, tokenize.NL) for t in tokens[:-2])):
                _, _, (start_row, start_col), _, _ = tokens[0]
                _, _, _, (end_row, end_col), _ = tokens[-2]
                # Multiline docstrings start on column 0
                if start_col == 0:
                    if end_row == start_row:
                        # Consider single-line docstrings separately from other multiline docstrings
                        # Note that strings with continuation are considered multiline
                        single_comments += 1
                    else:
                        multi += sum(1 for l in parsed_lines if l)  # Skip empty lines

        for parsed_line in parsed_lines:
            if parsed_line:
                sloc += 1
            else:
                blank += 1

        # Process a logical line
        # Split it on semicolons because they increase the number of logical
        # lines
        for sub_tokens in _split_tokens(tokens, OP, ';'):
            lloc += _logical(sub_tokens)

    loc = sloc - multi - single_comments
    return Module(loc, lloc, sloc, comments, multi, blank, single_comments)
