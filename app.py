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

# 4개 계정 정의
ACCOUNTS = {
    "acc_1": {
        "name": "오미영 (50대 계정)",
        "dir": os.path.join(PROFILES_ROOT, "profile_omiyoung")
    },
    "acc_2": {
        "name": "황지석",
        "dir": os.path.join(PROFILES_ROOT, "profile_hwang")
    },
    "acc_3": {
        "name": "김현지",
        "dir": os.path.join(PROFILES_ROOT, "profile_kim_hj")
    },
    "acc_4": {
        "name": "김일미",
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

# 웹 프론트엔드에서 등록된 계정 목록을 자동으로 가져갈 수 있는 API
@app.get("/api/accounts")
def get_accounts():
    return [{"id": k, "name": v["name"]} for k, v in ACCOUNTS.items()]

@app.get("/api/login/{account_id}")
async def login_helper(account_id: str):
    if account_id not in ACCOUNTS:
        raise HTTPException(status_code=400, detail="존재하지 않는 계정입니다.")

    account_dir = ACCOUNTS[account_id]["dir"]
    os.makedirs(account_dir, exist_ok=True)
    force_cleanup_profile(account_dir)

    async with async_playwright() as p:
        # 서버 환경(리눅스)에서는 모니터가 없으므로 headless=True 필수
        context = await p.chromium.launch_persistent_context(
            user_data_dir=account_dir,
            headless=True,
            viewport={"width": 1280, "height": 800},
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--remote-debugging-port=0",
                "--disable-gpu"
            ]
        )
        page = await context.new_page()
        await page.goto("https://www.instagram.com/accounts/login/")

        try:
            await page.wait_for_timeout(60000)
        except Exception:
            pass
        finally:
            await context.close()

    return {"status": "success", "message": f"{ACCOUNTS[account_id]['name']} 세션 준비 완료"}

@app.post("/api/comment")
async def send_comment(req: CommentRequest):
    if req.account_id not in ACCOUNTS:
        raise HTTPException(status_code=400, detail="존재하지 않는 계정입니다.")

    account_dir = ACCOUNTS[req.account_id]["dir"]
    force_cleanup_profile(account_dir)

    async with async_playwright() as p:
        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=account_dir,
                headless=True,
                viewport={"width": 1280, "height": 800},
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--remote-debugging-port=0",
                    "--disable-gpu"
                ]
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"브라우저 실행 충돌: {str(e)}")

        page = await context.new_page()
        try:
            await page.goto(req.post_url, wait_until="load")
            await asyncio.sleep(4)

            # 팝업 닫기
            for pop_text in ["나중에 하기", "Not Now", "닫기"]:
                btn = page.locator(f"button:has-text('{pop_text}')")
                if await btn.count() > 0:
                    try:
                        await btn.first.click()
                        await asyncio.sleep(1)
                    except Exception:
                        pass

            # 댓글 입력창 탐색
            comment_box = page.locator("textarea[aria-label*='댓글'], textarea[placeholder*='댓글'], form textarea")
            
            if await comment_box.count() == 0:
                icon = page.locator("svg[aria-label='댓글 달기'], svg[aria-label='댓글']").locator("..")
                if await icon.count() > 0:
                    await icon.first.click()
                    await asyncio.sleep(2)
                    comment_box = page.locator("textarea[aria-label*='댓글'], textarea[placeholder*='댓글']")

            if await comment_box.count() == 0:
                raise HTTPException(status_code=400, detail="댓글 창을 찾지 못했습니다. 계정 로그인이 풀렸는지 확인하세요.")

            await comment_box.first.click()
            await asyncio.sleep(1)
            await comment_box.first.fill(req.comment_text)
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