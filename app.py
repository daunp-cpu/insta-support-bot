import os
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from playwright.async_api import async_playwright

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILES_ROOT = os.path.join(BASE_DIR, "bot_profiles")
os.makedirs(PROFILES_ROOT, exist_ok=True)

ACCOUNTS = {
    "acc_1": {
        "name": "오미영 (50대/여)",
        "dir": os.path.join(PROFILES_ROOT, "profile_omiyoung")
    },
    "acc_2": {
        "name": "황지석 (30대/남)",
        "dir": os.path.join(PROFILES_ROOT, "profile_hwang")
    },
    "acc_3": {
        "name": "김현지 (20대/여)",
        "dir": os.path.join(PROFILES_ROOT, "profile_kim_hj")
    },
    "acc_4": {
        "name": "김일미 (30대/여)",
        "dir": os.path.join(PROFILES_ROOT, "profile_kim_im")
    }
}

class CommentRequest(BaseModel):
    account_id: str
    post_url: str
    comment_text: str

def force_cleanup_profile(profile_dir: str):
    lock_names = ["SingletonLock", "SingletonSocket", "SingletonCookie", "lockfile"]
    for name in lock_names:
        target = os.path.join(profile_dir, name)
        try:
            if os.path.islink(target) or os.path.exists(target):
                os.unlink(target) if os.path.islink(target) else os.remove(target)
        except Exception:
            pass

@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    html_file = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(html_file):
        with open(html_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>index.html 파일을 찾을 수 없습니다.</h1>"

@app.get("/api/accounts")
def get_accounts():
    return [{"id": k, "name": v["name"]} for k, v in ACCOUNTS.items()]

@app.post("/api/comment")
async def send_comment(req: CommentRequest):
    if req.account_id not in ACCOUNTS:
        raise HTTPException(status_code=400, detail="존재하지 않는 계정입니다.")

    account_dir = ACCOUNTS[req.account_id]["dir"]
    force_cleanup_profile(account_dir)

    async with async_playwright() as p:
        try:
            # 로컬 테스트에서 성공했던 크기(1440x900)와 옵션을 그대로 적용
            context = await p.chromium.launch_persistent_context(
                user_data_dir=account_dir,
                headless=True,
                viewport={"width": 1440, "height": 900},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-gpu"
                ]
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"브라우저 실행 충돌: {str(e)}")

        page = context.pages[0] if context.pages else await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        try:
            await page.goto(req.post_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)

            # 1. 팝업 닫기
            for text in ["나중에 하기", "Not Now", "닫기"]:
                btn = page.locator(f"button:has-text('{text}')")
                if await btn.count() > 0:
                    try:
                        await btn.first.click(timeout=2000)
                        await asyncio.sleep(1)
                    except Exception:
                        pass

            # 2. 말풍선(댓글 아이콘) 클릭
            icons = page.locator("svg[aria-label*='댓글'], svg[aria-label*='Comment']").locator("..")
            if await icons.count() > 0:
                try:
                    await icons.first.click(timeout=2000)
                    await asyncio.sleep(2)
                except Exception:
                    pass

            # 3. 입력창 탐색
            box = page.locator("textarea, div[role='textbox']")
            count = await box.count()
            if count == 0:
                raise HTTPException(status_code=400, detail="댓글 창을 찾지 못했습니다. 계정 로그인이 풀렸는지 확인하세요.")

            # 4. 댓글 입력 및 게시
            target = box.first
            await target.click()
            await asyncio.sleep(1)
            await target.fill(req.comment_text)
            await asyncio.sleep(1)

            post_btn = page.locator("div[role='button']:has-text('게시'), button:has-text('게시')")
            if await post_btn.count() > 0 and await post_btn.first.is_visible():
                await post_btn.first.click()
            else:
                await page.keyboard.press("Enter")

            await asyncio.sleep(4)

        finally:
            await context.close()

    return {"status": "success", "message": "댓글 작성이 완료되었습니다!"}