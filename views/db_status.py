from datetime import date

import streamlit as st

from utils import auth as A
from utils import config as C
from utils import data as D

TABLE_COLS = ["순번", "입력날짜", "담당부서", "진행상황", "병원명", "병원소재지", "분과",
              "연락처", "담당자", "문의이유", "유입경로", "비고"]
KIND_ICON = {"영업": "📝", "이관": "🔀", "배정": "📥", "등록": "🆕", "무효": "🚫"}


def _status_style(val):
    bg = C.STATUS_COLORS.get(str(val).strip())
    return f"background-color: {bg}; color: #1F2A37;" if bg else ""


def _status_badge(val) -> str:
    bg = C.STATUS_COLORS.get(str(val).strip(), "#EDEDED")
    return (f"<span style='background:{bg};padding:3px 10px;border-radius:10px;"
            f"font-size:.85rem;font-weight:700;color:#1F2A37'>{val}</span>")


def _field(col, label, value):
    col.markdown(f"<div class='fieldlabel'>{label}</div>"
                 f"<div class='fieldvalue'>{value or '-'}</div>", unsafe_allow_html=True)


def _note_field(no: str, current: str):
    """비고: 평소엔 값만 보이고, 연필 버튼을 누르면 기존 값이 담긴 입력칸으로 바뀝니다."""
    edit_key = f"note_edit_{no}"
    editing = st.session_state.get(edit_key, False)

    st.markdown("<div class='fieldlabel'>비고 (캠페인·특이사항)</div>", unsafe_allow_html=True)
    if not editing:
        c1, c2 = st.columns([6, 1], vertical_alignment="center")
        c1.markdown(f"<div class='fieldvalue'>{current or '-'}</div>", unsafe_allow_html=True)
        if c2.button("✏️ 수정", key=f"note_edit_btn_{no}", width="stretch"):
            st.session_state[edit_key] = True
            st.session_state[f"note_{no}"] = current   # 기존 값을 채운 채로 열기
            st.rerun()
        return

    c1, c2, c3 = st.columns([5, 1, 1], vertical_alignment="bottom")
    val = c1.text_input("비고", key=f"note_{no}", label_visibility="collapsed",
                        placeholder="예: 브마팀 메타_AI마케팅")
    if c2.button("저장", key=f"note_save_{no}", type="primary", width="stretch"):
        D.update_note(no, val.strip())
        st.session_state[edit_key] = False
        st.toast(f"{no} 비고를 {'저장했습니다' if val.strip() else '지웠습니다'}.", icon="✅")
        st.rerun()
    if c3.button("취소", key=f"note_cancel_{no}", width="stretch"):
        st.session_state[edit_key] = False
        st.rerun()


def _long_text(label, value):
    """긴 문의내용용: 줄바꿈 유지 + 전체 폭 사용"""
    st.markdown(f"<div class='fieldlabel'>{label}</div>", unsafe_allow_html=True)
    st.markdown((value or "-").replace("\n", "  \n"))


def render():
    user = A.current_user()
    st.title("DB 현황 / 영업로그")

    options = (["전체", C.UNASSIGNED] if user["role"] == "admin" else []) + A.visible_teams()
    team = st.radio("팀", options, horizontal=True, key="team_sel")

    db = D.load_db()
    if team == C.UNASSIGNED:
        db = db[db["담당부서"] == ""]
    elif team != "전체":
        db = db[db["담당부서"] == team]

    f1, f2, f3 = st.columns([2, 1, 1])
    statuses = f1.multiselect("진행상황", C.STATUSES, placeholder="전체")
    month = f2.selectbox("입력월", ["전체"] + sorted(db["입력월"].unique(), reverse=True))
    kw = f3.text_input("병원명 · 연락처 검색")

    view = db
    if statuses:
        view = view[view["진행상황"].isin(statuses)]
    if month != "전체":
        view = view[view["입력월"] == month]
    if kw:
        view = view[view["병원명"].str.contains(kw, case=False) | view["연락처"].str.contains(kw)]
    view = D.sort_by_no(view).reset_index(drop=True)

    st.caption(f"{len(view):,}건 · 행을 클릭하면 상세/영업로그가 열립니다")
    shown = view[TABLE_COLS].copy()
    shown["담당부서"] = shown["담당부서"].replace("", C.UNASSIGNED)
    styled = shown.style.map(_status_style, subset=["진행상황"])   # 진행상황 색 구분
    event = st.dataframe(styled, hide_index=True, width="stretch", height=340,
                         on_select="rerun", selection_mode="single-row", key=f"tbl_{team}")
    rows = event.selection.rows
    if not rows:
        st.info("👆 표에서 DB를 선택해주세요.")
        return
    _detail(view.iloc[rows[0]]["순번"], user)


