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
