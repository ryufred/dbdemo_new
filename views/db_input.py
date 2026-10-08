from datetime import date

import pandas as pd
import streamlit as st

from utils import auth as A
from utils import config as C
from utils import data as D
from utils.clean import normalize_addr


def render():
    st.title("DB 입력")
    tab_one, tab_bulk = st.tabs(["신규 등록", "DB 일괄 등록"])
    with tab_one:
        _single_form()
    with tab_bulk:
        _bulk_import()


# ══ 신규 등록 (한 줄에 항목 하나씩) ═════════════════════════════
def _single_form():
    st.caption("직접 받은 DB를 1건씩 등록합니다. 담당부서는 지정하지 않으며, 등록된 DB는 '미할당'으로 통합 DB에 들어가 "
               "메인 페이지에서 배정합니다.")

    if msg := st.session_state.pop("input_flash", None):
        st.success(msg)

    user = A.current_user()
    ver = st.session_state.setdefault("input_ver", 0)   # 등록 성공 시 올려서 입력칸 초기화
    k = lambda name: f"in_{name}_{ver}"                 # noqa: E731
    form, _ = st.columns([2, 1])                        # 입력칸이 화면 전체로 늘어나지 않도록

    with form:
        in_date = st.date_input("입력날짜", value=date.today(), key=k("date"))
        hospital = st.text_input("병원명 *", key=k("hospital"))

        dept_sel = st.selectbox("분과", C.DEPARTMENTS, index=None, placeholder="선택", key=k("dept"))
        dept_etc = st.text_input("분과 직접입력 *", key=k("dept_etc")) if dept_sel == C.DEPT_ETC else ""

        person = st.text_input("담당자", key=k("person"))
        phone = st.text_input("연락처 *", placeholder="010-0000-0000", key=k("phone"))

        c1, c2 = st.columns([1, 2])
        region = c1.selectbox("병원소재지 (시·도)", C.REGIONS, index=None, placeholder="선택", key=k("region"))
        metro = region in C.METRO_REGIONS               # 광역시는 시·군·구 없이 이름만 저장
        sigungu = c2.text_input("구 (서울) / 시·군 (그 외)", key=k("sigungu"), disabled=metro,
                                help="서울은 구까지, 경기·강원 등 도 지역은 시·군까지, 광역시는 입력하지 않아도 됩니다.")

        channel = st.selectbox("유입경로", C.CHANNELS, key=k("channel"))
        channel_etc = st.text_input("유입경로 직접입력 *", key=k("channel_etc")) \
            if channel == C.CHANNEL_ETC else ""

        notes = D.existing_notes()
        note_pick = st.selectbox("비고 (캠페인·특이사항)", ["(없음)"] + notes + ["+ 새로 입력"],
                                 key=k("note_pick"),
                                 help="예: 브마팀 메타_AI마케팅 — 어떤 광고·캠페인으로 들어왔는지 기록합니다.")
        note = "" if note_pick == "(없음)" else note_pick
        if note_pick == "+ 새로 입력":
            note = st.text_input("비고 직접입력", key=k("note_new"))

        reason = st.multiselect("문의이유 (복수 선택 가능)", C.INQUIRY_REASONS, key=k("reason"))
        detail = st.text_area("세부문의사항", height=140, key=k("detail"))
        avail = st.date_input("상담 가능 날짜", value=None, key=k("avail"))

        st.markdown("")
        allow_dup = st.checkbox("중복이어도 등록", key=k("dup"),
                                help="연락처 또는 병원명이 같은 DB가 이미 있어도 새로 등록합니다.")
        submitted = st.button("등록", type="primary", width="stretch")

    if not submitted:
        return
    if not hospital.strip() or not phone.strip():
        st.warning("병원명과 연락처는 필수입니다.")
        return
    if channel == C.CHANNEL_ETC and not channel_etc.strip():
        st.warning("유입경로 '기타'는 직접 입력해주세요.")
        return
    if dept_sel == C.DEPT_ETC and not dept_etc.strip():
        st.warning("분과 '기타'는 직접 입력해주세요.")
        return
    dup = D.find_similar(phone, hospital)
    if not dup.empty and not allow_dup:
        st.warning(f"⚠️ 연락처 또는 병원명이 같은 DB가 이미 {len(dup)}건 있습니다. "
                   "그래도 등록하려면 '중복이어도 등록'을 체크하세요.")
        st.dataframe(dup[["순번", "입력날짜", "담당부서", "진행상황", "병원명", "연락처"]],
                     hide_index=True, width="stretch")
        return

    no = D.add_db({
        "입력날짜": str(in_date), "담당부서": "", "병원명": hospital.strip(),
        "병원소재지": normalize_addr(f"{region or ''} {sigungu.strip()}"),
        "분과": (dept_etc.strip() if dept_sel == C.DEPT_ETC else (dept_sel or "")),
        "연락처": phone, "담당자": person.strip(), "문의이유": ", ".join(reason),
        "상담가능날짜": str(avail) if avail else "",
        "세부문의사항": detail.strip(), "유입경로": channel, "유입경로_기타": channel_etc.strip(),
        "비고": note.strip(), "등록경로": "수동입력",
    }, author=user["id"])
    st.session_state["input_flash"] = (f"✅ {no} · {hospital.strip()} 등록이 완료되었습니다. "
                                       "메인 페이지에서 담당 팀을 배정해주세요.")
    st.session_state["input_ver"] = ver + 1
    st.rerun()


