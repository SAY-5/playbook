"""Emit the expected output of playbook/evals/report.py `_pct` for a fixed list of values.

The browser port formats percentages itself, so the web self-check compares its output with this
table rather than with a reimplementation of Python's rounding rules.

    uv run python scripts/pct-cases.py > web/src/fixtures/pct-cases.ts
"""

import json

# Exact binary ties (.25 and .75 at the second decimal), two values that only look like ties, a
# third and two thirds, and two negatives, which is what a delta row prints.
VALUES = [0.0, 0.125, 0.1235, 0.4375, 0.5625, 0.875, 0.9865, 1.0, 1 / 3, 2 / 3, -0.5625, -0.4375]

HEADER = """\
/* Expected output of `_pct` in playbook/evals/report.py for each value, so the self-check compares
   the ported percent formatting with Python's own output instead of with a second implementation
   of its rounding rules.

   Regenerate with: uv run python scripts/pct-cases.py > web/src/fixtures/pct-cases.ts */
export type PctCase = [value: number, expected: string];

export const PCT_CASES: PctCase[] = [
"""


def main() -> None:
    rows = "".join(f"  [{json.dumps(v)}, {json.dumps(f'{v * 100:.1f}%')}],\n" for v in VALUES)
    print(HEADER + rows + "];")


if __name__ == "__main__":
    main()
