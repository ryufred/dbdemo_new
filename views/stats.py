import pandas as pd
import plotly.express as px
import streamlit as st

from utils import auth as A
from utils import config as C
from utils import analytics as AN
from utils import data as D
from utils.clean import region_of

BLUE = ["#0068C9"]


def _fig(fig):
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), xaxis_title=None, height=340)
    st.plotly_chart(fig, width="stretch")


def render():
    st.title("📊 애드리절트 DB 통계 대시보드")
    df = A.scope(D.load_db())

    admin = A.current_user()["role"] == "admin"
    years = sorted({m[:4] for m in df["입력월"] if m}, reverse=True)   # 연도는 한 해에 하나씩만 늘어남
    f1, f2, f3, f4 = st.columns([2, 1.2, 1, 1])
    team = f1.selectbox("애드리절트 담당부서", ["전체"] + ([C.UNASSIGNED] if admin else []) + A.visible_teams())
    unit = f2.selectbox("기간 단위", ["월별", "분기별", "연별"])
    year = f3.selectbox("입력 연도", ["전체"] + years)
    if unit == "분기별":        # 기간 단위에 맞춰 아래 필터도 분기/월로 바뀜
        period = f4.selectbox("입력 분기", ["전체", "Q1", "Q2", "Q3", "Q4"])
    elif unit == "월별":
        period = f4.selectbox("입력 월", ["전체"] + [f"{m:02d}" for m in range(1, 13)])
    else:
        period = "전체"
        f4.selectbox("입력 기간", ["연도로 선택"], disabled=True,
                     help="연별로 볼 때는 왼쪽의 '입력 연도'로 기간을 고르세요.")

    if team == C.UNASSIGNED:
        df = df[df["담당부서"] == ""]
    elif team != "전체":
        df = df[df["담당부서"] == team]
    if year != "전체":
        df = df[df["입력월"].str[:4] == year]
    if period != "전체":
        mm = pd.to_numeric(df["입력월"].str[5:7], errors="coerce")
        df = df[mm.map(lambda m: f"Q{int((m - 1) // 3 + 1)}") == period] if period.startswith("Q") \
            else df[df["입력월"].str[5:7] == period]
    if df.empty:
        st.info("조건에 맞는 DB가 없습니다.")
        return

    total = len(df)
    done = int((df["진행상황"] == C.CONTRACT_DONE).sum())
    pending = int((df["진행상황"] == C.PRE_CONTACT).sum())

    st.divider()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("총 DB", f"{total:,}건")
    k2.metric("계약전환율", f"{done / total * 100:.1f}%", help="계약완료 ÷ 총 DB")
    k3.metric("계약완료 수", f"{done:,}건")
    k4.metric("접촉 전 DB", f"{pending:,}건", help="진행상황이 '접촉 전'인 DB")
    st.divider()

    a, b = st.columns(2, gap="large")
    with a:
        st.subheader("팀별 DB수")
        order = C.TEAMS + ([C.UNASSIGNED] if admin else [])
        g = (df["담당부서"].replace("", C.UNASSIGNED).value_counts()
             .reindex(order, fill_value=0).rename_axis("담당부서").reset_index(name="DB수"))
        _fig(px.bar(g, x="담당부서", y="DB수", text_auto=True, color_discrete_sequence=BLUE))
    with b:
        st.subheader("채널별 효율 (계약전환율)")
        g = df.groupby("유입경로").agg(총=("순번", "count"),
                                        계약=("진행상황", lambda s: (s == C.CONTRACT_DONE).sum()))
        g["계약전환율(%)"] = (g["계약"] / g["총"] * 100).round(1)
        g = g.reset_index().sort_values("계약전환율(%)", ascending=False)
        _fig(px.bar(g, x="유입경로", y="계약전환율(%)", text_auto=True, color_discrete_sequence=BLUE))

    c, d = st.columns(2, gap="large")
    with c:
        st.subheader(f"{unit} DB 추이")
        dt = pd.to_datetime(df["입력날짜"])
        if unit == "연별":
            key = dt.dt.year.astype(str)
        elif unit == "분기별":
            key = dt.dt.to_period("Q").astype(str)
        else:
            key = dt.dt.to_period("M").astype(str)
        g = key.value_counts().sort_index().reset_index()
        g.columns = ["기간", "DB수"]
        _fig(px.line(g, x="기간", y="DB수", markers=True, color_discrete_sequence=BLUE))
    with d:
        st.subheader("진행상황별 분포")
        g = df.groupby("진행상황").size().reindex(C.STATUSES, fill_value=0).reset_index(name="DB수")
        _fig(px.bar(g, x="진행상황", y="DB수", text_auto=True, color_discrete_sequence=BLUE))

    e, f = st.columns(2, gap="large")
    with e:
        st.subheader("지역별 DB수")
        g = df["병원소재지"].map(region_of).value_counts().rename_axis("지역").reset_index(name="DB수")
        _fig(px.bar(g, x="지역", y="DB수", text_auto=True, color_discrete_sequence=BLUE))
    with f:
        st.subheader("분과별 DB수")
        g = df["분과"].replace("", "미상").value_counts().rename_axis("분과").reset_index(name="DB수")
        _fig(px.bar(g, x="분과", y="DB수", text_auto=True, color_discrete_sequence=BLUE))

    with st.expander("🔎 세부 통계 보기 (퍼널 · 응답 속도 · 기간 비교)"):
        _detail_stats(df, A.scope(D.load_db()))

    st.subheader("항목별 계약전환율")
    t = df.assign(지역=df["병원소재지"].map(region_of), 분과=df["분과"].replace("", "미상"),
                  비고=df["비고"].replace("", "(없음)"))
    tab_region, tab_dept, tab_note = st.tabs(["지역별", "분과별", "비고(캠페인)별"])
    for tab, col in ((tab_region, "지역"), (tab_dept, "분과"), (tab_note, "비고")):
        with tab:
            g = t.groupby(col).agg(DB수=("순번", "count"),
                                   계약완료=("진행상황", lambda s: (s == C.CONTRACT_DONE).sum()))
            g["계약전환율(%)"] = (g["계약완료"] / g["DB수"] * 100).round(1)
            st.dataframe(g.sort_values("DB수", ascending=False), width="stretch")


