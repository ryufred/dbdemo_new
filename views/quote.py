import json
import re
import tempfile
import uuid
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from utils import auth as A
from utils import config as C
from utils import data as D
from utils import quote as Q

BLANK_ITEM = {c: "" for c in C.QUOTE_ITEM_COLS}


def _numeric(df: pd.DataFrame) -> pd.DataFrame:
    """단가·할인값을 숫자형으로 맞춰야 천단위 쉼표 표시가 적용됩니다."""
    out = df.copy()
    for c in C.QUOTE_ITEM_COLS:
        if c not in out.columns:
            out[c] = "" if c not in ("단가", "할인값") else 0
    for c in ("단가", "할인값"):
        out[c] = pd.to_numeric(out[c].astype(str).str.replace(r"[^0-9.\-]", "", regex=True),
                               errors="coerce").fillna(0)
    out["할인유형"] = out["할인유형"].replace("", "없음").fillna("없음")
    return out[C.QUOTE_ITEM_COLS]


def render():
    st.title("🧾 견적서 제작")
    st.caption("카탈로그에서 항목을 체크해 담으면 가격이 자동으로 반영돼요. 이후 내용은 자유롭게 수정할 수 있고, "
               "엑셀(.xlsx)과 PDF로 내려받을 수 있어요.")

    tab_make, tab_history = st.tabs(["새 견적 만들기", "이전 견적"])
    with tab_make:
        _info_form()
        st.divider()
        _catalog_section()
        st.divider()
        _quote_items_section()
        st.divider()
        _totals_and_export()
    with tab_history:
        _history_section()


def _k(name):
    return f"q_{name}"


def _info_form():
    st.subheader("📋 견적 정보")
    c1, c2, c3 = st.columns(3)
    c1.text_input("병원명 *", key=_k("hospital"))
    c2.text_input("받는 분", value="원장님", key=_k("recipient"))
    c3.date_input("견적일자", value=date.today(), key=_k("date"))

    c1, c2, c3 = st.columns(3)
    default_no = f"a{st.session_state[_k('date')]:%Y%m%d}-1"
    c1.text_input("견적번호", value=st.session_state.get(_k("no"), default_no), key=_k("no"))
    c2.text_input("견적유효기간", value="견적으로부터 1개월", key=_k("valid"))
    c3.text_input("참조", key=_k("ref"))

    c1, c2, c3 = st.columns(3)
    c1.text_input("부서", value="마케팅 기획팀", key=_k("dept"))
    c2.text_input("담당자", key=_k("person"))
    c3.text_input("직책", key=_k("title"))

    c1, c2 = st.columns(2)
    c1.text_input("전화번호 (담당자)", key=_k("tel"))
    c2.text_input("전화 (고객 측 연락처, 선택)", key=_k("client_tel"))


def _catalog_section():
    st.subheader("🛒 카탈로그에서 담기")
    with st.expander("⚙️ 카탈로그 관리 (상품·가격 추가/수정)"):
        cat_ver = st.session_state.setdefault("cat_ver", 0)
        cat = D.load_catalog()
        cat["단가"] = pd.to_numeric(cat["단가"], errors="coerce").fillna(0)
        edited_cat = st.data_editor(cat, hide_index=True, num_rows="dynamic", width="stretch",
                                    key=f"cat_editor_{cat_ver}",
                                    column_config={"단가": st.column_config.NumberColumn(
                                        format="%,d", min_value=0, step=10000)})
        if st.button("카탈로그 저장", type="primary", key=f"cat_save_{cat_ver}"):
            D.save_catalog(edited_cat)
            st.session_state["cat_ver"] = cat_ver + 1
            st.toast("카탈로그가 저장되었습니다.", icon="✅")
            st.rerun()

    catalog = D.load_catalog()
    catalog["단가"] = pd.to_numeric(catalog["단가"], errors="coerce").fillna(0)
    st.caption("담을 항목을 체크(여러 개 가능)한 뒤 아래 버튼을 누르세요. 항목별 할인은 담은 뒤 아래 표에서 정할 수 있어요.")
    event = st.dataframe(catalog, hide_index=True, width="stretch", height=280,
                         on_select="rerun", selection_mode="multi-row", key="cat_select",
                         column_config={"단가": st.column_config.NumberColumn(format="%,d")})
    rows = event.selection.rows
    if st.button(f"선택 {len(rows)}건 견적에 담기", type="primary", disabled=not rows, width="stretch"):
        picked = catalog.iloc[rows][C.QUOTE_ITEM_COLS[:5]].copy()
        picked["할인유형"], picked["할인값"] = "없음", 0
        cur = st.session_state.get("quote_items_df", pd.DataFrame(columns=C.QUOTE_ITEM_COLS))
        st.session_state["quote_items_df"] = _numeric(pd.concat([cur, picked], ignore_index=True))
        st.session_state["item_ver"] = st.session_state.get("item_ver", 0) + 1
        st.toast(f"{len(rows)}건을 견적에 담았습니다.", icon="🛒")
        st.rerun()


