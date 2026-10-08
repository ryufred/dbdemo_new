from datetime import date

import streamlit as st

from utils import auth as A
from utils import config as C
from utils import data as D


def _sync_raw(show_result: bool):
    """Tally raw → DB마스터 가져오기 (구글시트 연결 시에만)."""
    try:
        n = D.import_from_raw()
    except Exception as e:  # noqa: BLE001
        st.warning(f"Tally 새 DB를 불러오지 못했습니다: {e}")
        return
    if n:
        st.session_state["main_flash"] = f"✅ Tally 새 DB {n}건을 불러왔습니다."
    elif show_result:
        st.toast("새로 들어온 DB가 없습니다.")


def render():
    is_admin = A.current_user()["role"] == "admin"
    if msg := st.session_state.pop("main_flash", None):
        st.success(msg)
    t1, t2 = st.columns([4, 1], vertical_alignment="center")
    t1.title("📊 " + C.APP_TITLE)
    if is_admin and D.raw_enabled():
        clicked = t2.button("🔄 새 DB 불러오기", width="stretch")
        if clicked or "raw_synced" not in st.session_state:   # 로그인 후 첫 진입 시 자동 1회 + 버튼
            st.session_state["raw_synced"] = True
            _sync_raw(show_result=clicked)
    elif is_admin:
        t2.caption(D.backend_name())

    df = A.scope(D.load_db())
    today = date.today()

    unassigned = df[(df["담당부서"] == "") & (df["진행상황"] != C.INVALID_STATUS)]  # 배정 대기 (무효 제외)
    assigned = df[df["담당부서"] != ""]
    pending = assigned[assigned["진행상황"] == C.PRE_CONTACT]  # 배정된 DB 중 접촉 전
    year_df = df[df["입력날짜"].str.startswith(str(today.year))]
    month_df = df[df["입력월"] == f"{today:%Y-%m}"]

    cols = st.columns(4 if is_admin else 3)
    cols[0].metric(f"{today.year}년 총 DB", f"{len(year_df):,}건")
    cols[1].metric(f"{today.month}월 DB", f"{len(month_df):,}건")
    if is_admin:
        cols[2].metric("미할당 DB", f"{len(unassigned):,}건", help="아직 담당 팀이 정해지지 않은 DB")
    cols[-1].metric("접촉 전 DB", f"{len(pending):,}건",
                    help="팀 배정이 끝난 DB 중 진행상황이 '접촉 전'인 DB")

    if is_admin:
        st.divider()
        _assign_section(unassigned)
        _duplicate_section()

    st.divider()
    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("팀별 접촉 전 DB")
        by_team = (pending.groupby("담당부서").size()
                   .reindex(A.visible_teams(), fill_value=0).reset_index(name="건수"))
        st.dataframe(by_team, hide_index=True, width="stretch")
    with right:
        st.subheader("최근 등록 DB")
        recent = D.sort_by_no(df).head(8).copy()
        recent["담당부서"] = recent["담당부서"].replace("", C.UNASSIGNED)
        st.dataframe(recent[["순번", "입력날짜", "담당부서", "병원명", "진행상황"]],
                     hide_index=True, width="stretch")

    st.subheader("접촉 전 DB 목록")
    if pending.empty:
        st.success("접촉 전 DB가 없습니다 🎉")
    else:
        show = ["순번", "입력날짜", "담당부서", "진행상황", "병원명", "병원소재지", "분과", "연락처",
                "담당자", "유입경로", "비고"]
        styled = pending.sort_values("입력날짜")[show].style.map(
            lambda v: (f"background-color: {C.STATUS_COLORS.get(str(v).strip(), '')}"
                       if C.STATUS_COLORS.get(str(v).strip()) else ""), subset=["진행상황"])
        st.dataframe(styled, hide_index=True, width="stretch")
        st.caption("오래된 순으로 정렬 · 처리는 'DB현황 / 영업로그' 페이지에서 하세요.")


def _duplicate_section():
    dups = D.duplicate_groups()
    if dups.empty:
        return
    st.subheader(f"⚠️ 중복 의심 DB ({len(dups)}건)")
    st.caption("연락처 또는 병원명이 같은 DB입니다. 확인 후 한쪽을 '중복' 또는 '무효'로 정리해주세요.")
    show = ["순번", "중복사유", "입력날짜", "담당부서", "진행상황", "병원명", "연락처", "유입경로", "비고"]
    st.dataframe(dups.sort_values(["병원명", "순번"])[show], hide_index=True, width="stretch",
                 height=220)


def _assign_section(unassigned):
    st.subheader("📥 미할당 DB · 담당 팀 배정")
    if unassigned.empty:
        st.success("배정 대기 중인 DB가 없습니다 ✅")
        return

    ver = st.session_state.setdefault("assign_ver", 0)   # 배정 후 선택 상태 초기화용
    view = D.sort_by_no(unassigned, ascending=True).reset_index(drop=True)
    show = ["순번", "입력날짜", "병원명", "병원소재지", "분과", "연락처", "담당자", "문의이유", "유입경로"]
    st.caption("배정할 DB를 체크(여러 개 가능)한 뒤 팀을 고르거나, 이상한 DB는 '무효 처리'를 선택하세요.")
    event = st.dataframe(view[show], hide_index=True, width="stretch", height=280,
                         on_select="rerun", selection_mode="multi-row", key=f"un_tbl_{ver}")
    rows = event.selection.rows
    c1, c2, _ = st.columns([1, 1, 2], vertical_alignment="bottom")
    choice = c1.selectbox("배정할 팀 / 처리", C.TEAMS + [C.MARK_INVALID], key=f"un_team_{ver}")
    is_invalid = choice == C.MARK_INVALID
    btn_label = f"선택 {len(rows)}건 무효 처리" if is_invalid else f"선택 {len(rows)}건 배정"
    if c2.button(btn_label, type="primary" if not is_invalid else "secondary",
                disabled=not rows, width="stretch"):
        nos = [view.iloc[i]["순번"] for i in rows]
        if is_invalid:
            n = D.mark_invalid_many(nos, A.current_user()["id"])
            st.session_state["main_flash"] = f"✅ {n}건을 무효 처리했습니다."
        else:
            D.assign_many(nos, choice, A.current_user()["id"])
            st.session_state["main_flash"] = f"✅ {len(nos)}건이 {choice}에 배정되었습니다."
        st.session_state["assign_ver"] = ver + 1
        st.rerun()