# ══ 세부 통계 ═══════════════════════════════════════════════════
def _detail_stats(df, full_db):
    logs = D.load_logs()
    logs = logs[logs["순번"].isin(set(df["순번"]))]
    t_funnel, t_speed, t_period = st.tabs(["🔻 퍼널", "⏱️ 응답 속도", "📆 기간 비교"])

    with t_funnel:
        _funnel_tab(df, logs)
    with t_speed:
        _speed_tab(df, logs)
    with t_period:
        _period_tab(full_db)


def _funnel_tab(df, logs):
    st.caption(f"단계 순서: {' → '.join(C.FUNNEL_STAGES)} · "
               f"{', '.join(C.FUNNEL_EXCLUDE)} 는 제외 · "
               f"{', '.join(C.SIDE_STATUSES)} 는 단계 후퇴로 보지 않고 한 번 도달한 단계를 유지합니다.")
    f = AN.funnel(df, logs)
    if f["도달"].iloc[0] == 0:
        st.info("계산할 DB가 없습니다.")
        return

    fig = px.funnel(f, x="도달", y="단계", color_discrete_sequence=BLUE)
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=320, yaxis_title=None)
    st.plotly_chart(fig, width="stretch")

    st.dataframe(f, hide_index=True, width="stretch")
    worst = f.iloc[1:]["멈춤 비율(%)"].idxmax() if len(f) > 1 else None
    if worst is not None and f.loc[worst, "여기서 멈춤"]:
        st.caption(f"가장 많이 멈추는 지점: **{f.loc[worst, '단계']}** "
                   f"({f.loc[worst, '여기서 멈춤']}건, {f.loc[worst, '멈춤 비율(%)']}%)")

    st.markdown("**최고 도달 단계별 목록**")
    live = AN.max_stage(df, logs)
    pick = st.selectbox("단계 선택", C.FUNNEL_STAGES, key="funnel_stage_pick")
    sel = live[live["최고단계"] == pick]
    cols = ["순번", "입력날짜", "담당부서", "진행상황", "병원명", "유입경로", "비고"]
    st.dataframe(sel[cols], hide_index=True, width="stretch", height=240)


def _speed_tab(df, logs):
    st.caption("DB가 들어온 날부터 첫 영업로그가 남은 날까지 걸린 시간입니다. "
               "영업로그를 남겨야 집계되니, 통화·상담 후 로그를 남겨주세요.")
    contacted, pending = AN.response_speed(df, logs)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("접촉한 DB", f"{len(contacted):,}건")
    c2.metric("평균 소요", f"{contacted['소요일'].mean():.1f}일" if len(contacted) else "-")
    c3.metric("중앙값", f"{contacted['소요일'].median():.0f}일" if len(contacted) else "-")
    c4.metric("당일 접촉", f"{(contacted['소요일'] == 0).mean() * 100:.0f}%" if len(contacted) else "-")

    b = AN.speed_buckets(contacted)
    if not b.empty:
        _fig(px.bar(b, x="구간", y="건수", text_auto=True, color_discrete_sequence=BLUE))

    st.markdown(f"**아직 접촉 기록이 없는 DB · {len(pending)}건**")
    if pending.empty:
        st.success("모든 DB에 영업로그가 남아 있습니다 🎉")
    else:
        cols = ["순번", "입력날짜", "경과일", "담당부서", "진행상황", "병원명", "연락처"]
        st.dataframe(pending[cols], hide_index=True, width="stretch", height=260)
        st.caption("경과일이 큰 순서입니다. 오래 방치된 DB부터 확인해주세요.")


def _period_tab(full_db):
    months = sorted(full_db["입력월"].unique(), reverse=True)
    if len(months) < 2:
        st.info("비교할 달이 아직 부족합니다. (2개월 이상 데이터 필요)")
        return
    c1, c2 = st.columns(2)
    cur = c1.selectbox("기준 달", months, index=0, key="cmp_cur")
    prev_opts = [m for m in months if m != cur]
    prev = c2.selectbox("비교 달", prev_opts, index=0, key="cmp_prev")

    st.dataframe(AN.compare_months(full_db, cur, prev), hide_index=True, width="stretch")

    st.markdown("**항목별 비교**")
    by = st.radio("기준", ["담당부서", "유입경로", "분과", "비고"], horizontal=True, key="cmp_by")
    st.dataframe(AN.by_group_compare(full_db, cur, prev, by), hide_index=True, width="stretch")