def _qty_num(text):
    """'10건 / 1개월' → 10 (앞쪽 첫 숫자). 숫자가 없으면 None."""
    m = re.search(r"\d+(?:\.\d+)?", str(text or ""))
    return float(m.group()) if m else None


def _qty_changed_cb(k: str):
    """수량을 바꾸면 기준(수량·단가) 비율대로 단가를 다시 계산해 넣습니다."""
    base = st.session_state.get(f"{k}_base")
    new_qty = _qty_num(st.session_state.get(f"{k}_qty"))
    if not base or not new_qty:
        return
    base_qty, base_price = base
    if not base_qty:
        return
    st.session_state[f"{k}_price"] = f"{round(base_price / base_qty * new_qty):,}"


def _price_changed_cb(k: str):
    """단가를 직접 고치면 그 값을 현재 수량 기준으로 다시 잡습니다."""
    _fmt_money_cb(f"{k}_price")
    digits = re.sub(r"[^0-9]", "", str(st.session_state.get(f"{k}_price", "")))
    qty = _qty_num(st.session_state.get(f"{k}_qty"))
    if digits and qty:
        st.session_state[f"{k}_base"] = (qty, int(digits))


def _fmt_money_cb(key: str):
    """입력한 숫자를 천단위 쉼표로 다시 써 줍니다 (위젯 콜백이라 세션 값 수정이 허용됨)."""
    digits = re.sub(r"[^0-9]", "", str(st.session_state.get(key, "")))
    st.session_state[key] = f"{int(digits):,}" if digits else ""


def _money_input(col, value, key, *, disabled=False, on_change=None, cb_arg=None):
    """천단위 쉼표가 보이는 금액 입력칸. 반환값은 정수."""
    if key not in st.session_state:
        st.session_state[key] = f"{int(value):,}" if value else ""
    col.text_input("금액", key=key, label_visibility="collapsed", disabled=disabled,
                   placeholder="0", on_change=on_change or _fmt_money_cb,
                   args=(cb_arg,) if on_change else (key,))
    digits = re.sub(r"[^0-9]", "", str(st.session_state.get(key, "")))
    return int(digits) if digits else 0


