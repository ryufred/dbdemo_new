import pandas as pd
import plotly.express as px
import streamlit as st

from utils import auth as A
from utils import data as D


def render():
    st.title("🎪 특별 DB")
    st.caption("세미나·이벤트처럼 일반 DB와 항목이 다른 DB를 별도로 관리합니다. "
               "이벤트를 만들 때 원하는 컬럼을 직접 정하고, 순번은 이벤트마다 1부터 매겨집니다.")

    events = D.list_events()
    with st.expander("➕ 새 이벤트 만들기", expanded=events.empty):
        _create_event_form()

    if events.empty:
        st.info("아직 만들어진 이벤트가 없습니다. 위에서 먼저 만들어주세요.")
        return

    st.divider()
    label = events["이벤트명"]
    idx = st.selectbox("이벤트 선택", range(len(events)), format_func=lambda i: label.iloc[i])
    _event_view(events.iloc[idx]["이벤트ID"], events.iloc[idx]["이벤트명"])


def _create_event_form():
    ver = st.session_state.setdefault("ev_ver", 0)
    n = st.session_state.setdefault(f"ev_n_{ver}", 3)
    W = [2.2, 1.2, 2.6]

    name = st.text_input("이벤트/세미나 이름 *", placeholder="예: 2026 하반기 개원세미나", key=f"ev_name_{ver}")
    st.caption("스프레드시트를 만든다고 생각하고 컬럼(항목)을 정해주세요. 유형을 '드롭다운'으로 하면 "
               "정해진 선택지 중에서 고르게 됩니다. 컬럼은 나중에도 추가·수정할 수 있어요.")

    h = st.columns(W)
    for c, label in zip(h, ["컬럼명", "유형", "선택지 (쉼표로 구분)"]):
        c.markdown(f"<div class='fieldlabel'>{label}</div>", unsafe_allow_html=True)

    cols = []
    for i in range(n):
        c = st.columns(W, vertical_alignment="center")
        cname = c[0].text_input("컬럼명", key=f"ev_col_{ver}_{i}", label_visibility="collapsed",
                                placeholder="예: 소속병원, 참석자명, 연락처 ...")
        ctype = c[1].selectbox("유형", [D.COL_TEXT, D.COL_SELECT], key=f"ev_type_{ver}_{i}",
                               label_visibility="collapsed")
        opts = c[2].text_input("선택지", key=f"ev_opts_{ver}_{i}", label_visibility="collapsed",
                               placeholder="예: 참석, 불참, 미정" if ctype == D.COL_SELECT else "(텍스트는 비워두세요)",
                               disabled=(ctype != D.COL_SELECT))
        cols.append({"name": cname, "type": ctype, "options": opts.split(",") if opts else []})

    c1, c2 = st.columns([1, 1])
    if c1.button("➕ 컬럼 추가", key=f"ev_addcol_{ver}", width="stretch"):
        st.session_state[f"ev_n_{ver}"] = n + 1
        st.rerun()
    if c2.button("이벤트 만들기", type="primary", key=f"ev_make_{ver}", width="stretch"):
        cleaned = D.norm_schema(cols)
        bad = [c["name"] for c in cleaned if c["type"] == D.COL_SELECT and not c["options"]]
        if not name.strip():
            st.warning("이벤트 이름을 입력해주세요.")
        elif not cleaned:
            st.warning("컬럼을 1개 이상 입력해주세요.")
        elif bad:
            st.warning(f"드롭다운 컬럼의 선택지를 입력해주세요: {', '.join(bad)}")
        else:
            D.create_event(name.strip(), cleaned, A.current_user()["id"])
            st.session_state["ev_ver"] = ver + 1
            st.toast(f"'{name.strip()}' 이벤트가 생성되었습니다.", icon="🎪")
            st.rerun()


