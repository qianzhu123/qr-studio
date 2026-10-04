"""qr_payloads.py - Structured payload builders for common QR conventions.

A QR code encodes an arbitrary byte string. "Advanced" uses are just
well-known string formats that a consuming app parses: WIFI:, vCard, MECARD,
mailto:, tel:, SMSTO:, geo:, otpauth:, VEVENT, SEPA/EPC, a GS1 element string,
and so on. This module builds and validates those strings.

Each type is described by a schema (fields) so a UI can render it dynamically,
and by a build(fields) function that returns the final text.
"""
from __future__ import annotations

import urllib.parse
from typing import Callable


# --------------------------------------------------------------------------
# Escaping helpers
# --------------------------------------------------------------------------

def _vcard_escape(s: str) -> str:
    """Escape a value per RFC 6350 (vCard 4) / 2426 (vCard 3)."""
    return (s.replace("\\", "\\\\").replace(";", "\\;")
             .replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n"))


def _mecard_escape(s: str) -> str:
    return (s.replace("\\", "\\\\").replace(";", "\\;")
             .replace(",", "\\,").replace(":", "\\:"))


def _wifi_escape(s: str) -> str:
    out = []
    for ch in s:
        if ch in '\\;,:"':
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _crlf_join(lines: list[str]) -> str:
    return "\r\n".join(lines) + "\r\n"


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------

def build_text(f: dict) -> str:
    return f.get("text", "")


def build_url(f: dict) -> str:
    return f.get("url", "").strip()


def build_vcard(f: dict) -> str:
    first = f.get("first", "").strip()
    last = f.get("last", "").strip()
    lines = ["BEGIN:VCARD", "VERSION:3.0",
             f"N:{_vcard_escape(last)};{_vcard_escape(first)};;;",
             f"FN:{_vcard_escape((first + ' ' + last).strip())}"]
    if f.get("org"):
        lines.append(f"ORG:{_vcard_escape(f['org'])}")
    if f.get("title"):
        lines.append(f"TITLE:{_vcard_escape(f['title'])}")
    if f.get("phone"):
        lines.append(f"TEL;TYPE=CELL:{_vcard_escape(f['phone'])}")
    if f.get("email"):
        lines.append(f"EMAIL:{_vcard_escape(f['email'])}")
    if f.get("url"):
        lines.append(f"URL:{_vcard_escape(f['url'])}")
    if f.get("address"):
        lines.append(f"ADR:;;{_vcard_escape(f['address'])};;;;")
    if f.get("note"):
        lines.append(f"NOTE:{_vcard_escape(f['note'])}")
    lines.append("END:VCARD")
    return _crlf_join(lines)


def build_mecard(f: dict) -> str:
    parts = [f"MECARD:N:{_mecard_escape(f.get('last',''))},{_mecard_escape(f.get('first',''))}"]
    if f.get("phone"):
        parts.append(f"TEL:{_mecard_escape(f['phone'])}")
    if f.get("email"):
        parts.append(f"EMAIL:{_mecard_escape(f['email'])}")
    if f.get("url"):
        parts.append(f"URL:{_mecard_escape(f['url'])}")
    if f.get("note"):
        parts.append(f"NOTE:{_mecard_escape(f['note'])}")
    return ";".join(parts) + ";;"


def build_email(f: dict) -> str:
    to = f.get("to", "").strip()
    q = {}
    if f.get("subject"):
        q["subject"] = f["subject"]
    if f.get("body"):
        q["body"] = f["body"]
    query = ("?" + urllib.parse.urlencode(q)) if q else ""
    return f"mailto:{to}{query}"


def build_tel(f: dict) -> str:
    return "tel:" + f.get("number", "").strip()


def build_sms(f: dict) -> str:
    number = f.get("number", "").strip()
    body = f.get("body", "")
    return f"SMSTO:{number}:{body}" if body else f"SMSTO:{number}"


def build_geo(f: dict) -> str:
    lat = f.get("lat", "").strip()
    lng = f.get("lng", "").strip()
    return f"geo:{lat},{lng}"


def build_wifi(f: dict) -> str:
    ssid = f.get("ssid", "")
    sec = (f.get("security") or "WPA").upper()
    if sec not in ("WPA", "WEP", "NOPASS", "NONE"):
        raise ValueError("wifi security must be WPA, WEP or NOPASS")
    if sec == "NONE":
        sec = "nopass"
    pwd = f.get("password", "")
    hidden = "true" if f.get("hidden") else "false"
    out = f"WIFI:T:{sec};S:{_wifi_escape(ssid)};"
    if sec.lower() != "nopass":
        out += f"P:{_wifi_escape(pwd)};"
    if f.get("hidden"):
        out += f"H:{hidden};"
    return out + ";"


def build_otpauth(f: dict) -> str:
    label = f.get("label", "").strip()
    secret = f.get("secret", "").strip().replace(" ", "")
    if not secret:
        raise ValueError("otpauth requires a secret")
    issuer = f.get("issuer", "").strip()
    algo = (f.get("algorithm") or "SHA1").upper()
    if algo not in ("SHA1", "SHA256", "SHA512"):
        raise ValueError("algorithm must be SHA1, SHA256 or SHA512")
    digits = str(f.get("digits") or "6")
    if digits not in ("6", "8"):
        raise ValueError("digits must be 6 or 8")
    period = str(f.get("period") or "30")
    q = {"secret": secret, "algorithm": algo, "digits": digits, "period": period}
    if issuer:
        q["issuer"] = issuer
        label = f"{issuer}:{label}" if label else issuer
    return "otpauth://totp/" + urllib.parse.quote(label) + "?" + urllib.parse.urlencode(q)


def build_event(f: dict) -> str:
    lines = ["BEGIN:VEVENT",
             f"SUMMARY:{_vcard_escape(f.get('summary',''))}"]
    if f.get("location"):
        lines.append(f"LOCATION:{_vcard_escape(f['location'])}")
    if f.get("start"):
        lines.append(f"DTSTART:{f['start'].strip()}")
    if f.get("end"):
        lines.append(f"DTEND:{f['end'].strip()}")
    if f.get("description"):
        lines.append(f"DESCRIPTION:{_vcard_escape(f['description'])}")
    lines.append("END:VEVENT")
    return _crlf_join(lines)


def build_sepa(f: dict) -> str:
    """SEPA credit transfer QR (EPC069-12 payload), EUR only."""
    name = f.get("name", "").strip()
    iban = f.get("iban", "").strip().replace(" ", "")
    amount = f.get("amount", "").strip()
    if not name or not iban or not amount:
        raise ValueError("SEPA requires name, IBAN and amount")
    try:
        amount = f"EUR{float(amount):.2f}"
    except ValueError:
        raise ValueError("amount must be a number")
    lines = ["BCD", "002", "1", "SCT",
             f.get("bic", "").strip(), name, iban, amount]
    if f.get("remittance"):
        lines += ["", _vcard_escape(f["remittance"][:140])]
    return _crlf_join(lines)


def build_gs1(f: dict) -> str:
    """GS1 element string. Encoded with FNC1 (set content.fnc1 = true).

    Provide AI=value pairs as 'ai:value' lines, e.g.
      01:09501101530003
      10:ABC123
    """
    raw = f.get("elements", "").strip()
    if not raw:
        raise ValueError("GS1 requires at least one AI element")
    elems = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" not in line:
            raise ValueError(f"invalid GS1 element (expected ai:value): {line}")
        ai, val = line.split(":", 1)
        elems.append(ai.strip() + val.strip())
    return "".join(elems)


def build_json(f: dict) -> str:
    return f.get("json", "").strip()


def build_kv(f: dict) -> str:
    return f.get("kv", "").strip()


BUILDERS: dict[str, Callable[[dict], str]] = {
    "text": build_text, "url": build_url, "vcard": build_vcard,
    "mecard": build_mecard, "email": build_email, "tel": build_tel,
    "sms": build_sms, "geo": build_geo, "wifi": build_wifi,
    "otpauth": build_otpauth, "event": build_event, "sepa": build_sepa,
    "gs1": build_gs1, "json": build_json, "kv": build_kv,
}


# --------------------------------------------------------------------------
# Schema (drives the UI)
# --------------------------------------------------------------------------

def _field(name, en, zh, kind="text", default="", placeholder="", options=None):
    d = {"name": name, "label_en": en, "label_zh": zh, "kind": kind,
         "default": default, "placeholder": placeholder}
    if options:
        d["options"] = options
    return d


TYPES = [
    {"id": "text", "label_en": "Text", "label_zh": "文本",
     "fields": [_field("text", "Text", "文本", "textarea", "", "Any text")]},
    {"id": "url", "label_en": "URL", "label_zh": "网址",
     "fields": [_field("url", "URL", "网址", "text", "", "https://example.com")]},
    {"id": "vcard", "label_en": "Contact (vCard)", "label_zh": "联系人 (vCard)",
     "fields": [_field("first", "First name", "名"), _field("last", "Last name", "姓"),
                _field("org", "Organization", "组织"), _field("title", "Title", "职务"),
                _field("phone", "Phone", "电话"), _field("email", "Email", "邮箱"),
                _field("url", "Website", "网址"), _field("address", "Address", "地址"),
                _field("note", "Note", "备注", "textarea")]},
    {"id": "mecard", "label_en": "Contact (MECARD)", "label_zh": "联系人 (MECARD)",
     "fields": [_field("first", "First name", "名"), _field("last", "Last name", "姓"),
                _field("phone", "Phone", "电话"), _field("email", "Email", "邮箱"),
                _field("url", "Website", "网址"), _field("note", "Note", "备注")]},
    {"id": "email", "label_en": "Email", "label_zh": "邮件",
     "fields": [_field("to", "To", "收件人", "text", "", "a@b.com"),
                _field("subject", "Subject", "主题"),
                _field("body", "Body", "正文", "textarea")]},
    {"id": "tel", "label_en": "Phone call", "label_zh": "拨打电话",
     "fields": [_field("number", "Number", "号码", "text", "", "+8613800000000")]},
    {"id": "sms", "label_en": "SMS", "label_zh": "短信",
     "fields": [_field("number", "Number", "号码"), _field("body", "Message", "内容", "textarea")]},
    {"id": "geo", "label_en": "Location", "label_zh": "位置",
     "fields": [_field("lat", "Latitude", "纬度", "text", "", "31.2304"),
                _field("lng", "Longitude", "经度", "text", "", "121.4737")]},
    {"id": "wifi", "label_en": "WiFi", "label_zh": "WiFi 配网",
     "fields": [_field("ssid", "SSID", "网络名"),
                _field("security", "Security", "加密方式", "select", "WPA", "", ["WPA", "WEP", "NOPASS"]),
                _field("password", "Password", "密码"),
                _field("hidden", "Hidden network", "隐藏网络", "checkbox")]},
    {"id": "otpauth", "label_en": "TOTP (2FA)", "label_zh": "TOTP 两步验证",
     "fields": [_field("label", "Account", "账户", "text", "", "alice@example.com"),
                _field("secret", "Secret (Base32)", "密钥 (Base32)"),
                _field("issuer", "Issuer", "发行方"),
                _field("algorithm", "Algorithm", "算法", "select", "SHA1", "", ["SHA1", "SHA256", "SHA512"]),
                _field("digits", "Digits", "位数", "select", "6", "", ["6", "8"]),
                _field("period", "Period (s)", "周期(秒)", "text", "30")]},
    {"id": "event", "label_en": "Calendar event", "label_zh": "日历事件",
     "fields": [_field("summary", "Summary", "标题"),
                _field("location", "Location", "地点"),
                _field("start", "Start (yyyymmddThhmmss)", "开始", "text", "", "20261005T090000"),
                _field("end", "End", "结束", "text", "", "20261005T100000"),
                _field("description", "Description", "描述", "textarea")]},
    {"id": "sepa", "label_en": "SEPA transfer", "label_zh": "SEPA 转账",
     "fields": [_field("name", "Beneficiary name", "收款人", "text", "", "Max Mustermann"),
                _field("iban", "IBAN", "IBAN"),
                _field("bic", "BIC (optional)", "BIC（可选）"),
                _field("amount", "Amount EUR", "金额(欧元)", "text", "", "12.50"),
                _field("remittance", "Remittance", "附言")]},
    {"id": "gs1", "label_en": "GS1 element string", "label_zh": "GS1 元素串",
     "fields": [_field("elements", "AI:value per line", "每行一个 AI:值", "textarea", "",
                       "01:09501101530003\n10:ABC123")]},
    {"id": "json", "label_en": "JSON", "label_zh": "JSON",
     "fields": [_field("json", "JSON", "JSON", "textarea", "", '{"a":1}')]},
    {"id": "kv", "label_en": "Key=value", "label_zh": "键值对",
     "fields": [_field("kv", "One key=value per line", "每行一个 键=值", "textarea")]},
]


def type_schema() -> list[dict]:
    return TYPES


def build_payload(type_id: str, fields: dict) -> tuple[str, bool]:
    """Return (text, needs_fnc1). Raises ValueError on invalid input."""
    if type_id not in BUILDERS:
        raise ValueError(f"unknown payload type: {type_id}")
    text = BUILDERS[type_id](fields or {})
    return text, (type_id == "gs1")