def _quote_items_section():
    st.subheader("📝 이번 견적 항목")
    df = _numeric(st.session_state.get("quote_items_df", pd.DataFrame(columns=C.QUOTE_ITEM_COLS)))
    if df.empty:
        st.info("위 카탈로그에서 항목을 담거나, 아래 '빈 항목 추가'로 직접 넣어주세요.")
        if st.button("➕ 빈 항목 추가", key="item_add_empty"):
            _add_blank_item()
        return

    st.caption("각 칸을 한 번만 클릭하면 바로 고칠 수 있어요. 수량을 바꾸면 단가가 비율대로 자동 계산되고, "
               "↑↓ 로 순서를 바꾸면 견적서에도 그 순서로 나옵니다.")
    ver = st.session_state.setdefault("item_ver", 0)
    records = df.to_dict("records")
    updated, delete_idx, move = [], None, None
    WIDTHS = [2.3, 2.1, 1.4, 1.35, 1.15, 1.35, 0.4, 0.4, 0.45]
    last = len(records) - 1

    h = st.columns(WIDTHS)
    for c, label in zip(h, ["상품", "상세", "수량/기간", "단가", "할인유형", "할인값", "", "순서", ""]):
        c.markdown(f"<div class='fieldlabel'>{label}</div>", unsafe_allow_html=True)

    for i, rec in enumerate(records):
        k = f"it_{ver}_{i}"
        c = st.columns(WIDTHS, vertical_alignment="top")

        prod = c[0].text_input("상품", value=str(rec.get("상품", "")), key=f"{k}_prod",
                               label_visibility="collapsed")
        desc = c[1].text_input("상세", value=str(rec.get("상세", "")), key=f"{k}_desc",
                               label_visibility="collapsed")
        if f"{k}_base" not in st.session_state:        # 카탈로그 기준 수량·단가를 기억
            bq = _qty_num(rec.get("수량기간", ""))
            st.session_state[f"{k}_base"] = (bq, int(rec.get("단가", 0) or 0)) if bq else None
        qty = c[2].text_input("수량기간", value=str(rec.get("수량기간", "")), key=f"{k}_qty",
                              label_visibility="collapsed", on_change=_qty_changed_cb, args=(k,))
        price = _money_input(c[3], rec.get("단가", 0), f"{k}_price",
                             on_change=_price_changed_cb, cb_arg=k)

        dtype = rec.get("할인유형", "없음") or "없음"
        dtype = c[4].selectbox("할인유형", C.DISCOUNT_TYPES,
                               index=C.DISCOUNT_TYPES.index(dtype) if dtype in C.DISCOUNT_TYPES else 0,
                               key=f"{k}_dtype", label_visibility="collapsed")
        no_disc = dtype == "없음"
        dval = _money_input(c[5], rec.get("할인값", 0), f"{k}_dval", disabled=no_disc)
        if no_disc:
            dval = 0
        if c[6].button("↑", key=f"{k}_up", help="위로 이동", disabled=(i == 0)):
            move = (i, i - 1)
        if c[7].button("↓", key=f"{k}_down", help="아래로 이동", disabled=(i == last)):
            move = (i, i + 1)
        if c[8].button("✕", key=f"{k}_del", help="이 항목 삭제"):
            delete_idx = i

        row = {"채널": rec.get("채널", ""), "상품": prod, "상세": desc, "수량기간": qty,
               "단가": price, "할인유형": dtype, "할인값": dval}
        c[5].markdown(  # 입력칸 바로 아랫줄에 제안가 표시
            f"<div style='color:#C4314B;font-weight:700;font-size:.85rem;margin:-6px 0 14px'>"
            f"제안가 {Q.line_final(row):,.0f}원</div>", unsafe_allow_html=True)
        updated.append(row)

    st.session_state["quote_items_df"] = pd.DataFrame(updated, columns=C.QUOTE_ITEM_COLS)

    if move is not None:
        a, b = move
        updated[a], updated[b] = updated[b], updated[a]
        st.session_state["quote_items_df"] = pd.DataFrame(updated, columns=C.QUOTE_ITEM_COLS)
        st.session_state["item_ver"] = ver + 1     # 위젯 키를 새로 만들어 바뀐 순서를 반영
        st.rerun()

    if delete_idx is not None:
        rest = [r for j, r in enumerate(updated) if j != delete_idx]
        st.session_state["quote_items_df"] = pd.DataFrame(rest, columns=C.QUOTE_ITEM_COLS)
        st.session_state["item_ver"] = ver + 1
        st.rerun()

    b1, b2 = st.columns([1, 4])
    if b1.button("➕ 빈 항목 추가", key=f"item_add_{ver}"):
        _add_blank_item()


def _add_blank_item():
    cur = _numeric(st.session_state.get("quote_items_df", pd.DataFrame(columns=C.QUOTE_ITEM_COLS)))
    blank = pd.DataFrame([{"채널": "", "상품": "", "상세": "", "수량기간": "",
                           "단가": 0, "할인유형": "없음", "할인값": 0}])
    st.session_state["quote_items_df"] = pd.concat([cur, blank], ignore_index=True)[C.QUOTE_ITEM_COLS]
    st.session_state["item_ver"] = st.session_state.get("item_ver", 0) + 1
    st.rerun()


