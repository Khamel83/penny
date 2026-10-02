"""Shared normalized complete-reference alignment for local public benchmarks."""

from array import array
import re


def integer_words(n):
    small = [
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
    ]
    tens = [
        "",
        "",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
    ]
    if n < 20:
        return small[n]
    if n < 100:
        return tens[n // 10] + (" " + small[n % 10] if n % 10 else "")
    if n < 1000:
        return (
            small[n // 100]
            + " hundred"
            + (" " + integer_words(n % 100) if n % 100 else "")
        )
    if n < 1000000:
        return (
            integer_words(n // 1000)
            + " thousand"
            + (" " + integer_words(n % 1000) if n % 1000 else "")
        )
    return " ".join(small[int(c)] for c in str(n))


def normalize(text, content=False):
    text = text.casefold().replace("’", "'").replace("%", " percent ")
    for a, b in {
        "can't": "can not",
        "cannot": "can not",
        "won't": "will not",
        "it's": "it is",
        "that's": "that is",
        "there's": "there is",
        "what's": "what is",
        "let's": "let us",
    }.items():
        text = text.replace(a, b)
    text = re.sub(r"n['’]t\b", " not", text)
    text = re.sub(r"['’]re\b", " are", text)
    text = re.sub(r"['’]ve\b", " have", text)
    text = re.sub(r"['’]ll\b", " will", text)
    text = re.sub(r"['’]m\b", " am", text)
    # Cosmetic number/ordinal and compound spacing changes apply to all texts.
    ordinals = {
        1: "first",
        2: "second",
        3: "third",
        4: "fourth",
        5: "fifth",
        6: "sixth",
        7: "seventh",
        8: "eighth",
        9: "ninth",
        10: "tenth",
    }
    text = re.sub(
        r"\b(\d{1,6})(st|nd|rd|th)\b",
        lambda m: ordinals.get(int(m[1]), integer_words(int(m[1])) + "th"),
        text,
    )
    text = re.sub(r"\b\d{1,6}\b", lambda m: integer_words(int(m[0])), text)
    text = re.sub(r"\bapple\s+iis\b", "apple twos", text)
    text = re.sub(r"\bapple\s+ii\b", "apple two", text)
    text = re.sub(r"\bspacetime\b", "space time", text)
    text = re.sub(r"\bbattlebots\b", "battle bots", text)
    tokens = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text)
    if content:
        result = []
        for token in tokens:
            if token in {"uh", "um", "hmm", "ah"}:
                continue
            if not result or result[-1] != token:
                result.append(token)
        return result
    return tokens


def align(reference, hypothesis, insertion_cost=1):
    """Align every reference token; optionally ignore interior extra words.

    Zero insertion cost measures lexical recall, not semantic accuracy or WER.
    """
    n, m = len(reference), len(hypothesis)
    d = [array("i", [0]) * (m + 1) for _ in range(n + 1)]
    matches = [array("i", [0]) * (m + 1) for _ in range(n + 1)]
    operations = [bytearray(m + 1) for _ in range(n + 1)]
    for row in range(n + 1):
        d[row][0] = row
        operations[row][0] = 1
    for i, a in enumerate(reference, 1):
        for j, b in enumerate(hypothesis, 1):
            choices = [
                (
                    int(d[i - 1][j - 1]) + (a != b),
                    int(matches[i - 1][j - 1]) + (a == b),
                    0,
                ),
                (int(d[i - 1][j]) + 1, int(matches[i - 1][j]), 1),
                (int(d[i][j - 1]) + insertion_cost, int(matches[i][j - 1]), 2),
            ]
            cost, equal, op = min(choices, key=lambda x: (x[0], -x[1], x[2]))
            d[i][j] = cost
            matches[i][j] = equal
            operations[i][j] = op
    j = min(range(m + 1), key=lambda k: (int(d[n][k]), -int(matches[n][k]), k))
    end = j
    i = n
    changes = []
    equal = 0
    counts = {"substitutions": 0, "deletions": 0, "insertions": 0}
    while i:
        op = operations[i][j]
        if op == 0:
            if reference[i - 1] == hypothesis[j - 1]:
                equal += 1
            else:
                counts["substitutions"] += 1
                changes.append(
                    {
                        "type": "substitution",
                        "ref_index": i - 1,
                        "reference": reference[i - 1],
                        "hypothesis": hypothesis[j - 1],
                    }
                )
            i -= 1
            j -= 1
        elif op == 1:
            counts["deletions"] += 1
            changes.append(
                {"type": "deletion", "ref_index": i - 1, "reference": reference[i - 1]}
            )
            i -= 1
        else:
            counts["insertions"] += 1
            changes.append(
                {"type": "insertion", "ref_index": i, "hypothesis": hypothesis[j - 1]}
            )
            j -= 1
    return {
        **counts,
        "reference_tokens": n,
        "equal_tokens": equal,
        "error_percent": 100 * sum(counts.values()) / max(1, n),
        "hypothesis_start": j,
        "hypothesis_end": end,
        "hypothesis_tokens": m,
        "changes": list(reversed(changes)),
    }
