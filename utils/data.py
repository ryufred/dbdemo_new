"""데이터 계층.
- 구글시트 설정(secrets의 [gsheets] + [gcp_service_account])이 있으면 구글시트에 읽고 씁니다.
- 없으면 data/ 폴더의 CSV로 동작합니다 (데모용).
페이지들은 이 파일의 함수만 사용하므로, 저장소가 바뀌어도 페이지 코드는 그대로입니다.

구글시트 구조
  raw        : Tally가 쌓는 원본 (앱은 '읽기만' 함)
  DB마스터   : 앱이 읽고 쓰는 정리된 DB (1행=DB 1건)
  진행로그   : 영업로그/이관/배정 이력 (계속 아래로 추가)
"""
import random
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from utils import config as C
from utils.clean import clean_raw_row, normalize_phone, parse_headers, phone_digits  # noqa: F401

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _a1(row: int, col: int) -> str:
    letters = ""
    while col:
        col, r = divmod(col - 1, 26)
        letters = chr(65 + r) + letters
    return f"{letters}{row}"


# ══ 저장소 1) CSV (데모) ════════════════════════════════════════
class CsvBackend:
    name = "CSV (데모 모드 · 구글시트 미연결)"
    import_from = None
    last_no = None

    def __init__(self, data_dir: Path = DATA_DIR):
        self.dir = data_dir
        self.db_path = data_dir / "db_master.csv"
        self.log_path = data_dir / "progress_log.csv"

    def _ensure(self):
        if self.db_path.exists():
            return
        self.dir.mkdir(exist_ok=True)
        if C.USE_SAMPLE_DATA:
            db, logs = _make_sample()
        else:
            db, logs = pd.DataFrame(columns=C.DB_COLUMNS), pd.DataFrame(columns=C.LOG_COLUMNS)
        db.reindex(columns=C.DB_COLUMNS, fill_value="").to_csv(self.db_path, index=False, encoding="utf-8-sig")
        logs.reindex(columns=C.LOG_COLUMNS, fill_value="").to_csv(self.log_path, index=False, encoding="utf-8-sig")

    def _load(self, path, cols):
        self._ensure()
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        return df[cols]

    def read_db(self, fresh=False):
        return self._load(self.db_path, C.DB_COLUMNS)

    def read_logs(self, fresh=False):
        return self._load(self.log_path, C.LOG_COLUMNS)

    def read_raw(self):
        return None

    def append_db(self, rows):
        df = pd.concat([self.read_db(), pd.DataFrame(rows)], ignore_index=True)
        df[C.DB_COLUMNS].to_csv(self.db_path, index=False, encoding="utf-8-sig")

    def update_db_many(self, updates: dict):
        df = self.read_db()
        for no, upd in updates.items():
            for k, v in upd.items():
                df.loc[df["순번"] == no, k] = v
        df.to_csv(self.db_path, index=False, encoding="utf-8-sig")

    def append_logs(self, rows):
        df = pd.concat([self.read_logs(), pd.DataFrame(rows)], ignore_index=True)
        df[C.LOG_COLUMNS].to_csv(self.log_path, index=False, encoding="utf-8-sig")


    # -- 견적서 카탈로그 --
    def load_catalog(self):
        p = self.dir / "quote_catalog.csv"
        if not p.exists():
            self.dir.mkdir(exist_ok=True)
            df = pd.DataFrame(C.DEFAULT_CATALOG)[C.CATALOG_COLS]
            df.to_csv(p, index=False, encoding="utf-8-sig")
            return df
        df = pd.read_csv(p, dtype=str, encoding="utf-8-sig").fillna("")
        for c in C.CATALOG_COLS:
            if c not in df.columns:
                df[c] = ""
        return df[C.CATALOG_COLS]

    def save_catalog(self, df):
        self.dir.mkdir(exist_ok=True)
        df[C.CATALOG_COLS].to_csv(self.dir / "quote_catalog.csv", index=False, encoding="utf-8-sig")

    # -- 견적서 이력 --
    def _quotes_path(self):
        return self.dir / "quotes.csv"

    def list_quotes(self):
        p = self._quotes_path()
        if not p.exists():
            return pd.DataFrame(columns=C.QUOTE_HISTORY_COLS)
        return pd.read_csv(p, dtype=str, encoding="utf-8-sig").fillna("")

    def upsert_quote(self, record: dict):
        df = self.list_quotes()
        df = df[df["견적번호"] != record["견적번호"]]
        self.dir.mkdir(exist_ok=True)
        pd.concat([df, pd.DataFrame([record])], ignore_index=True)[C.QUOTE_HISTORY_COLS].to_csv(
            self._quotes_path(), index=False, encoding="utf-8-sig")

    def delete_quote(self, qid: str):
        df = self.list_quotes()
        df[df["견적ID"] != qid].to_csv(self._quotes_path(), index=False, encoding="utf-8-sig")

    # -- 특별 DB (세미나/이벤트): 이벤트별 CSV 파일 + 목록 CSV --
    def _events_path(self):
        return self.dir / "special_events.csv"

    def _event_data_path(self, eid):
        return self.dir / "special" / f"{eid}.csv"

    def list_events(self):
        p = self._events_path()
        if not p.exists():
            return pd.DataFrame(columns=C.EVENT_REGISTRY_COLS)
        return pd.read_csv(p, dtype=str, encoding="utf-8-sig").fillna("")

    def create_event(self, name, schema, author):
        import json
        eid = uuid.uuid4().hex[:8]
        columns = [c["name"] for c in schema]
        reg = self.list_events()
        row = {"이벤트ID": eid, "이벤트명": name, "시트명": "", "컬럼": json.dumps(schema, ensure_ascii=False),
               "생성일": str(date.today()), "작성자": author}
        self.dir.mkdir(exist_ok=True)
        pd.concat([reg, pd.DataFrame([row])], ignore_index=True).to_csv(self._events_path(), index=False,
                                                                        encoding="utf-8-sig")
        (self.dir / "special").mkdir(exist_ok=True)
        pd.DataFrame(columns=["순번", *columns, "등록일시"]).to_csv(self._event_data_path(eid), index=False,
                                                                  encoding="utf-8-sig")
        return eid

    def read_event_rows(self, eid, columns):
        cols = ["순번", *columns, "등록일시"]
        p = self._event_data_path(eid)
        if not p.exists():
            return pd.DataFrame(columns=cols)
        df = pd.read_csv(p, dtype=str, encoding="utf-8-sig").fillna("")
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        return df[cols]

    def append_event_row(self, eid, columns, values: dict):
        df = self.read_event_rows(eid, columns)
        no = int(pd.to_numeric(df["순번"], errors="coerce").max()) + 1 if len(df) else 1
        row = {"순번": no, **{c: values.get(c, "") for c in columns},
               "등록일시": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        pd.concat([df, pd.DataFrame([row])], ignore_index=True).to_csv(self._event_data_path(eid), index=False,
                                                                       encoding="utf-8-sig")

    def bulk_append_event_rows(self, eid, columns, rows: list) -> int:
        df = self.read_event_rows(eid, columns)
        start = int(pd.to_numeric(df["순번"], errors="coerce").max()) + 1 if len(df) else 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new = [{"순번": start + i, **{c: r.get(c, "") for c in columns}, "등록일시": now}
               for i, r in enumerate(rows)]
        pd.concat([df, pd.DataFrame(new)], ignore_index=True).to_csv(self._event_data_path(eid), index=False,
                                                                     encoding="utf-8-sig")
        return len(new)

    def update_event_columns(self, eid, schema: list, sources=None):
        """컬럼명/유형 추가·수정·삭제.
        sources[j] = 그 컬럼이 원래 어떤 컬럼이었는지(이름). None 이면 새 컬럼(빈 값).
        이름만 바꾼 컬럼은 데이터를 그대로 들고 가고, 삭제한 컬럼의 데이터만 사라집니다."""
        import json
        new_columns = [c["name"] for c in schema]
        reg = self.list_events()
        idx = reg.index[reg["이벤트ID"] == eid]
        if len(idx) == 0:
            raise KeyError(f"이벤트 {eid} 를 찾을 수 없습니다.")
        i = idx[0]
        old_columns = [c["name"] if isinstance(c, dict) else c for c in json.loads(reg.at[i, "컬럼"])]
        df = self.read_event_rows(eid, old_columns)
        if sources is None:                       # 지정이 없으면 예전처럼 순서 기준
            sources = [old_columns[j] if j < len(old_columns) else None for j in range(len(new_columns))]
        aligned = pd.DataFrame(index=df.index)
        for col, src in zip(new_columns, sources):
            aligned[col] = df[src] if src and src in df.columns else ""
        out = pd.concat([df[["순번"]], aligned, df[["등록일시"]]], axis=1)
        out.to_csv(self._event_data_path(eid), index=False, encoding="utf-8-sig")
        reg.at[i, "컬럼"] = json.dumps(schema, ensure_ascii=False)
        reg.to_csv(self._events_path(), index=False, encoding="utf-8-sig")

    def delete_event(self, eid):
        reg = self.list_events()
        reg = reg[reg["이벤트ID"] != eid]
        reg.to_csv(self._events_path(), index=False, encoding="utf-8-sig")
        p = self._event_data_path(eid)
        if p.exists():
            p.unlink()


# ══ 저장소 2) 구글시트 ══════════════════════════════════════════
class SheetsBackend:
    name = "구글시트"
    TTL = 15   # 초. 조회 API 호출 횟수를 줄이기 위한 짧은 캐시 (쓰기 시 즉시 무효화)

    def __init__(self, app_ss, raw_ss, cfg: dict, not_found_exc=Exception):
        self.app_ss, self.raw_ss, self.cfg, self.NotFound = app_ss, raw_ss, cfg, not_found_exc
        self.import_from = str(cfg.get("import_from", "") or "")
        self.last_no = str(cfg.get("last_no", "") or "")   # 기존 시트의 마지막 순번 (예: "26-187") → 이 다음 번호부터 부여
        self.names = {"db": cfg.get("master_worksheet", "DB마스터"), "log": cfg.get("log_worksheet", "진행로그")}
        self.cols = {"db": C.DB_COLUMNS, "log": C.LOG_COLUMNS}
        self._ws, self._cache = {}, {}

    # -- 워크시트 확보 (없으면 생성, 헤더가 다르면 덮어쓰지 않고 중단) --
    def _get_ws(self, kind):
        if kind in self._ws:
            return self._ws[kind]
        name, cols = self.names[kind], self.cols[kind]
        try:
            ws = self.app_ss.worksheet(name)
            head = ws.row_values(1)
            if not head:
                ws.update([cols], "A1", value_input_option="RAW")
            elif head[:len(cols)] != cols:
                raise RuntimeError(f"시트 '{name}'의 헤더가 앱 형식과 달라 사용할 수 없습니다. "
                                   f"새 시트 이름을 secrets의 master_worksheet/log_worksheet에 지정해주세요. "
                                   f"(필요한 헤더: {', '.join(cols)})")
        except self.NotFound:
            ws = self.app_ss.add_worksheet(title=name, rows=2000, cols=len(cols))
            ws.update([cols], "A1", value_input_option="RAW")
        self._ws[kind] = ws
        return ws

    def _df(self, kind, fresh=False):
        hit = self._cache.get(kind)
        if hit and not fresh and time.time() - hit[0] < self.TTL:
            return hit[1].copy()
        cols = self.cols[kind]
        vals = self._get_ws(kind).get_all_values()
        rows = [r + [""] * (len(cols) - len(r)) for r in vals[1:]]
        df = pd.DataFrame([r[:len(cols)] for r in rows], columns=cols) if rows else pd.DataFrame(columns=cols)
        self._cache[kind] = (time.time(), df)
        return df.copy()

    def read_db(self, fresh=False):
        return self._df("db", fresh)

    def read_logs(self, fresh=False):
        return self._df("log", fresh)

    def read_raw(self):
        name = self.cfg.get("raw_worksheet", "raw")
        return self.raw_ss.worksheet(name).get_all_values()

    def append_db(self, rows):
        if rows:
            self._get_ws("db").append_rows([[r.get(c, "") for c in C.DB_COLUMNS] for r in rows],
                                           value_input_option="RAW")
            self._cache.pop("db", None)

    def append_logs(self, rows):
        if rows:
            self._get_ws("log").append_rows([[r.get(c, "") for c in C.LOG_COLUMNS] for r in rows],
                                            value_input_option="RAW")
            self._cache.pop("log", None)

    def update_db_many(self, updates: dict):
        if not updates:
            return
        ws = self._get_ws("db")
        no_col = C.DB_COLUMNS.index("순번") + 1
        row_of = {v: i + 1 for i, v in enumerate(ws.col_values(no_col))}   # 항상 최신 행 위치로 조회
        data = []
        for no, upd in updates.items():
            if no not in row_of:
                raise KeyError(f"순번 {no} 을 시트에서 찾을 수 없습니다.")
            for k, v in upd.items():
                data.append({"range": _a1(row_of[no], C.DB_COLUMNS.index(k) + 1), "values": [[v]]})
        ws.batch_update(data, value_input_option="RAW")
        self._cache.pop("db", None)


    # -- 견적서 카탈로그 --
    CATALOG_WS = "견적카탈로그"

    def _catalog_ws(self):
        try:
            ws = self.app_ss.worksheet(self.CATALOG_WS)
            if not ws.row_values(1):
                ws.update([C.CATALOG_COLS], "A1", value_input_option="RAW")
        except self.NotFound:
            ws = self.app_ss.add_worksheet(title=self.CATALOG_WS, rows=200, cols=len(C.CATALOG_COLS))
            ws.update([C.CATALOG_COLS], "A1", value_input_option="RAW")
        return ws

    def load_catalog(self):
        ws = self._catalog_ws()
        vals = ws.get_all_values()
        if len(vals) < 2:
            df = pd.DataFrame(C.DEFAULT_CATALOG)[C.CATALOG_COLS]
            ws.append_rows(df.values.tolist(), value_input_option="RAW")
            return df
        cols = C.CATALOG_COLS
        rows = [r + [""] * (len(cols) - len(r)) for r in vals[1:]]
        return pd.DataFrame([r[:len(cols)] for r in rows], columns=cols)

    def save_catalog(self, df):
        ws = self._catalog_ws()
        ws.clear()
        ws.update([C.CATALOG_COLS] + df[C.CATALOG_COLS].astype(str).values.tolist(), "A1",
                 value_input_option="RAW")

    # -- 견적서 이력 --
    QUOTES_WS = "견적함"

    def _quotes_ws(self):
        try:
            ws = self.app_ss.worksheet(self.QUOTES_WS)
            if not ws.row_values(1):
                ws.update([C.QUOTE_HISTORY_COLS], "A1", value_input_option="RAW")
        except self.NotFound:
            ws = self.app_ss.add_worksheet(title=self.QUOTES_WS, rows=1000, cols=len(C.QUOTE_HISTORY_COLS))
            ws.update([C.QUOTE_HISTORY_COLS], "A1", value_input_option="RAW")
        return ws

    def list_quotes(self):
        vals = self._quotes_ws().get_all_values()
        cols = C.QUOTE_HISTORY_COLS
        rows = [r + [""] * (len(cols) - len(r)) for r in vals[1:]]
        return pd.DataFrame([r[:len(cols)] for r in rows], columns=cols) if rows else pd.DataFrame(columns=cols)

    def upsert_quote(self, record: dict):
        ws = self._quotes_ws()
        no_col = C.QUOTE_HISTORY_COLS.index("견적번호") + 1
        existing = ws.col_values(no_col)
        row_data = [str(record.get(c, "")) for c in C.QUOTE_HISTORY_COLS]
        if record["견적번호"] in existing[1:]:
            row_i = existing.index(record["견적번호"]) + 1
            ws.update([row_data], f"A{row_i}", value_input_option="RAW")
        else:
            ws.append_rows([row_data], value_input_option="RAW")

    def delete_quote(self, qid: str):
        ws = self._quotes_ws()
        id_col = C.QUOTE_HISTORY_COLS.index("견적ID") + 1
        ids = ws.col_values(id_col)
        if qid in ids[1:]:
            row_i = ids.index(qid) + 1
            ws.delete_rows(row_i)

    # -- 특별 DB (세미나/이벤트): 이벤트마다 별도 워크시트 + 목록 워크시트 --
    EVENT_REGISTRY = "특별DB_목록"

    def _registry_ws(self):
        cols = C.EVENT_REGISTRY_COLS
        try:
            ws = self.app_ss.worksheet(self.EVENT_REGISTRY)
            if not ws.row_values(1):
                ws.update([cols], "A1", value_input_option="RAW")
        except self.NotFound:
            ws = self.app_ss.add_worksheet(title=self.EVENT_REGISTRY, rows=200, cols=len(cols))
            ws.update([cols], "A1", value_input_option="RAW")
        return ws

    def list_events(self):
        vals = self._registry_ws().get_all_values()
        cols = C.EVENT_REGISTRY_COLS
        rows = [r + [""] * (len(cols) - len(r)) for r in vals[1:]]
        return pd.DataFrame([r[:len(cols)] for r in rows], columns=cols) if rows else pd.DataFrame(columns=cols)

    def create_event(self, name, schema, author):
        import json
        eid = uuid.uuid4().hex[:8]
        columns = [c["name"] for c in schema]
        sheet_name = f"특별_{eid}"
        ws = self.app_ss.add_worksheet(title=sheet_name, rows=1000, cols=len(columns) + 2)
        ws.update([["순번", *columns, "등록일시"]], "A1", value_input_option="RAW")
        self._registry_ws().append_rows(
            [[eid, name, sheet_name, json.dumps(schema, ensure_ascii=False), str(date.today()), author]],
            value_input_option="RAW")
        return eid

    def _event_sheet_name(self, eid):
        reg = self.list_events()
        row = reg[reg["이벤트ID"] == eid]
        if row.empty:
            raise KeyError(f"이벤트 {eid} 를 찾을 수 없습니다.")
        return row.iloc[0]["시트명"]

    def read_event_rows(self, eid, columns):
        ws = self.app_ss.worksheet(self._event_sheet_name(eid))
        cols = ["순번", *columns, "등록일시"]
        vals = ws.get_all_values()
        rows = [r + [""] * (len(cols) - len(r)) for r in vals[1:]]
        return pd.DataFrame([r[:len(cols)] for r in rows], columns=cols) if rows else pd.DataFrame(columns=cols)

    def append_event_row(self, eid, columns, values: dict):
        ws = self.app_ss.worksheet(self._event_sheet_name(eid))
        existing = [v for v in ws.col_values(1)[1:] if v.isdigit()]
        no = (max(map(int, existing)) if existing else 0) + 1
        ws.append_rows([[no, *[values.get(c, "") for c in columns],
                         datetime.now().strftime("%Y-%m-%d %H:%M:%S")]], value_input_option="RAW")

    def bulk_append_event_rows(self, eid, columns, rows: list) -> int:
        ws = self.app_ss.worksheet(self._event_sheet_name(eid))
        existing = [v for v in ws.col_values(1)[1:] if v.isdigit()]
        start = (max(map(int, existing)) if existing else 0) + 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = [[start + i, *[r.get(c, "") for c in columns], now] for i, r in enumerate(rows)]
        if data:
            ws.append_rows(data, value_input_option="RAW")
        return len(data)

    def update_event_columns(self, eid, schema: list, sources=None):
        """컬럼명/유형 추가·수정·삭제.
        sources[j] = 그 컬럼이 원래 어떤 컬럼이었는지(이름). None 이면 새 컬럼(빈 값)."""
        import json
        new_columns = [c["name"] for c in schema]
        reg = self.list_events()
        idx = reg.index[reg["이벤트ID"] == eid]
        if len(idx) == 0:
            raise KeyError(f"이벤트 {eid} 를 찾을 수 없습니다.")
        i = idx[0]
        old_columns = [c["name"] if isinstance(c, dict) else c for c in json.loads(reg.at[i, "컬럼"])]
        sheet_name = reg.at[i, "시트명"]
        ws = self.app_ss.worksheet(sheet_name)
        vals = ws.get_all_values()
        n_old = len(old_columns)
        if sources is None:
            sources = [old_columns[j] if j < len(old_columns) else None for j in range(len(new_columns))]
        pos = {name: j for j, name in enumerate(old_columns)}
        new_rows = []
        for r in vals[1:]:
            no = r[0] if r else ""
            old_data = r[1:1 + n_old]
            ts = r[1 + n_old] if len(r) > 1 + n_old else ""
            aligned = []
            for src in sources:
                j = pos.get(src) if src else None
                aligned.append(old_data[j] if j is not None and j < len(old_data) else "")
            new_rows.append([no, *aligned, ts])
        ws.clear()
        ws.update([["순번", *new_columns, "등록일시"]] + new_rows, "A1", value_input_option="RAW")
        col_idx = C.EVENT_REGISTRY_COLS.index("컬럼") + 1
        self._registry_ws().update_cell(i + 2, col_idx, json.dumps(schema, ensure_ascii=False))

    def delete_event(self, eid):
        reg = self.list_events()
        idx = reg.index[reg["이벤트ID"] == eid]
        if len(idx) == 0:
            return
        sheet_name = reg.at[idx[0], "시트명"]
        try:
            self.app_ss.del_worksheet(self.app_ss.worksheet(sheet_name))
        except self.NotFound:
            pass
        reg_ws = self._registry_ws()
        reg_ws.clear()
        remaining = reg[reg["이벤트ID"] != eid]
        reg_ws.update([C.EVENT_REGISTRY_COLS] + remaining.astype(str).values.tolist(), "A1",
                      value_input_option="RAW")


# ══ 저장소 선택 ═════════════════════════════════════════════════
_B = None


def set_backend(b):
    global _B
    _B = b


def _make_backend():
    try:
        import streamlit as st
        cfg, sa = st.secrets.get("gsheets"), st.secrets.get("gcp_service_account")
    except Exception:
        cfg = sa = None
    if not (cfg and sa):
        return CsvBackend()
    import gspread
    cfg = dict(cfg)
    gc = gspread.service_account_from_dict(dict(sa))
    app_ss = gc.open_by_key(cfg["spreadsheet_id"])
    raw_id = cfg.get("raw_spreadsheet_id") or cfg["spreadsheet_id"]
    raw_ss = app_ss if raw_id == cfg["spreadsheet_id"] else gc.open_by_key(raw_id)
    return SheetsBackend(app_ss, raw_ss, cfg, gspread.WorksheetNotFound)


def _backend():
    global _B
    if _B is None:
        _B = _make_backend()
    return _B


def backend_name() -> str:
    return _backend().name


def raw_enabled() -> bool:
    return isinstance(_backend(), SheetsBackend)


# ══ 조회 ═══════════════════════════════════════════════════════
def load_db() -> pd.DataFrame:
    df = _backend().read_db()
    df["입력월"] = df["입력날짜"].str[:7]
    return df


def load_logs() -> pd.DataFrame:
    return _backend().read_logs()


# ── 순번 (예: 26-001 = 26년 1번째, 해가 바뀌면 27-001부터) ─────
def _no_key(s: pd.Series) -> pd.Series:
    return s.map(lambda x: int(x.split("-")[0]) * 100000 + int(x.split("-")[1]))


def sort_by_no(df: pd.DataFrame, ascending: bool = False) -> pd.DataFrame:
    return df.sort_values("순번", key=_no_key, ascending=ascending) if len(df) else df


def _seq_counters(db: pd.DataFrame) -> dict:
    seq = {}
    start = getattr(_backend(), "last_no", None)
    for n in list(db["순번"]) + ([start] if start else []):
        if "-" in n:
            yy, s = n.split("-", 1)
            seq[yy] = max(seq.get(yy, 0), int(s))
    return seq


def next_no(db: pd.DataFrame, year: int) -> str:
    yy = f"{year % 100:02d}"
    return f"{yy}-{_seq_counters(db).get(yy, 0) + 1:03d}"


def bulk_add_db(rows: list, author: str = "") -> int:
    """과거 DB(Tally 사용 전 데이터 등)를 여러 건 한 번에 등록.
    순번을 비워두면 자동 부여, 이미 쓰던 번호(예: 26-045)를 적어 넣으면 그 번호를 그대로 씁니다."""
    b = _backend()
    db = b.read_db(fresh=True)
    seq = _seq_counters(db)
    existing_nos = set(db["순번"])
    new_rows, logs = [], []
    for r in rows:
        if not str(r.get("병원명", "")).strip():
            continue
        row = {c: "" for c in C.DB_COLUMNS}
        row.update({k: v for k, v in r.items() if k in C.DB_COLUMNS})
        no = str(row.get("순번", "")).strip()
        if no and no not in existing_nos and "-" in no:
            yy, n = no.split("-", 1)
            seq[yy] = max(seq.get(yy, 0), int(n))
        else:
            yy = (row["입력날짜"][2:4] if len(row["입력날짜"]) >= 4 else f"{date.today().year % 100:02d}")
            seq[yy] = seq.get(yy, 0) + 1
            no = f"{yy}-{seq[yy]:03d}"
        row["순번"] = no
        existing_nos.add(no)
        row["연락처"] = normalize_phone(row["연락처"])
        row["진행상황"] = row["진행상황"] or C.PRE_CONTACT
        row["등록경로"] = row["등록경로"] or "과거DB"
        new_rows.append(row)
        logs.append(_log_entry(no, row["입력날짜"] or str(date.today()), row["진행상황"],
                               "과거 DB 일괄 등록", author, "등록"))
    b.append_db(new_rows)
    b.append_logs(logs)
    return len(new_rows)


def update_note(no: str, text: str):
    """비고(캠페인·특이사항) 수정."""
    _backend().update_db_many({no: {"비고": text}})


def _norm_name(v: str) -> str:
    return "".join(str(v).split()).lower()


def find_similar(phone: str = "", hospital: str = "", exclude_no: str = "") -> pd.DataFrame:
    """연락처 또는 병원명이 같은 기존 DB를 찾음 (중복 접수 확인용)."""
    db = load_db()
    digits, name = phone_digits(phone), _norm_name(hospital)
    hit = pd.Series(False, index=db.index)
    if digits:
        hit |= db["연락처"].map(phone_digits) == digits
    if name:
        hit |= db["병원명"].map(_norm_name) == name
    if exclude_no:
        hit &= db["순번"] != exclude_no
    return db[hit]


def duplicate_groups() -> pd.DataFrame:
    """연락처 또는 병원명이 겹치는 DB들만 모아서 반환 (겹침 사유 포함)."""
    db = load_db()
    if db.empty:
        return db.assign(중복사유="")
    ph = db["연락처"].map(phone_digits)
    nm = db["병원명"].map(_norm_name)
    dup_ph = ph.duplicated(keep=False) & ph.ne("")
    dup_nm = nm.duplicated(keep=False) & nm.ne("")
    reason = pd.Series("", index=db.index)
    reason[dup_ph & dup_nm] = "연락처+병원명"
    reason[dup_ph & ~dup_nm] = "연락처"
    reason[~dup_ph & dup_nm] = "병원명"
    out = db[dup_ph | dup_nm].copy()
    out["중복사유"] = reason[out.index]
    return out


def existing_notes() -> list:
    """이미 쓴 적 있는 비고(캠페인) 값 목록 — 새로 입력할 때 골라 쓰도록."""
    db = load_db()
    vals = [v.strip() for v in db["비고"].tolist() if str(v).strip()]
    return sorted(set(vals))


def find_duplicates(phone: str) -> pd.DataFrame:
    digits = phone_digits(phone)
    db = load_db()
    if not digits:
        return db.iloc[0:0]
    return db[db["연락처"].map(phone_digits) == digits]


# ══ 등록 / 로그 / 배정·이관 ════════════════════════════════════
def _log_entry(no, log_date, status, content, author, kind):
    return {"로그ID": uuid.uuid4().hex[:8], "순번": no, "날짜": str(log_date), "진행상황": status,
            "내용": content, "작성자": author, "유형": kind,
            "기록시각": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def add_db(record: dict, author: str = "") -> str:
    """수동 입력 DB 등록. 담당부서는 비워두고(미할당), 진행상황은 '접촉 전'으로 시작. 순번을 반환."""
    b = _backend()
    try:                       # 아직 안 가져온 Tally 응답을 먼저 반영 → 순번이 접수 순서대로 매겨지도록
        import_from_raw()
    except Exception:          # noqa: BLE001  (설정 문제는 메인 화면의 불러오기에서 안내)
        pass
    db = b.read_db(fresh=True)
    row = {c: "" for c in C.DB_COLUMNS}
    row.update(record)
    row["순번"] = next_no(db, int(record["입력날짜"][:4]))
    row["진행상황"] = record.get("진행상황") or C.PRE_CONTACT
    row["연락처"] = normalize_phone(row["연락처"])
    b.append_db([row])
    b.append_logs([_log_entry(row["순번"], date.today(), row["진행상황"],
                              f"DB 등록 ({row['등록경로'] or '수동입력'})", author, "등록")])
    return row["순번"]


def add_log(no: str, log_date, status: str, content: str, author: str = "", kind: str = "영업"):
    """로그 1건 추가. kind가 '영업'이면 DB의 진행상황도 함께 갱신."""
    b = _backend()
    b.append_logs([_log_entry(no, log_date, status, content, author, kind)])
    if kind == "영업":
        b.update_db_many({no: {"진행상황": status}})


def _ro(word: str) -> str:
    """조사 '로/으로' 선택 (받침 없음·ㄹ받침 → 로, 그 외 → 으로)."""
    code = ord(word[-1]) - 0xAC00
    return "로" if 0 <= code < 11172 and code % 28 in (0, 8) else "으로"


def assign_many(nos: list, to_team: str, author: str = "") -> int:
    """담당부서 일괄 변경 + 히스토리 자동 기록 (시트 호출은 묶어서 1~2회).
    미할당 → 팀: 'xxxx년 x월 x일 미할당에서 B팀으로 DB 배정' / 팀 → 팀: '...A팀에서 B팀으로 DB 이관'"""
    b = _backend()
    db = b.read_db(fresh=True)
    d = date.today()
    updates, logs = {}, []
    for _, r in db[db["순번"].isin(nos)].iterrows():
        frm = r["담당부서"]
        if frm == to_team:
            continue
        word = "이관" if frm else "배정"
        updates[r["순번"]] = {"담당부서": to_team}
        logs.append(_log_entry(r["순번"], d, r["진행상황"],
                               f"{d.year}년 {d.month}월 {d.day}일 {frm or C.UNASSIGNED}에서 "
                               f"{to_team}{_ro(to_team)} DB {word}", author, word))
    b.update_db_many(updates)
    b.append_logs(logs)
    return len(updates)


def transfer_db(no: str, to_team: str, author: str = ""):
    if assign_many([no], to_team, author) == 0:
        raise ValueError("현재 담당부서와 같은 팀입니다.")


def mark_invalid_many(nos: list, author: str = "") -> int:
    """미할당 DB를 팀 배정 없이 '무효' 처리 (할당 전 이상한 DB 거르기용)."""
    b = _backend()
    db = b.read_db(fresh=True)
    d = date.today()
    updates, logs = {}, []
    for _, r in db[db["순번"].isin(nos)].iterrows():
        if r["진행상황"] == C.INVALID_STATUS:
            continue
        updates[r["순번"]] = {"진행상황": C.INVALID_STATUS}
        logs.append(_log_entry(r["순번"], d, C.INVALID_STATUS, "할당 전 무효 처리", author, "무효"))
    b.update_db_many(updates)
    b.append_logs(logs)
    return len(updates)


# ══ raw(Tally) → 마스터 가져오기 ═══════════════════════════════
def import_from_raw():
    """raw 시트의 새 응답을 정리(clean)해서 DB마스터에 추가. 반환: 추가 건수 (구글시트 미연결이면 None).
    - 이미 가져온 응답은 원본ID(=raw 첫 열의 Submission ID)로 구분해서 건너뜀
    - secrets의 import_from 날짜 이후 응답만 가져옴 (과거 raw 전체가 미할당으로 쏟아지는 것 방지)"""
    b = _backend()
    raw = b.read_raw()
    if raw is None:
        return None
    if not b.import_from:
        raise RuntimeError("secrets의 [gsheets]에 import_from = \"YYYY-MM-DD\" 를 설정해주세요. "
                           "이 날짜 이후 접수된 raw 응답만 마스터로 가져옵니다.")
    if len(raw) < 2:
        return 0
    cols = parse_headers(raw[0])
    db = b.read_db(fresh=True)
    known = set(db["원본ID"])
    seq = _seq_counters(db)
    new, logs = [], []
    for row in raw[1:]:
        rec = clean_raw_row(cols, row)
        if not rec or not rec["입력날짜"] or rec["입력날짜"] < b.import_from or rec["원본ID"] in known:
            continue
        known.add(rec["원본ID"])
        yy = rec["입력날짜"][2:4]
        seq[yy] = seq.get(yy, 0) + 1
        rec["순번"] = f"{yy}-{seq[yy]:03d}"
        new.append(rec)
        logs.append({**_log_entry(rec["순번"], rec["입력날짜"], C.PRE_CONTACT, "DB 등록 (Tally)", "system", "등록")})
    b.append_db(new)
    b.append_logs(logs)
    return len(new)


# ══ 특별 DB (세미나/이벤트) ═════════════════════════════════════
# 팀별 정규 DB와 별도로, 이벤트마다 컬럼을 자유롭게 정의해서 쓰는 미니 스프레드시트.
# 순번은 이벤트별로 1부터 다시 매김 (정규 DB의 26-xxx 형식과 무관).


def list_events() -> pd.DataFrame:
    return _backend().list_events()


COL_TEXT, COL_SELECT = "텍스트", "드롭다운"


def norm_schema(items: list) -> list:
    """컬럼 정의를 {name, type, options} 형태로 통일.
    예전에 만든 이벤트는 이름만 저장돼 있어서 문자열도 그대로 받습니다."""
    out = []
    for c in items:
        if isinstance(c, dict):
            name = str(c.get("name", "")).strip()
            ctype = c.get("type") or COL_TEXT
            opts = [str(o).strip() for o in (c.get("options") or []) if str(o).strip()]
        else:
            name, ctype, opts = str(c).strip(), COL_TEXT, []
        if not name:
            continue
        if ctype != COL_SELECT:
            ctype, opts = COL_TEXT, []
        out.append({"name": name, "type": ctype, "options": opts})
    return out


def create_event(name: str, columns: list, author: str = "") -> str:
    schema = norm_schema(columns)
    if not schema:
        raise ValueError("컬럼을 1개 이상 입력해주세요.")
    return _backend().create_event(name.strip(), schema, author)


def event_schema(eid: str) -> list:
    import json
    reg = list_events()
    row = reg[reg["이벤트ID"] == eid]
    if row.empty:
        raise KeyError("이벤트를 찾을 수 없습니다.")
    return norm_schema(json.loads(row.iloc[0]["컬럼"]))


def event_columns(eid: str) -> list:
    return [c["name"] for c in event_schema(eid)]


def load_event_rows(eid: str):
    cols = event_columns(eid)
    return _backend().read_event_rows(eid, cols), cols


def add_event_row(eid: str, values: dict, author: str = ""):
    cols = event_columns(eid)
    _backend().append_event_row(eid, cols, values)


def bulk_add_event_rows(eid: str, rows: list, author: str = "") -> int:
    """복붙/엑셀 업로드로 여러 행을 한 번에 등록. 값이 모두 빈 행은 건너뜀."""
    cols = event_columns(eid)
    rows = [r for r in rows if any(str(v).strip() for v in r.values())]
    if not rows:
        return 0
    return _backend().bulk_append_event_rows(eid, cols, rows)


def update_event_columns(eid: str, new_columns: list, sources=None):
    """sources: 각 컬럼이 원래 어떤 컬럼이었는지(이름) 목록. 이름 변경과 삭제를 구분하는 데 씁니다."""
    schema = norm_schema(new_columns)
    if not schema:
        raise ValueError("컬럼을 1개 이상 입력해주세요.")
    if sources is not None and len(sources) != len(schema):
        sources = None
    _backend().update_event_columns(eid, schema, sources)


def delete_event(eid: str):
    _backend().delete_event(eid)


def list_quotes() -> pd.DataFrame:
    return _backend().list_quotes()


def save_quote(header: dict, items: list, overall_type: str, overall_value, final_amount: float, author: str = ""):
    import json
    record = {
        "견적ID": uuid.uuid4().hex[:8], "병원명": header["병원명"], "견적번호": header.get("견적번호", ""),
        "견적일자": header.get("견적일자", ""), "담당자": header.get("담당자", ""), "항목수": str(len(items)),
        "최종합계": f"{final_amount:.0f}", "작성자": author,
        "생성일시": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "데이터": json.dumps({"header": header, "items": items, "overall_type": overall_type,
                             "overall_value": overall_value}, ensure_ascii=False),
    }
    _backend().upsert_quote(record)
    return record["견적ID"]


def delete_quote(qid: str):
    _backend().delete_quote(qid)


def load_catalog() -> pd.DataFrame:
    return _backend().load_catalog()


def save_catalog(df: pd.DataFrame):
    _backend().save_catalog(df)


# ══ 샘플 데이터 (CSV 데모용) ═══════════════════════════════════
def _make_sample():
    rnd = random.Random(42)
    names = ["서울바른", "연세튼튼", "해오름", "맑은숨", "새봄", "하늘빛", "리더스", "우리들", "참좋은", "다온"]
    kinds = ["치과", "피부과", "정형외과", "한의원", "성형외과", "안과", "내과", "산부인과"]
    areas = ["서울시 마포구", "서울시 강남구", "부산광역시", "대전광역시", "경기도 성남시", "인천광역시", "경기도 수원시"]
    weights = [18, 12, 12, 8, 6, 4, 20, 10, 14]   # C.STATUSES 와 길이가 같아야 함
    today = date.today()
    dates = sorted(today - timedelta(days=rnd.randint(0, 200)) for _ in range(60))
    counters, rows, logs = {}, [], []
    for d in dates:
        yy = f"{d.year % 100:02d}"
        counters[yy] = counters.get(yy, 0) + 1
        no = f"{yy}-{counters[yy]:03d}"
        unassigned = d >= today - timedelta(days=8)          # 최근 들어온 DB는 미할당
        status = C.PRE_CONTACT if unassigned else rnd.choices(C.STATUSES, weights=weights)[0]
        team = "" if unassigned else rnd.choice(C.TEAMS)
        kind = rnd.choice(kinds)
        ch = rnd.choice(C.CHANNELS)
        rows.append({
            "순번": no, "입력날짜": str(d), "담당부서": team, "진행상황": status,
            "병원명": f"{names[(counters[yy] - 1) % len(names)]}{kind}{counters[yy]:02d}", "병원소재지": rnd.choice(areas), "분과": kind,
            "연락처": f"010-{rnd.randint(1000, 9999)}-{rnd.randint(1000, 9999)}",
            "담당자": rnd.choice(["김원장", "이실장", "박팀장", "최이사"]),
            "문의이유": ", ".join(rnd.sample(C.INQUIRY_REASONS, rnd.randint(1, 2))),
            "세부문의사항": "샘플 데이터입니다.\n문의 내용이 길어질 경우를 가정한 여러 줄 텍스트 예시입니다. " * 2,
            "유입경로": ch, "유입경로_기타": "박람회" if ch == C.CHANNEL_ETC else "",
            "비고": "",
            "등록경로": "Tally",
        })
        logs.append(_log_entry(no, d, C.PRE_CONTACT, "DB 등록 (Tally)", "system", "등록"))
        if team:
            logs.append(_log_entry(no, d, C.PRE_CONTACT,
                                   f"{d.year}년 {d.month}월 {d.day}일 미할당에서 {team}{_ro(team)} DB 배정", "admin", "배정"))
        if status != C.PRE_CONTACT:
            logs.append(_log_entry(no, d + timedelta(days=1), status, "샘플 영업로그", "admin", "영업"))
    return pd.DataFrame(rows), pd.DataFrame(logs)