def _totals_and_export():
    items_df = st.session_state.get("quote_items_df", pd.DataFrame(columns=C.QUOTE_ITEM_COLS))
    items = [r for r in items_df.to_dict("records") if str(r.get("상품", "")).strip()]

    st.subheader("💰 합계")
    c1, c2 = st.columns([1, 1])
    overall_type = c1.selectbox("전체 할인 유형", C.DISCOUNT_TYPES, key=_k("disc_type"))
    overall_value = c2.number_input("전체 할인 값" + (" (%)" if overall_type == "%" else " (원)"),
                                    min_value=0, value=0, step=1, format="%d",
                                    key=_k("disc_val"), disabled=(overall_type == "없음"))

    totals = Q.calc_totals(items, overall_type, overall_value)
    m1, m2, m3 = st.columns(3)
    m1.metric("상품 정상가 합계", f"{totals['list_total']:,.0f}원")
    m2.metric("상품별 할인 합계", f"-{totals['item_discount_total']:,.0f}원")
    m3.metric("소계 (상품 할인 반영)", f"{totals['after_item']:,.0f}원")
    m4, m5, m6 = st.columns(3)
    m4.metric("전체 할인", f"-{totals['overall_amount']:,.0f}원")
    m5.metric("부가세(10%)", f"{totals['vat']:,.0f}원")
    m6.metric("최종 합계(VAT 포함)", f"{totals['final']:,.0f}원")

    st.divider()
    hospital = st.session_state.get(_k("hospital"), "").strip()
    if not hospital:
        st.info("견적 정보에 병원명을 입력하면 다운로드할 수 있어요.")
        return
    if not items:
        st.info("견적 항목을 1건 이상 담아주세요.")
        return

    header = {
        "병원명": hospital, "받는분": st.session_state.get(_k("recipient"), ""),
        "견적번호": st.session_state.get(_k("no"), ""), "부서": st.session_state.get(_k("dept"), ""),
        "담당자": st.session_state.get(_k("person"), ""), "직책": st.session_state.get(_k("title"), ""),
        "전화번호": st.session_state.get(_k("tel"), ""), "견적일자": str(st.session_state.get(_k("date"), "")),
        "유효기간": st.session_state.get(_k("valid"), ""), "참조": st.session_state.get(_k("ref"), ""),
        "전화": st.session_state.get(_k("client_tel"), ""),
    }

    st.subheader("👁️ 견적서 미리보기")
    st.caption("아래 모양 그대로 엑셀·PDF로 저장됩니다. 위에서 내용을 고치면 미리보기도 바로 바뀝니다.")
    _preview(header, items, overall_type, overall_value, "new")

    st.divider()
    c1, c2 = st.columns(2)
    if c1.button("📥 XLSX 만들기", width="stretch"):
        _generate(header, items, overall_type, overall_value, totals["final"], "xlsx")
    if c2.button("📥 PDF 만들기", width="stretch"):
        _generate(header, items, overall_type, overall_value, totals["final"], "pdf")

    ready = st.session_state.get("quote_file")
    if ready and ready["hospital"] == hospital:
        st.download_button(f"⬇️ {ready['name']} 다운로드", data=ready["bytes"], file_name=ready["name"],
                           mime=ready["mime"], type="primary", width="stretch")
    st.caption("만들 때마다 '이전 견적' 탭에 자동으로 저장돼요. 같은 견적번호로 다시 만들면 이전 내용을 덮어써요.")


def _preview(header, items, overall_type, overall_value, key: str):
    """인쇄 미리보기 — 다운로드하지 않고 완성된 견적서 모양을 그대로 봅니다."""
    try:
        html = Q.build_quote_html(header, items, overall_type, overall_value)
    except Exception as e:  # noqa: BLE001
        st.warning(f"미리보기를 만들 수 없습니다: {e}")
        return
    with st.container(height=820, border=False):
        st.html(html)


def _generate(header, items, overall_type, overall_value, final_amount, kind):
    try:
        with tempfile.TemporaryDirectory() as tmp:
            safe_name = "".join(ch for ch in header["병원명"] if ch not in '\\/:*?"<>|')
            today = header["견적일자"].replace("-", "")
            if kind == "xlsx":
                xlsx_path = str(Path(tmp) / f"{uuid.uuid4().hex[:6]}.xlsx")
                Q.build_quote_xlsx(xlsx_path, header, items, overall_type, overall_value)
                data, name, mime = Path(xlsx_path).read_bytes(), f"{safe_name}_견적서_{today}.xlsx", \
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            else:
                pdf_path = str(Path(tmp) / "견적서.pdf")
                Q.build_quote_pdf(pdf_path, header, items, overall_type, overall_value)
                data, name, mime = Path(pdf_path).read_bytes(), f"{safe_name}_견적서_{today}.pdf", "application/pdf"
        D.save_quote(header, items, overall_type, overall_value, final_amount, A.current_user()["id"])
        st.session_state["quote_file"] = {"bytes": data, "name": name, "mime": mime, "hospital": header["병원명"]}
        st.toast(f"{name} 생성 완료! 아래 버튼으로 받아주세요.", icon="📄")
        st.rerun()
    except Exception as e:  # noqa: BLE001
        st.error(f"만드는 중 문제가 생겼습니다: {e}")


