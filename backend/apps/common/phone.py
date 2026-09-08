"""
Bangladesh mobile number handling (FR-CHK-3).

One normalised form is stored everywhere -- 01XXXXXXXXX, eleven digits -- so an
order placed with "+8801712345678" and a saved address holding "01712345678"
are recognisably the same subscriber. Accepting the alternatives is a courtesy
at the edge; storing them would leave the database unable to compare two
numbers for equality.
"""
import re

# 01[3-9] + 8 digits. The leading +880 / 880 / 0088 forms are stripped first.
_LOCAL_RE = re.compile(r"^01[3-9]\d{8}$")
_SEPARATORS_RE = re.compile(r"[\s\-().]")

PHONE_ERROR_MESSAGE = (
    "Enter a valid Bangladesh mobile number, e.g. 01712345678 or +8801712345678."
)


class InvalidPhoneNumber(ValueError):
    """Raised by normalise_phone when the input cannot be a BD mobile number."""


def normalise_phone(value):
    """
    Return the canonical 01XXXXXXXXX form.

    Raises InvalidPhoneNumber for anything that is not a Bangladesh mobile
    number. Callers at the HTTP edge translate that into a field error; the
    service layer lets it surface, because an unreachable phone number on a
    Cash-on-Delivery order is an undeliverable order.
    """
    if value is None:
        raise InvalidPhoneNumber(PHONE_ERROR_MESSAGE)

    digits = _SEPARATORS_RE.sub("", str(value).strip())
    if digits.startswith("+"):
        digits = digits[1:]
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("880"):
        digits = "0" + digits[3:]

    if not _LOCAL_RE.match(digits):
        raise InvalidPhoneNumber(PHONE_ERROR_MESSAGE)
    return digits


def is_valid_phone(value):
    try:
        normalise_phone(value)
    except InvalidPhoneNumber:
        return False
    return True
