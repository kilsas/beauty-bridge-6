# 웹사이트 공개하기 (GitHub Pages + 리뷰 저장소)

GitHub Pages는 파일만 보여주는 곳이라, 리뷰를 저장할 곳이 따로 필요해요.
**Supabase**(무료 요금제 있음)를 연결하면 누구나 로그인 없이 리뷰를 남기고,
남기는 즉시 모든 방문자의 순위가 바뀌어요.

## 1. GitHub에 올리기
1. GitHub에서 새 저장소를 만들어요 (예: `beauty-bridge`).
2. 이 폴더 전체를 올려요.
   ```bash
   cd beauty-bridge
   git init && git add . && git commit -m "Beauty Bridge"
   git branch -M main
   git remote add origin https://github.com/<내아이디>/beauty-bridge.git
   git push -u origin main
   ```
3. 저장소 **Settings → Pages → Source**를 **GitHub Actions**로 바꿔요.
   이제 `main`에 올릴 때마다 사이트가 `https://<내아이디>.github.io/beauty-bridge/`에 자동 배포돼요.
   (이 단계까지만 하면 리뷰 없이 나머지 기능은 다 작동해요.)

## 2. 리뷰 저장소 만들기 (Supabase)
1. https://supabase.com 에서 가입하고 **New project**를 만들어요.
2. 왼쪽 **SQL Editor → New query**에 `supabase/setup.sql` 내용을 붙여 넣고 **Run**.
   리뷰 표, "누구나 읽고 자기 리뷰만 수정" 규칙, 실시간 알림이 한 번에 만들어져요.
3. **Authentication → Sign In / Providers**에서 **Anonymous sign-ins**를 켜요.
   (방문자가 가입 없이 리뷰를 남길 수 있게 해 줘요.)
4. **Project Settings → API**에서 두 값을 복사해요.
   - Project URL (예: `https://abcd.supabase.co`)
   - `anon` `public` 키
   ⚠️ `service_role` 키는 절대 넣지 마세요. `anon` 키는 공개돼도 되도록 설계돼 있어요.

## 3. 사이트에 연결하기
GitHub 저장소 **Settings → Secrets and variables → Actions → Variables**에서
- `SUPABASE_URL` = Project URL
- `SUPABASE_ANON_KEY` = anon public 키

를 추가하고, **Actions → pages → Run workflow**를 눌러 다시 배포해요.
끝나면 사이트의 리뷰 탭에서 바로 리뷰를 남길 수 있어요.

직접 테스트할 때는 `web/config.example.json`을 `web/config.json`으로 복사해
값을 넣고 `python scripts/build_site.py`를 실행한 뒤 `web/index.html`을 열면 돼요.

## 자체 서버를 쓰고 싶다면
`uvicorn beautybridge.api:app`을 Render, Railway 같은 곳에 올리고,
`BEAUTYBRIDGE_CORS=https://<내아이디>.github.io` 환경 변수를 설정한 뒤
저장소 변수 `REVIEWS_API_URL`에 서버 주소를 넣으면 돼요.
(이 방식은 로그인 없이 브라우저별 익명 ID로 리뷰를 구분해요.)

## 운영할 때 알아둘 점
- **스팸**: 익명 리뷰는 누구나 쓸 수 있어요. 사람이 많아지면 Supabase의
  익명 로그인 속도 제한과 CAPTCHA(Authentication → Attack Protection)를 켜 두세요.
- **삭제**: 부적절한 리뷰는 Supabase **Table Editor → reviews**에서 지울 수 있어요.
- **개인정보**: 리뷰에는 이름이나 이메일을 저장하지 않아요. 익명 ID만 남아요.

## 구매하기 버튼과 구매 클릭 순위
제품 페이지마다 나라별 공식 판매처 버튼이 있어요
(한국 올리브영·쿠팡, 미국 Amazon·Sephora·Ulta, 일본 라쿠텐·Amazon Japan, 중국 티몰·징둥).
누르면 그 판매처의 제품 검색 결과가 새 탭으로 열려요.

**클릭 기록 켜기 (한 번만)**: Supabase **SQL Editor → New query**에 `supabase/buy_clicks.sql`을
붙여 넣고 **Run**. 이후 랭킹의 **구매 인기** 탭에 "구매 버튼을 누른 사람 수" 순위가 나와요.
- 한 사람이 여러 번 눌러도 1명으로 세요. 방문자는 남의 클릭 기록을 볼 수 없고 합계만 보여요.
- 연구용 원자료: Supabase **Table Editor → buy_clicks → Export → CSV**
  (visitor_id, product_id, store, market, created_at). 리뷰도 같은 방법으로 내려받을 수 있어요.

**판매처 바꾸기**: `data/stores.json`에서 이름과 검색 주소(`{q}` 자리에 제품명이 들어가요)를 고쳐요.

**제휴 링크로 바꾸기 (수수료 받기)**
- 판매처 전체에 붙이는 방식(예: Amazon Associates): `stores.json`의 해당 판매처에
  `"append": "&tag=내태그-20"`, `"affiliate": true`를 넣어요.
- 제품마다 받은 링크(예: 쿠팡 파트너스): `data/real/buy_links.csv`에
  `product_id,store,url,affiliate` 형식으로 한 줄씩 넣어요. 예: `R004,coupang,https://link.coupang.com/a/xxxx,yes`
- 제휴 링크가 하나라도 있으면 제품 페이지에 "제휴 링크" 안내 문구가 자동으로 나와요.
  쿠팡 파트너스처럼 프로그램이 정한 문구가 있으면 `web/i18n.js`의 `affNote`를 그 문구로 바꾸세요.

## 브랜드 공식몰 버튼
구매하기 상자의 맨 앞 분홍 버튼은 브랜드 공식몰로 연결돼요(58개 브랜드, `data/real/brand_sites.csv`).
결제는 공식몰에서 이뤄지고, 이 사이트는 결제·개인정보를 다루지 않아요.
- 공식몰 검색 주소가 확인된 브랜드는 제품 검색 결과로 바로 열리고, 나머지는 공식몰 첫 화면이 열려요.
- 고른 나라에 공식몰이 없으면 가장 가까운 나라의 공식몰을 "· 미국"처럼 표시해서 보여줘요.
- `kind`: shop(브랜드 자체 몰), mall(그룹 공식몰, 예: 아모레몰), flagship(티몰·네이버 공식 스토어),
  info(직접 판매하지 않는 브랜드 사이트 — CANMAKE, KATE, CEZANNE, 하다라보, 3CE, 메이블린 미국 등).
- 주소는 2026-10-03에 확인했어요. 몰 주소가 바뀌면 이 CSV의 해당 줄만 고치면 돼요.