def _history_section():
    st.subheader("🗂️ 이전에 만든 견적")
    quotes = D.list_quotes()
    if quotes.empty:
        st.info("아직 만든 견적이 없습니다.")
        return
    quotes = quotes.assign(_final=pd.to_numeric(quotes["최종합계"], errors="coerce")) \
        .sort_values("생성일시", ascending=False).reset_index(drop=True)
    show = quotes[["병원명", "견적번호", "견적일자", "담당자", "항목수", "최종합계", "생성일시"]]
    event = st.dataframe(show, hide_index=True, width="stretch", height=280,
                         on_select="rerun", selection_mode="single-row", key="hist_select")
    rows = event.selection.rows
    if not rows:
        st.caption("👆 표에서 견적을 선택하면 다시 내려받거나 불러올 수 있어요.")
        return

    row = quotes.iloc[rows[0]]
    data = json.loads(row["데이터"])
    header, items = data["header"], data["items"]
    overall_type, overall_value = data.get("overall_type", "없음"), data.get("overall_value", 0)

    st.markdown(f"**{header['병원명']}** · {header.get('견적번호','')} · {row['생성일시']}")
    c1, c2, c3 = st.columns(3)
    if c1.button("📥 XLSX 다시 받기", key=f"hist_xlsx_{row['견적ID']}", width="stretch"):
        _redownload(row["견적ID"], header, items, overall_type, overall_value, "xlsx")
    if c2.button("📥 PDF 다시 받기", key=f"hist_pdf_{row['견적ID']}", width="stretch"):
        _redownload(row["견적ID"], header, items, overall_type, overall_value, "pdf")
    if c3.button("✏️ 불러와서 수정", key=f"hist_load_{row['견적ID']}", width="stretch"):
        _load_into_editor(header, items)

    with st.expander("👁️ 미리보기", expanded=False):
        _preview(header, items, overall_type, overall_value, f"hist_{row['견적ID']}")

    with st.popover("🗑️ 이 견적 삭제"):
        st.warning("삭제하면 되돌릴 수 없어요.")
        if st.button("정말 삭제", key=f"hist_del_{row['견적ID']}"):
            D.delete_quote(row["견적ID"])
            st.toast("견적이 삭제되었습니다.", icon="🗑️")
            st.rerun()

    ready = st.session_state.get("history_file")
    if ready and ready["qid"] == row["견적ID"]:
        st.download_button(f"⬇️ {ready['name']} 다운로드", data=ready["bytes"], file_name=ready["name"],
                           mime=ready["mime"], type="primary", width="stretch", key=f"hist_dl_{row['견적ID']}")


def _redownload(qid, header, items, overall_type, overall_value, kind):
    try:
        with tempfile.TemporaryDirectory() as tmp:
            safe_name = "".join(ch for ch in header["병원명"] if ch not in '\\/:*?"<>|')
            today = header["견적일자"].replace("-", "")
            if kind == "xlsx":
                path = str(Path(tmp) / "q.xlsx")
                Q.build_quote_xlsx(path, header, items, overall_type, overall_value)
                mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                name = f"{safe_name}_견적서_{today}.xlsx"
            else:
                path = str(Path(tmp) / "q.pdf")
                Q.build_quote_pdf(path, header, items, overall_type, overall_value)
                mime, name = "application/pdf", f"{safe_name}_견적서_{today}.pdf"
            data = Path(path).read_bytes()
        st.session_state["history_file"] = {"bytes": data, "name": name, "mime": mime, "qid": qid}
        st.rerun()
    except Exception as e:  # noqa: BLE001
        st.error(f"만드는 중 문제가 생겼습니다: {e}")


def _load_into_editor(header, items):
    st.session_state[_k("hospital")] = header.get("병원명", "")
    st.session_state[_k("recipient")] = header.get("받는분", "")
    st.session_state[_k("no")] = header.get("견적번호", "")
    st.session_state[_k("valid")] = header.get("유효기간", "")
    st.session_state[_k("ref")] = header.get("참조", "")
    st.session_state[_k("dept")] = header.get("부서", "")
    st.session_state[_k("person")] = header.get("담당자", "")
    st.session_state[_k("title")] = header.get("직책", "")
    st.session_state[_k("tel")] = header.get("전화번호", "")
    st.session_state[_k("client_tel")] = header.get("전화", "")
    st.session_state["quote_items_df"] = pd.DataFrame(items)
    st.session_state["item_ver"] = st.session_state.get("item_ver", 0) + 1
    st.toast("불러왔습니다. '새 견적 만들기' 탭에서 이어서 수정하세요.", icon="✏️")
    st.rerun()