def _event_view(eid: str, name: str):
    top1, top2 = st.columns([5, 1], vertical_alignment="center")
    top1.subheader(f"📋 {name}")
    with top2.popover("🗑️ 이벤트 삭제", width="stretch"):
        st.warning(f"'{name}' 이벤트와 등록된 모든 데이터가 삭제됩니다. 되돌릴 수 없어요.")
        if st.button("정말 삭제", type="primary", key=f"del_ev_{eid}"):
            D.delete_event(eid)
            st.toast(f"'{name}' 이벤트가 삭제되었습니다.", icon="🗑️")
            st.rerun()

    df, cols = D.load_event_rows(eid)
    schema = D.event_schema(eid)
    label = ", ".join(f"{c['name']}{' ▾' if c['type'] == D.COL_SELECT else ''}" for c in schema)
    st.caption(f"{len(df)}건 등록 · 컬럼: {label}")

    tab_add, tab_bulk, tab_cols, tab_stats = st.tabs(["항목 등록", "엑셀 일괄 등록", "컬럼 관리", "간단 통계"])

    with tab_add:
        _single_add(eid, schema)
    with tab_bulk:
        _bulk_add(eid, schema)
    with tab_cols:
        _column_manager(eid, schema)
    with tab_stats:
        _simple_stats(df, cols)

    st.divider()
    st.dataframe(df, hide_index=True, width="stretch")


def _single_add(eid, schema):
    with st.form(f"ev_row_{eid}", clear_on_submit=True):
        st.markdown("**새 항목 등록**")
        values = {}
        for c in schema:
            if c["type"] == D.COL_SELECT and c["options"]:
                values[c["name"]] = st.selectbox(c["name"], c["options"], index=None,
                                                 placeholder="선택", key=f"ev_val_{eid}_{c['name']}") or ""
            else:
                values[c["name"]] = st.text_input(c["name"], key=f"ev_val_{eid}_{c['name']}")
        if st.form_submit_button("등록", type="primary"):
            if not any(v.strip() for v in values.values()):
                st.warning("값을 하나 이상 입력해주세요.")
            else:
                D.add_event_row(eid, values, A.current_user()["id"])
                st.toast("1건이 등록되었습니다.", icon="✅")
                st.rerun()


