import os
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
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

ACCOUNTS = {
    "acc_1": {
        "name": "오미영 (50대/여)",
        "state_file": os.path.join(BASE_DIR, "state_omiyoung.json")
    },
    "acc_2": {
        "name": "황지석 (30대/남)",
        "state_file": os.path.join(BASE_DIR, "state_hwang.json")
    },
    "acc_3": {
        "name": "김현지 (20대/여)",
        "state_file": os.path.join(BASE_DIR, "state_kim_hj.json")
    },
    "acc_4": {
        "name": "김일미 (30대/여)",
        "state_file": os.path.join(BASE_DIR, "state_kim_im.json")
    }
}

class CommentRequest(BaseModel):
    account_id: str
    post_url: str
    comment_text: str

@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    html_file = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(html_file):
        with open(html_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>index.html 파일을 찾을 수 없습니다.</h1>"

@app.get("/debug-screen")
def get_debug_screen():
    debug_path = os.path.join(BASE_DIR, "debug_error.png")
    if os.path.exists(debug_path):
        return FileResponse(debug_path, media_type="image/png")
    return HTMLResponse("<h3>아직 캡처된 화면이 없습니다.</h3>")

@app.get("/api/accounts")
def get_accounts():
    return [{"id": k, "name": v["name"]} for k, v in ACCOUNTS.items()]

@app.post("/api/comment")
async def send_comment(req: CommentRequest):
    if req.account_id not in ACCOUNTS:
        raise HTTPException(status_code=400, detail="존재하지 않는 계정입니다.")

    acc_info = ACCOUNTS[req.account_id]
    state_file = acc_info["state_file"]

    if not os.path.exists(state_file):
        raise HTTPException(status_code=400, detail=f"[{acc_info['name']}] 세션 파일({os.path.basename(state_file)})이 서버에 없습니다.")

    async with async_playwright() as p:
        # 1. 브라우저 시작
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-gpu"
            ]
        )

        # 2. 저장된 쿠키(JSON)를 완벽하게 로드하여 브라우저 컨텍스트 생성
        context = await browser.new_context(
            storage_state=state_file,
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        try:
            await page.goto(req.post_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)

            # 방해 팝업 닫기
            popup_selectors = [
                "svg[aria-label='닫기']",
                "button:has-text('닫기')",
                "button:has-text('나중에 하기')",
                "button:has-text('Not Now')",
                "div[role='dialog'] button:has-text('취소')"
            ]
            for sel in popup_selectors:
                btn = page.locator(sel)
                if await btn.count() > 0:
                    try:
                        await btn.first.click(timeout=1500)
                        await asyncio.sleep(1)
                    except Exception:
                        pass

            # 말풍선(댓글 아이콘) 클릭 시도
            icons = page.locator("svg[aria-label*='댓글'], svg[aria-label*='Comment']").locator("..")
            if await icons.count() > 0:
                try:
                    await icons.first.click(timeout=2000)
                    await asyncio.sleep(2)
                except Exception:
                    pass

            # 댓글 입력창 탐색
            box = page.locator("textarea, div[role='textbox']")
            count = await box.count()

            if count == 0:
                debug_img = os.path.join(BASE_DIR, "debug_error.png")
                await page.screenshot(path=debug_img, full_page=True)
                raise HTTPException(
                    status_code=400,
                    detail="댓글 창을 찾지 못했습니다. /debug-screen 에서 화면을 확인하세요."
                )

            # 댓글 작성 및 게시
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
            await browser.close()

    return {"status": "success", "message": f"{acc_info['name']} 댓글 작성이 성공적으로 완료되었습니다!"}
    