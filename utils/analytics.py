"""세부 통계 계산 (퍼널 / 응답 속도 / 기간 비교).
화면 코드와 분리해서, 계산 규칙을 여기서만 고치면 되도록 합니다.
"""
from datetime import date

import pandas as pd

from utils import config as C

STAGE_IDX = {s: i for i, s in enumerate(C.FUNNEL_STAGES)}


def _to_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")


# ══ 1) 퍼널 ════════════════════════════════════════════════════
def max_stage(db: pd.DataFrame, logs: pd.DataFrame) -> pd.DataFrame:
    """DB마다 '최고 도달 단계'를 계산. 지금 상태가 뒤로 밀려도 한 번 갔던 단계는 유지됩니다.
    무효·중복은 제외합니다."""
    live = db[~db["진행상황"].isin(C.FUNNEL_EXCLUDE)].copy()
    if live.empty:
        return live.assign(최고단계="", 최고단계idx=pd.Series(dtype=int))

    reached = {no: STAGE_IDX.get(st, 0) for no, st in zip(live["순번"], live["진행상황"])}
    lg = logs[logs["순번"].isin(set(live["순번"]))]
    for no, st in zip(lg["순번"], lg["진행상황"]):
        if st in STAGE_IDX:
            reached[no] = max(reached.get(no, 0), STAGE_IDX[st])

    live["최고단계idx"] = live["순번"].map(reached).fillna(0).astype(int)
    live["최고단계"] = live["최고단계idx"].map(lambda i: C.FUNNEL_STAGES[i])
    return live


def funnel(db: pd.DataFrame, logs: pd.DataFrame) -> pd.DataFrame:
    """단계별 도달 수·도달률과, 그 단계에서 멈춘(이탈) 수·비율."""
    live = max_stage(db, logs)
    total = len(live)
    rows = []
    for i, stage in enumerate(C.FUNNEL_STAGES):
        reached_n = int((live["최고단계idx"] >= i).sum()) if total else 0
        stopped_n = int((live["최고단계idx"] == i).sum()) if total else 0
        prev = rows[-1]["도달"] if rows else None
        rows.append({
            "단계": stage,
            "도달": reached_n,
            "도달률(%)": round(reached_n / total * 100, 1) if total else 0.0,
            "직전 단계 대비(%)": round(reached_n / prev * 100, 1) if prev else 100.0,
            "여기서 멈춤": stopped_n,
            "멈춤 비율(%)": round(stopped_n / total * 100, 1) if total else 0.0,
        })
    return pd.DataFrame(rows)


# ══ 2) 응답 속도 ═══════════════════════════════════════════════
def response_speed(db: pd.DataFrame, logs: pd.DataFrame):
    """DB 접수일 → 첫 영업로그까지 걸린 일수. (contacted, pending) 반환."""
    sales = logs[logs["유형"] == "영업"].copy()
    sales["날짜"] = _to_date(sales["날짜"])
    first = sales.groupby("순번")["날짜"].min().rename("첫접촉일")

    d = db.copy()
    d["입력일"] = _to_date(d["입력날짜"])
    d = d.join(first, on="순번")

    contacted = d[d["첫접촉일"].notna()].copy()
    contacted["소요일"] = (contacted["첫접촉일"] - contacted["입력일"]).dt.days.clip(lower=0)

    pending = d[d["첫접촉일"].isna() & ~d["진행상황"].isin(C.FUNNEL_EXCLUDE)].copy()
    pending["경과일"] = (pd.Timestamp(date.today()) - pending["입력일"]).dt.days
    return contacted, pending.sort_values("경과일", ascending=False)


def speed_buckets(contacted: pd.DataFrame) -> pd.DataFrame:
    if contacted.empty:
        return pd.DataFrame(columns=["구간", "건수"])
    bins = [-1, 0, 1, 3, 7, 14, 10**6]
    labels = ["당일", "1일", "2~3일", "4~7일", "8~14일", "15일 이상"]
    cut = pd.cut(contacted["소요일"], bins=bins, labels=labels)
    g = cut.value_counts().reindex(labels, fill_value=0)
    return g.rename_axis("구간").reset_index(name="건수")


# ══ 3) 기간 비교 ═══════════════════════════════════════════════
def month_summary(db: pd.DataFrame, month: str) -> dict:
    sub = db[db["입력월"] == month]
    total = len(sub)
    done = int((sub["진행상황"] == C.CONTRACT_DONE).sum())
    invalid = int(sub["진행상황"].isin(C.FUNNEL_EXCLUDE).sum())
    return {"월": month, "총 DB": total, "계약완료": done,
            "계약전환율(%)": round(done / total * 100, 1) if total else 0.0,
            "무효·중복": invalid}


def compare_months(db: pd.DataFrame, cur: str, prev: str) -> pd.DataFrame:
    a, b = month_summary(db, cur), month_summary(db, prev)
    rows = []
    for key in ["총 DB", "계약완료", "계약전환율(%)", "무효·중복"]:
        pct = key.endswith("(%)")
        fmt = (lambda v: f"{v:g}%") if pct else (lambda v: f"{int(v):,}건")
        diff = round(a[key] - b[key], 1)
        rows.append({"항목": key, cur: fmt(a[key]), prev: fmt(b[key]),
                     "증감": f"{diff:+g}{'%p' if pct else '건'}"})
    return pd.DataFrame(rows)


def by_group_compare(db: pd.DataFrame, cur: str, prev: str, col: str) -> pd.DataFrame:
    """팀별·유입경로별 등으로 두 기간의 DB수를 비교."""
    a = db[db["입력월"] == cur][col].replace("", C.UNASSIGNED).value_counts()
    b = db[db["입력월"] == prev][col].replace("", C.UNASSIGNED).value_counts()
    idx = sorted(set(a.index) | set(b.index))
    out = pd.DataFrame({col: idx,
                        cur: [int(a.get(i, 0)) for i in idx],
                        prev: [int(b.get(i, 0)) for i in idx]})
    out["증감"] = (out[cur] - out[prev]).map(lambda v: f"{v:+d}")
    return out.sort_values(cur, ascending=False)