# ══ DB 일괄 등록 ════════════════════════════════════════════════
def _bulk_import():
    if msg := st.session_state.pop("bulk_flash", None):
        st.success(msg)
    st.caption("엑셀에서 복사한 표를 그대로 붙여넣어 여러 건을 한 번에 등록합니다. "
               "과거 DB, 외부 플랫폼에서 받은 DB 모두 사용할 수 있어요. "
               "순번을 비우면 입력날짜 연도에 맞춰 자동으로 부여됩니다.")
    cols = C.BULK_INPUT_COLS
    ver = st.session_state.setdefault("db_bulk_ver", 0)
    col_config = {
        "담당부서": st.column_config.SelectboxColumn(options=[""] + C.TEAMS),
        "진행상황": st.column_config.SelectboxColumn(options=[""] + C.STATUSES),
        "유입경로": st.column_config.SelectboxColumn(options=[""] + C.CHANNELS),
        "분과": st.column_config.SelectboxColumn(options=[""] + C.DEPARTMENTS),
        "기타": st.column_config.TextColumn(help="캠페인·특이사항 — 비고로 저장됩니다"),
        "순번": st.column_config.TextColumn(help="비워두면 자동 부여 (예: 26-045 처럼 직접 지정도 가능)"),
    }

    st.caption("엑셀에서 여러 행을 복사한 뒤, 표의 첫 칸을 클릭하고 Ctrl+V 하세요. 표가 모자라면 자동으로 늘어납니다.")
    blank = pd.DataFrame([{c: "" for c in cols} for _ in range(10)])
    edited = st.data_editor(blank, hide_index=True, num_rows="dynamic", width="stretch",
                            key=f"db_bulk_editor_{ver}", column_config=col_config)

    c1, c2 = st.columns([1, 3], vertical_alignment="bottom")
    source = c1.text_input("등록경로 표시", value="일괄등록", key=f"db_bulk_src_{ver}",
                           help="외부 플랫폼에서 받은 DB라면 플랫폼 이름을 적어두면 나중에 구분하기 좋아요.")
    if c2.button("붙여넣은 내용 일괄 등록", type="primary", key=f"db_bulk_submit_{ver}"):
        rows = []
        for r in edited.to_dict("records"):
            row = {C.BULK_ALIAS.get(k, k): v for k, v in r.items()}
            row["등록경로"] = source.strip() or "일괄등록"
            rows.append(row)
        n = D.bulk_add_db(rows, A.current_user()["id"])
        if n:
            st.session_state["db_bulk_ver"] = ver + 1
            st.session_state["bulk_flash"] = f"✅ {n}건이 등록되었습니다."
            st.rerun()
        else:
            st.warning("등록할 내용이 없습니다. (병원명이 비어있으면 건너뜁니다)")
