import hmac
import streamlit as st
from utils import config as C


def _users() -> dict:
    try:
        u = st.secrets.get("users")
        if u:
            return {k: dict(v) for k, v in u.items()}
    except Exception:
        pass
    return {"admin": {"password": "admin1234", "role": "admin"}}  # 데모 계정


def is_logged_in() -> bool:
    return "user" in st.session_state


def current_user() -> dict:
    return st.session_state["user"]


def visible_teams() -> list:
    u = current_user()
    return C.TEAMS if u["role"] == "admin" else [u["team"]]


def scope(df):
    """로그인 사용자가 볼 수 있는 DB만 남김 (admin=전체, team=본인 팀)."""
    u = current_user()
    if u["role"] == "admin":
        return df
    return df[df["담당부서"] == u["team"]]


def login_view():
    _, mid, _ = st.columns([1, 1, 1])
    with mid:
        st.title("📊 " + C.APP_TITLE)
        with st.form("login"):
            uid = st.text_input("아이디")
            pw = st.text_input("비밀번호", type="password")
            if st.form_submit_button("로그인", type="primary", width="stretch"):
                users = _users()
                info = users.get(uid)
                if info and hmac.compare_digest(str(info.get("password", "")), pw):
                    st.session_state["user"] = {
                        "id": uid,
                        "role": info.get("role", "team"),
                        "team": info.get("team", ""),
                    }
                    st.rerun()
                else:
                    st.error("아이디 또는 비밀번호가 올바르지 않습니다.")


def sidebar_user():
    u = current_user()
    with st.sidebar:
        st.markdown(f"**👤 {u['id']}**")
        st.caption(f"환영합니다, {u['id']}님" + ("" if u["role"] == "admin" else f" ({u['team']})"))
        if st.button("로그아웃", icon=":material/logout:", width="stretch"):
            st.session_state.clear()
            st.rerun()
