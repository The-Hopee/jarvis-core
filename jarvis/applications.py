"""Speech aliases refer to registered application IDs, never shell commands."""
import re

ALIASES = {
    "telegram": "telegram", "телеграм": "telegram", "телеграмм": "telegram",
    "телеграмма": "telegram", "телеграмму": "telegram",
    "калькулятор": "calc", "calc": "calc", "блокнот": "notepad", "notepad": "notepad",
    "paint": "mspaint", "пейнт": "mspaint", "пэйнт": "mspaint",
    "vscode": "vscode", "vs code": "vscode", "вс код": "vscode", "вс коуд": "vscode",
    "ви эс код": "vscode", "ви эс коуд": "vscode", "вижуал студио код": "vscode",
    "visual studio code": "vscode", "код": "vscode",
    "onlyoffice": "onlyoffice", "only office": "onlyoffice", "онлиофис": "onlyoffice",
    "онли офис": "onlyoffice", "онли офисе": "onlyoffice",
}


def application_id(text):
    return ALIASES.get(re.sub(r"\s+", " ", text.casefold().strip()))