def _bulk_add(eid, schema):
    cols = [c["name"] for c in schema]
    col_config = {c["name"]: st.column_config.SelectboxColumn(options=[""] + c["options"])
                  for c in schema if c["type"] == D.COL_SELECT and c["options"]}
    st.markdown("**엑셀에서 복사한 표를 그대로 붙여넣기**")
    st.caption("엑셀에서 여러 행을 복사한 뒤, 아래 표의 첫 칸을 클릭하고 Ctrl+V(붙여넣기) 하세요. "
               "표가 모자라면 자동으로 행이 늘어납니다.")
    ver = st.session_state.setdefault(f"bulk_ver_{eid}", 0)
    blank = pd.DataFrame([{c: "" for c in cols} for _ in range(8)])
    edited = st.data_editor(blank, hide_index=True, num_rows="dynamic", width="stretch",
                            key=f"bulk_editor_{eid}_{ver}", column_config=col_config)
    if st.button("붙여넣은 내용 일괄 등록", type="primary", key=f"bulk_submit_{eid}_{ver}"):
        n = D.bulk_add_event_rows(eid, edited.to_dict("records"), A.current_user()["id"])
        if n:
            st.session_state[f"bulk_ver_{eid}"] = ver + 1
            st.toast(f"{n}건이 등록되었습니다.", icon="✅")
            st.rerun()
        else:
            st.warning("등록할 내용이 없습니다.")

    st.markdown("**또는 엑셀(.xlsx)/CSV 파일 업로드**")
    up = st.file_uploader("파일 선택", type=["xlsx", "csv"], key=f"bulk_file_{eid}_{ver}")
    if up is not None:
        try:
            raw = pd.read_excel(up, dtype=str) if up.name.endswith("xlsx") else pd.read_csv(up, dtype=str)
        except Exception as e:  # noqa: BLE001
            st.error(f"파일을 읽지 못했습니다: {e}")
            return
        raw = raw.fillna("")
        matched = [c for c in cols if c in raw.columns]
        # 헤더가 이벤트 컬럼과 이름이 같으면 이름으로, 아니면 앞에서부터 순서대로 매칭
        mapped = raw[matched].to_dict("records") if len(matched) >= max(1, len(cols) // 2) else \
            raw.iloc[:, :len(cols)].set_axis(cols[:raw.shape[1]], axis=1).to_dict("records")
        st.caption(f"미리보기 ({len(mapped)}행)")
        st.dataframe(pd.DataFrame(mapped).head(5), hide_index=True, width="stretch")
        if st.button("파일 내용 일괄 등록", type="primary", key=f"bulk_file_submit_{eid}_{ver}"):
            n = D.bulk_add_event_rows(eid, mapped, A.current_user()["id"])
            st.session_state[f"bulk_ver_{eid}"] = ver + 1
            st.toast(f"{n}건이 등록되었습니다.", icon="✅")
            st.rerun()


def _column_manager(eid, schema):
    st.markdown("**컬럼 추가·수정**")
    st.caption("이름을 바꿔도 그 컬럼의 기존 데이터는 그대로 유지됩니다. 유형을 '드롭다운'으로 두면 "
               "선택지에 적은 값 중에서만 고르게 됩니다. 수정 후 반드시 '컬럼 저장'을 눌러주세요.")

    ver = st.session_state.setdefault(f"col_ver_{eid}", 0)
    rows_key = f"colrows_{eid}_{ver}"
    if rows_key not in st.session_state:
        st.session_state[rows_key] = [{**c, "_src": c["name"]} for c in schema]
    rows = st.session_state[rows_key]
    W = [2.2, 1.2, 2.6, 0.5]

    h = st.columns(W)
    for c, label in zip(h, ["컬럼명", "유형", "선택지 (쉼표로 구분)", ""]):
        c.markdown(f"<div class='fieldlabel'>{label}</div>", unsafe_allow_html=True)

    current, delete_idx = [], None
    for i, r in enumerate(rows):
        k = f"cm_{eid}_{ver}_{i}"
        c = st.columns(W, vertical_alignment="center")
        cname = c[0].text_input("컬럼명", value=r.get("name", ""), key=f"{k}_name",
                                label_visibility="collapsed")
        tp = r.get("type", D.COL_TEXT)
        ctype = c[1].selectbox("유형", [D.COL_TEXT, D.COL_SELECT],
                               index=1 if tp == D.COL_SELECT else 0, key=f"{k}_type",
                               label_visibility="collapsed")
        opts = c[2].text_input("선택지", value=", ".join(r.get("options", [])), key=f"{k}_opts",
                               label_visibility="collapsed",
                               placeholder="예: 참석, 불참, 미정" if ctype == D.COL_SELECT else "(텍스트는 비워두세요)",
                               disabled=(ctype != D.COL_SELECT))
        if c[3].button("✕", key=f"{k}_del", help="이 컬럼 삭제"):
            delete_idx = i
        current.append({"name": cname, "type": ctype, "_src": r.get("_src"),
                        "options": [o.strip() for o in opts.split(",") if o.strip()]})

    if delete_idx is not None:   # 다음 ver 의 키에 넣어야 새로 그릴 때 반영됨
        st.session_state[f"colrows_{eid}_{ver + 1}"] = [r for j, r in enumerate(current) if j != delete_idx]
        st.session_state[f"col_ver_{eid}"] = ver + 1
        st.rerun()

    b1, b2 = st.columns([1, 1])
    if b1.button("➕ 컬럼 추가", key=f"col_add_{eid}_{ver}", width="stretch"):
        st.session_state[f"colrows_{eid}_{ver + 1}"] = current + [{"name": "", "type": D.COL_TEXT,
                                                                   "options": [], "_src": None}]
        st.session_state[f"col_ver_{eid}"] = ver + 1
        st.rerun()

    if b2.button("컬럼 저장", type="primary", key=f"col_save_{eid}_{ver}", width="stretch"):
        cleaned = D.norm_schema(current)
        bad = [c["name"] for c in cleaned if c["type"] == D.COL_SELECT and not c["options"]]
        if not cleaned:
            st.warning("컬럼을 1개 이상 남겨주세요.")
        elif bad:
            st.warning(f"드롭다운 컬럼의 선택지를 입력해주세요: {', '.join(bad)}")
        else:
            srcs = [r.get("_src") for r in current if str(r.get("name", "")).strip()]
            D.update_event_columns(eid, cleaned, sources=srcs)
            st.session_state[f"col_ver_{eid}"] = ver + 1
            st.toast("컬럼이 저장되었습니다.", icon="✅")
            st.rerun()


def _simple_stats(df, cols):
    if df.empty:
        st.info("등록된 항목이 없습니다.")
        return
    st.metric("총 등록 건수", f"{len(df):,}건")
    col = st.selectbox("분포를 볼 컬럼", cols, key="ev_stat_col")
    g = df[col].replace("", "(빈 값)").value_counts().rename_axis(col).reset_index(name="건수")
    if len(g) > 30:
        g = g.head(30)
        st.caption("상위 30개만 표시합니다.")
    fig = px.bar(g, x=col, y="건수", text_auto=True, color_discrete_sequence=["#0068C9"])
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), xaxis_title=None, height=340)
    st.plotly_chart(fig, width="stretch")
