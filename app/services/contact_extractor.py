import re

PHONE_PATTERN = re.compile(r"(?:\+7|7|8)?[\s\-()]*(\d[\d\s\-()]{8,}\d)")
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 11 and digits.startswith("7"):
        return "+" + digits
    if len(digits) >= 10:
        return "+" + digits
    return raw.strip()


def extract_contacts(text: str) -> dict[str, str | None]:
    phone_match = PHONE_PATTERN.search(text)
    email_match = EMAIL_PATTERN.search(text)

    phone = normalize_phone(phone_match.group(0)) if phone_match else None
    email = email_match.group(0).lower() if email_match else None

    return {"phone": phone, "email": email}