def _detail(no: str, user: dict):
    db = D.load_db()
    rec = db[db["순번"] == no].iloc[0]

    st.divider()
    st.subheader(f"{no} · {rec['병원명']}")
    dups = D.find_similar(rec["연락처"], rec["병원명"], exclude_no=no)
    if not dups.empty:
        with st.expander(f"⚠️ 연락처·병원명이 같은 DB가 {len(dups)}건 더 있습니다", expanded=False):
            st.dataframe(dups[["순번", "입력날짜", "담당부서", "진행상황", "병원명", "연락처"]],
                         hide_index=True, width="stretch")
    left, right = st.columns([3, 2], gap="large")

    # ── 좌: DB 상세 ──
    with left:
        st.markdown(f"<span class='fieldlabel' style='display:inline'>진행상황</span> &nbsp;"
                    f"{_status_badge(rec['진행상황'])}", unsafe_allow_html=True)
        r1 = st.columns(3)
        _field(r1[0], "순번", rec["순번"])
        _field(r1[1], "입력날짜", rec["입력날짜"])
        _field(r1[2], "담당부서", rec["담당부서"] or C.UNASSIGNED)
        r2 = st.columns(3)
        _field(r2[0], "병원명", rec["병원명"])
        _field(r2[1], "병원소재지", rec["병원소재지"])
        _field(r2[2], "분과", rec["분과"])
        r3 = st.columns(3)
        _field(r3[0], "연락처", rec["연락처"])
        _field(r3[1], "담당자", rec["담당자"])
        channel = rec["유입경로"]
        if rec["유입경로_기타"]:
            channel = f"{channel} ({rec['유입경로_기타']})"
        _field(r3[2], "유입경로", channel)
        _note_field(no, rec["비고"])
        r4 = st.columns([2, 1])
        _field(r4[0], "문의이유", rec["문의이유"])
        _field(r4[1], "상담 가능 날짜", rec["상담가능날짜"])
        _long_text("세부문의사항", rec["세부문의사항"])

        st.markdown("&nbsp;")
        label = "이관" if rec["담당부서"] else "배정"
        with st.expander(f"🔀 DB {label}"):
            others = [t for t in C.TEAMS if t != rec["담당부서"]]
            if not rec["담당부서"]:
                others = others + [C.MARK_INVALID]
            to_team = st.selectbox(f"{label}할 팀 / 처리", others, key=f"to_{no}")
            if st.button(f"{label}하기" if to_team != C.MARK_INVALID else "무효 처리하기", key=f"transfer_{no}"):
                if to_team == C.MARK_INVALID:
                    D.mark_invalid_many([no], user["id"])
                    st.toast(f"{no} 무효 처리했습니다.", icon="✅")
                else:
                    D.transfer_db(no, to_team, user["id"])
                    st.toast(f"{no} → {to_team} {label} 완료", icon="✅")
                st.rerun()

    # ── 우: 영업로그 ──
    with right:
        st.markdown("#### 영업로그 작성")
        with st.form(f"log_form_{no}", clear_on_submit=True):
            c1, c2 = st.columns(2)
            log_date = c1.date_input("날짜", value=date.today())
            cur = C.STATUSES.index(rec["진행상황"]) if rec["진행상황"] in C.STATUSES else 0
            status = c2.selectbox("진행상황", C.STATUSES, index=cur)
            content = st.text_area("내용", height=100)
            if st.form_submit_button("로그 저장", type="primary"):
                if not content.strip():
                    st.warning("내용을 입력해주세요.")
                else:
                    D.add_log(no, log_date, status, content.strip(), user["id"])
                    st.toast(f"{no} · {status} 영업로그가 저장되었습니다.", icon="✅")
                    st.rerun()

        st.markdown("#### 진행 히스토리")
        logs = D.load_logs()
        logs = logs[logs["순번"] == no].sort_values(["날짜", "기록시각"], ascending=False)
        if logs.empty:
            st.caption("기록이 없습니다.")
        for _, lg in logs.iterrows():
            with st.container(border=True):
                st.markdown(f"**{lg['날짜']}** · {KIND_ICON.get(lg['유형'], '')} {lg['진행상황']}"
                            f"  \n<small>{lg['작성자']}</small>", unsafe_allow_html=True)
                st.write(lg["내용"])
