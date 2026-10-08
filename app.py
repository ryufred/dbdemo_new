import streamlit as st

from utils import auth as A
from utils import config as C
from utils import ui as UI

st.set_page_config(page_title=C.APP_TITLE, page_icon="📊", layout="wide")
UI.inject()

if not A.is_logged_in():
    A.login_view()
    st.stop()

from views import db_input, db_status, main, quote, special_db, stats  # noqa: E402

pages = [
    st.Page(main.render, title="메인", icon=":material/home:", url_path="main", default=True),
    st.Page(db_status.render, title="DB현황 / 영업로그", icon=":material/table_view:", url_path="db-status"),
    st.Page(stats.render, title="DB통계", icon=":material/bar_chart:", url_path="stats"),
    st.Page(db_input.render, title="DB입력", icon=":material/edit_note:", url_path="db-input"),
    st.Page(special_db.render, title="특별 DB", icon=":material/celebration:", url_path="special-db"),
    st.Page(quote.render, title="견적서제작", icon=":material/description:", url_path="quote"),
]
pg = st.navigation(pages)
A.sidebar_user()
pg.run()
