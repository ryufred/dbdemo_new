# 애드리절트 DB 대시보드

Tally → 구글시트로 들어오는 병원 문의 DB를 팀 배정 / 영업로그 / 통계 / 견적서까지 한 곳에서 관리하는 Streamlit 앱.

## 페이지

| 페이지 | 내용 |
|---|---|
| 메인 | 올해·이번달 DB 건수, 미할당 DB 팀 배정, 중복 의심 DB, 접촉 전 목록 |
| DB현황 / 영업로그 | 팀별 DB 조회, 상세·영업로그 작성, 이관/배정, 비고 수정 |
| DB통계 | KPI, 팀·채널·지역·분과·캠페인별 통계 + 세부 통계(퍼널 / 응답 속도 / 기간 비교) |
| DB입력 | 1건씩 신규 등록, 엑셀 복붙 일괄 등록 |
| 특별 DB | 세미나·이벤트별로 컬럼을 직접 정의하는 별도 DB (드롭다운 컬럼 지원) |
| 견적서 제작 | 카탈로그에서 담아 견적 작성, 미리보기 / XLSX / PDF 다운로드, 이전 견적 보관 |

## 로컬 실행

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

`secrets.toml`이 없으면 **데모 모드**로 동작합니다.
- 로그인: `admin` / `admin1234`
- 데이터: `data/` 폴더에 CSV로 저장되며, 첫 실행 시 샘플 60건이 자동 생성됩니다.
- 샘플이 필요 없으면 `utils/config.py`의 `USE_SAMPLE_DATA = False`로 바꾸고 `data/` 폴더를 지우세요.

## 구글시트 연결

`.streamlit/secrets.toml.example`을 `.streamlit/secrets.toml`로 복사해 채웁니다.

1. Google Cloud에서 **Sheets API**와 **Drive API**를 켜고 서비스 계정 JSON 키를 발급
2. 앱 전용 스프레드시트를 새로 만들고, 서비스 계정 이메일에 **편집자** 권한으로 공유
   (`DB마스터`, `진행로그`, `견적카탈로그`, `견적함`, `특별DB_목록` 탭은 앱이 자동 생성)
3. Tally raw 시트는 같은 계정에 **뷰어** 권한으로 공유 (앱은 읽기만 함)
4. `secrets.toml`에 시트 ID, `raw_worksheet`, `import_from`, `last_no`, 서비스 계정 정보 입력

- `import_from` : 이 날짜 이후 접수된 raw 응답만 가져옵니다. 처음엔 최근 날짜로 두고 테스트하세요.
- `last_no` : 기존 시트에서 쓰던 마지막 순번(예: `26-187`). 다음 번호부터 이어서 부여됩니다.

## 배포 (Streamlit Community Cloud)

1. **비공개(Private)** GitHub 저장소에 올립니다. `.gitignore`가 `secrets.toml`과 `data/`를 제외합니다.
2. [share.streamlit.io](https://share.streamlit.io) → New app → 저장소 선택, Main file은 `app.py`
3. **Advanced settings → Secrets**에 `secrets.toml` 내용을 그대로 붙여넣습니다.

> 주의: secrets를 넣지 않으면 데모 모드(CSV)로 뜨는데, Cloud는 재시작 시 파일이 사라지므로
> 입력한 데이터가 날아갑니다. **실제 사용은 반드시 구글시트 연결 후**에 하세요.

PDF·엑셀 생성은 순수 파이썬 라이브러리(openpyxl, reportlab)만 사용하므로 별도 시스템 패키지 설치가 필요 없습니다.

## 주요 설정 (`utils/config.py`)

| 항목 | 설명 |
|---|---|
| `TEAMS` | 팀 목록 |
| `STATUSES` / `STATUS_COLORS` | 진행상황과 표시 색 |
| `FUNNEL_STAGES` / `FUNNEL_EXCLUDE` | 퍼널 단계 정의 |
| `CHANNELS` / `DEPARTMENTS` / `INQUIRY_REASONS` | 드롭다운 선택지 |
| `DEFAULT_CATALOG` | 견적서 상품·가격 카탈로그 초기값 |
| `USE_SAMPLE_DATA` | 데모 샘플 생성 여부 |
