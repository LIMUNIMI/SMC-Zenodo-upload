"""Terminal output helpers."""

import os
import sys

ANSI_COLORS = {'red': 31, 'green': 32, 'yellow': 33}
if os.name == 'nt' and sys.stdout.isatty():
    os.system('')  # enables ANSI escape sequences in the Windows console


def secho(message, fg=None):
    """Print a message, coloured when writing to a terminal."""
    if fg in ANSI_COLORS and sys.stdout.isatty():
        print(f"\033[{ANSI_COLORS[fg]}m{message}\033[0m")
    else:
        print(message)


def print_response(resp, color='red'):
    """Print a requests.Response as JSON if possible, otherwise as raw text."""
    try:
        data = resp.json()
        secho(data, fg=color)
    except ValueError:
        # Not JSON (e.g., HTML 413 page); print raw text
        secho(resp.text, fg=color)
