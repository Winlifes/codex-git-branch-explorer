"""Explicit UI messages; repository strings never become translation keys."""
from pathlib import Path
from functools import lru_cache
import json


class Message(str):
    def __new__(cls, key, values=None):
        values = values or {}
        value = "".join(str(v) for v in values["parts"]) if key == "$concat" else key.format(**values)
        result = super().__new__(cls, value)
        result.key, result.values = key, values
        return result

    def __add__(self, other):
        return Message("$concat", {"parts": [self, other]})

    def __radd__(self, other):
        return Message("$concat", {"parts": [other, self]})

    def map_values(self, fn):
        def walk(value):
            if isinstance(value, Message):
                return value.map_values(fn)
            if isinstance(value, list):
                return [walk(item) for item in value]
            return fn(value) if isinstance(value, str) else value
        return Message(self.key, {key: walk(value) for key, value in self.values.items()})


def ui(key, **values):
    return Message(key, values)


def error_message(error):
    return getattr(error, "ui_message", None) or str(error)


def message_spec(value):
    if isinstance(value, Message):
        return {"key": value.key, "values": {key: message_spec(item) for key, item in value.values.items()},
                "_gitMessage": True}
    if isinstance(value, list):
        return [message_spec(item) for item in value]
    return value


def message_paths(value, path=()):
    if isinstance(value, Message):
        return [{"path": list(path), "message": message_spec(value)}]
    if isinstance(value, dict):
        return [entry for key, item in value.items() for entry in message_paths(item, (*path, key))]
    if isinstance(value, list):
        return [entry for index, item in enumerate(value) for entry in message_paths(item, (*path, index))]
    return []


def language(locale):
    return "zh" if isinstance(locale, str) and locale.lower().replace("_", "-").split("-")[0] == "zh" else "en"


@lru_cache(maxsize=1)
def english_catalog():
    return json.loads((Path(__file__).resolve().parents[1] / "assets/locales/en.json").read_text(encoding="utf-8"))


def translate(value, locale="zh-CN"):
    """Used for host-facing metadata only; panel messages retain their identity."""
    if not isinstance(value, Message):
        return value
    if value.key == "$concat":
        return "".join(str(translate(part, locale)) for part in value.values["parts"])
    template = value.key
    if language(locale) == "en":
        template = english_catalog().get(value.key, value.key)
    return template.format(**{key: translate(item, locale) for key, item in value.values.items()})


def translate_metadata(value, locale):
    if isinstance(value, Message):
        return translate(value, locale)
    if isinstance(value, list):
        return [translate_metadata(item, locale) for item in value]
    if isinstance(value, dict):
        return {key: translate_metadata(item, locale) for key, item in value.items()}
    return value


def requested_locale(metadata):
    if not isinstance(metadata, dict):
        return None
    locale = metadata.get("openai/locale", metadata.get("webplus/i18n"))
    return locale if isinstance(locale, str) and 0 < len(locale) <= 100 else None
