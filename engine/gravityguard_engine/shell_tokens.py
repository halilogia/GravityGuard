"""Linear scanner matching the non-POSIX shlex mode used by shell guards."""
import re

_UNQUOTED = re.compile(r'[^ \t\r\n]+')


def split_command(segment: str) -> list[str]:
    """Preserve quotes and Windows paths; retain the legacy malformed-input fallback."""
    tokens = []
    index = 0
    while index < len(segment):
        char = segment[index]
        if char in ' \t\r\n':
            index += 1
            continue
        if char in "\"'":
            end = segment.find(char, index + 1)
            if end < 0:
                return segment.split()
            end += 1
        else:
            end = _UNQUOTED.match(segment, index).end()
        tokens.append(segment[index:end])
        index = end
    return tokens
