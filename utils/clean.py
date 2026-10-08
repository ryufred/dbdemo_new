"""raw(Tally 응답) → master 형식으로 정리하는 순수 함수들. (구글시트/스트림릿 의존 없음)"""
import re

from utils import config as C

# Tally '문의하시는 이유' 선택지(긴 문장) → 짧은 라벨
REASON_KEYWORDS = [
    ("개원", "신규 개원"),
    ("바꾸려", "마케팅사 변경"),
    ("신규 환자", "신규 환자 유입"),
    ("존재를 모릅", "병원 인지도"),
    ("민원", "민원 후 마케팅 재개"),
]


# ── 연락처 ──────────────────────────────────────────────────────
def phone_digits(phone: str) -> str:
    """숫자만 추출 + 시트가 숫자로 바꾸며 잃어버린 앞자리 0 복원 (1029095406 → 01029095406)."""
    d = re.sub(r"\D", "", phone or "")
    if d and not d.startswith("0"):
        if len(d) == 10 and d.startswith("1"):          # 휴대폰 (010 등)
            d = "0" + d
        elif 8 <= len(d) <= 10 and d[0] in "23456":     # 지역번호
            d = "0" + d
    return d


def normalize_phone(phone: str) -> str:
    d = phone_digits(phone)
    if len(d) == 11:
        return f"{d[:3]}-{d[3:7]}-{d[7:]}"
    if len(d) == 10:
        return f"{d[:2]}-{d[2:6]}-{d[6:]}" if d.startswith("02") else f"{d[:3]}-{d[3:6]}-{d[6:]}"
    if len(d) == 9 and d.startswith("02"):
        return f"{d[:2]}-{d[2:5]}-{d[5:]}"
    return (phone or "").strip()


# ── 지역 / 날짜 / 유입경로 ──────────────────────────────────────
def region_of(addr: str) -> str:
    """'경기도 성남시' → 경기, '서울시 강남구' → 서울, '충청남도 천안시' → 충남"""
    parts = (addr or "").split()
    if not parts:
        return "미상"
    first = parts[0]
    if first in C.REGION_ALIASES:
        return C.REGION_ALIASES[first]
    for r in C.REGIONS:
        if first.startswith(r):
            return r
    return first


def normalize_addr(addr: str) -> str:
    """소재지 표기 통일: 서울=구까지, 광역시=이름만, 도=시·군까지.
    '경기도 성남시 분당구'→'경기도 성남시' / '서울 강남구 역삼동'→'서울시 강남구' / '인천 남동구'→'인천광역시'"""
    parts = (addr or "").split()
    if not parts:
        return ""
    short = region_of(addr)
    if short not in C.REGION_FULL:            # 시·도를 알 수 없으면 입력값 그대로
        return " ".join(parts)
    full = C.REGION_FULL[short]
    rest = parts[1:]
    if short in C.METRO_REGIONS:
        return full
    if short == "서울":
        gu = next((p for p in rest if p.endswith("구")), "")
        return f"{full} {gu}".strip()
    city = next((p for p in rest if p.endswith(("시", "군"))), "")
    return f"{full} {city}".strip()


def to_iso_date(text: str) -> str:
    m = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", text or "")
    return f"{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}" if m else ""


def channel_of(selected: str, etc_text: str):
    """(유입경로, 유입경로_기타) — 'AI 검색'→'AI검색', '기타(직접 입력)'→('기타', 입력값)"""
    sel = (selected or "").strip()
    canon = {c.replace(" ", ""): c for c in C.CHANNELS}
    key = sel.replace(" ", "")
    if key in canon and canon[key] != C.CHANNEL_ETC:
        return canon[key], ""
    if sel.startswith("기타") or not sel:
        return (C.CHANNEL_ETC, (etc_text or "").strip()) if sel else ("", "")
    return C.CHANNEL_ETC, sel        # 목록에 없는 값은 기타로 두고 원문 보존


def reason_label(inner: str) -> str:
    for kw, label in REASON_KEYWORDS:
        if kw in inner:
            return label
    return "기타" if inner.strip() in ("", "기타") else inner.strip()[:20]


# ── raw 헤더 해석 / 행 변환 ─────────────────────────────────────
def parse_headers(headers: list) -> dict:
    h = [re.sub(r"\s+", " ", x or "").strip() for x in headers]

    def find(prefix):
        return next((i for i, x in enumerate(h) if x.startswith(prefix)), None)

    m = {
        "date": find("입력날짜"), "hospital": find("병원명"), "person": find("성함"),
        "phone": find("연락처"), "dept_sel": find("분과를 선택"), "dept_txt": find("분과를 입력"),
        "addr": find("병원 소재지"), "avail": find("상담 가능"), "detail": find("문의 내용"),
        "channel": find("애드리절트를 알게 된 경로"), "channel_txt": find("어떻게 애드리절트를"),
        "reason_combined": None, "reasons": [],
    }
    for i, x in enumerate(h):
        if x.startswith("문의하시는 이유"):
            if x.endswith("(복수응답 가능)"):
                m["reason_combined"] = i
            else:
                inner = x.split("(복수응답 가능)", 1)[-1].strip().strip("()").strip()
                m["reasons"].append((i, inner))
    missing = [name for key, name in (("hospital", "병원명"), ("phone", "연락처")) if m[key] is None]
    if missing:
        raise RuntimeError(f"raw 시트 헤더에서 {', '.join(missing)} 열을 찾을 수 없습니다. 헤더 이름을 확인해주세요.")
    return m


def clean_raw_row(cols: dict, row: list):
    """raw 1행 → master 레코드(dict). 병원명·연락처가 모두 비면 None."""
    def get(idx):
        return row[idx].strip() if idx is not None and idx < len(row) else ""

    hospital, phone_raw = get(cols["hospital"]), get(cols["phone"])
    if not hospital and not phone_raw:
        return None

    submitted = get(cols["date"])
    day = to_iso_date(submitted)

    dept = get(cols["dept_txt"]) if get(cols["dept_sel"]).startswith("기타") else get(cols["dept_sel"])
    dept = dept or get(cols["dept_txt"])

    reasons = []
    for idx, inner in cols["reasons"]:
        v = get(idx)
        if v.upper() == "TRUE":
            reasons.append(reason_label(inner))
        elif v and v.upper() != "FALSE":                # '기타' 칸에 직접 입력한 텍스트
            reasons.append(f"기타({v})")
    if not reasons:
        reasons = [reason_label(x) for x in get(cols["reason_combined"]).split(",") if x.strip()]

    channel, channel_etc = channel_of(get(cols["channel"]), get(cols["channel_txt"]))
    key = (row[0].strip() if row else "") or f"{submitted}|{phone_digits(phone_raw)}"

    return {
        "입력날짜": day, "담당부서": "", "진행상황": C.PRE_CONTACT, "병원명": hospital,
        "병원소재지": normalize_addr(get(cols["addr"])), "분과": dept, "연락처": normalize_phone(phone_raw),
        "담당자": get(cols["person"]), "상담가능날짜": to_iso_date(get(cols["avail"])),
        "문의이유": ", ".join(dict.fromkeys(reasons)),
        "세부문의사항": (row[cols["detail"]].strip() if cols["detail"] is not None and cols["detail"] < len(row) else ""),
        "유입경로": channel, "유입경로_기타": channel_etc, "비고": "",
        "등록경로": "Tally", "원본ID": key,
    }
