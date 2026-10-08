"""앱 전체 공통 스타일 (폰트, 표 가독성 등)."""
import streamlit as st

# Pretendard / Noto Sans KR 우선, 사내망에서 CDN이 막히면 시스템 폰트로 자연스럽게 대체됩니다.
# ※ 아이콘(Material Symbols)까지 덮어쓰면 사이드바 메뉴가 깨지므로 아이콘 폰트는 아래에서 되돌립니다.
_CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable.min.css');
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&display=swap');

:root {
  --app-font: "Pretendard Variable", Pretendard, "Noto Sans KR", "Malgun Gothic",
              -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
}
html, body, .stApp { font-family: var(--app-font); -webkit-font-smoothing: antialiased; }
.stApp p, .stApp label, .stApp li, .stApp td, .stApp th,
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6,
.stApp button, .stApp input, .stApp textarea, .stApp select,
.stMarkdown, [data-testid="stWidgetLabel"], [data-testid="stMetricValue"],
[data-testid="stMetricLabel"] { font-family: var(--app-font); }

/* 아이콘 폰트는 반드시 원래대로 (사이드바 메뉴 아이콘 깨짐 방지) */
[data-testid="stIconMaterial"], .material-icons, .material-icons-outlined,
.material-symbols-rounded, .material-symbols-outlined,
span[translate="no"] {
  font-family: "Material Symbols Rounded", "Material Icons" !important;
  font-feature-settings: "liga" !important;
}

/* 숫자 입력칸의 +/- 버튼 숨김 (직접 타이핑만) */
[data-testid="stNumberInputStepUp"], [data-testid="stNumberInputStepDown"],
[data-testid="stNumberInputStepper"] { display: none !important; }
[data-testid="stNumberInputContainer"] input { border-radius: 8px; }

/* 표 머리글: 은은한 배경 + 진한 글씨로 컬럼이 바로 보이게 */
[data-testid="stDataFrame"] [role="columnheader"],
[data-testid="stDataEditor"] [role="columnheader"] {
  font-weight: 700 !important;
  color: #1B3A5C !important;
  background-color: #D7E6F5 !important;
}

/* 상세 화면의 항목 라벨 (순번/입력날짜/담당부서 …) */
.fieldlabel { font-size: .78rem; font-weight: 700; color: #4A6480;
              letter-spacing: .02em; margin-bottom: 6px; }
.fieldvalue { font-size: .95rem; line-height: 1.5; margin-bottom: 24px; }
</style>
"""


def inject():
    st.markdown(_CSS, unsafe_allow_html=True)
