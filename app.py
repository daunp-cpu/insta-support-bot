import os
import json
import asyncio
import traceback
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
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
HISTORY_FILE = os.path.join(BASE_DIR, "comment_history.json")
KST = timezone(timedelta(hours=9))

# Meta API 연동 설정
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "EAARZCr1VmbggBS5MOA5RjWwJ3PW8EyitDtUP3PG1LaLUam4aXvde8saLq2lXkRyrZB6ACHAXRxBSiurQ84IT5D9S3fcdxRVZBOFIrK7nOI7DriGUaAqBZAdOuZCiFdD03i7IHvp0vZC6Y6JjR35ixqTEArVTy8v8BiURZCTPhvWymYXZBde8SZC9IfgiRgwk3IMaNBolSUyaBV7ojQWA6J2bYTZBhYRZCgcau5ib7eNWRJyZBYfXlsDZBiFZA8ViF4q4CTSZC4V5SJSubR0D5USzewria5YuAZDZD")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "1363134018754563")

AD_CACHE = {
    "last_updated": None,
    "ads": []
}

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
    },
    "acc_5": {
        "name": "이상훈 (30대/남)",
        "state_file": os.path.join(BASE_DIR, "state_lee_sh.json")
    }
}

class CommentRequest(BaseModel):
    account_id: str
    post_url: str
    comment_text: str

class DeleteRequest(BaseModel):
    account_id: str
    post_url: str
    comment_text: str

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def fetch_meta_wm_ads():
    """Meta Graph API에서 WM 캠페인 광고 소재와 썸네일(미리보기)을 전수 수집"""
    base_url = f"https://graph.facebook.com/v19.0/act_{META_AD_ACCOUNT_ID}/ads"
    params = {
        "fields": "id,name,status,creative{id,name,instagram_permalink_url,effective_object_story_id,thumbnail_url,image_url},campaign{id,name}",
        "limit": "200",
        "access_token": META_ACCESS_TOKEN
    }

    next_url = f"{base_url}?{urllib.parse.urlencode(params)}"
    seen_urls = set()
    cleaned_ads = []
    page_count = 0

    while next_url and page_count < 10:
        page_count += 1
        req = urllib.request.Request(next_url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                data = json.loads(res.read().decode("utf-8"))
        except Exception as e:
            print(f"[Meta API Page {page_count} Error] {e}")
            break

        raw_items = data.get("data", [])
        if not raw_items:
            break

        for item in raw_items:
            camp = item.get("campaign", {})
            camp_name = camp.get("name", "")

            if "WM" not in camp_name.upper():
                continue

            creative = item.get("creative", {})
            post_url = creative.get("instagram_permalink_url", "")

            if not post_url and creative.get("effective_object_story_id"):
                story_id = creative.get("effective_object_story_id")
                if "_" in story_id:
                    media_id = story_id.split("_")[1]
                    post_url = f"https://www.instagram.com/p/{media_id}/"

            if not post_url or post_url in seen_urls:
                continue

            seen_urls.add(post_url)

            # 썸네일 URL 추출 (동영상 썸네일 또는 이미지 소재 URL)
            thumbnail = creative.get("thumbnail_url") or creative.get("image_url") or ""

            cleaned_ads.append({
                "ad_id": item.get("id"),
                "ad_name": item.get("name"),
                "campaign_name": camp_name,
                "post_url": post_url,
                "thumbnail_url": thumbnail
            })

        paging = data.get("paging", {})
        next_url = paging.get("next")

    print(f"[Meta Sync] 총 {len(cleaned_ads)}개의 WM 광고 소재 수집 완료 ({page_count}페이지)")
    AD_CACHE["ads"] = cleaned_ads
    AD_CACHE["last_updated"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    return cleaned_ads

async def schedule_ad_sync_loop():
    while True:
        try:
            fetch_meta_wm_ads()
            print(f"[Auto Sync] WM Ads updated at {AD_CACHE['last_updated']} (Total: {len(AD_CACHE['ads'])})")
        except Exception as e:
            print(f"[Auto Sync Error] {e}")
        await asyncio.sleep(5 * 3600)

@app.on_event("startup")
async def startup_event():
    fetch_meta_wm_ads()
    asyncio.create_task(schedule_ad_sync_loop())

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

@app.get("/api/meta-ads")
def get_meta_ads():
    if not AD_CACHE["ads"]:
        fetch_meta_wm_ads()
    return {
        "last_updated": AD_CACHE["last_updated"],
        "count": len(AD_CACHE["ads"]),
        "ads": AD_CACHE["ads"]
    }

@app.post("/api/meta-ads/refresh")
def refresh_meta_ads():
    ads = fetch_meta_wm_ads()
    return {
        "status": "success",
        "last_updated": AD_CACHE["last_updated"],
        "count": len(ads),
        "ads": ads
    }

@app.get("/api/history")
def get_history_summary():
    history = load_history()
    today_str = datetime.now(KST).strftime("%Y-%m-%d")

    total_counts = {k: 0 for k in ACCOUNTS.keys()}
    today_counts = {k: 0 for k in ACCOUNTS.keys()}

    for item in history:
        acc = item.get("account_id")
        created_at = item.get("created_at", "")
        if acc in total_counts:
            total_counts[acc] += 1
            if created_at.startswith(today_str):
                today_counts[acc] += 1

    return {
        "total_counts": total_counts,
        "today_counts": today_counts,
        "history": list(reversed(history[-50:]))
    }

@app.post("/api/comment")
async def send_comment(req: CommentRequest):
    if req.account_id not in ACCOUNTS:
        raise HTTPException(status_code=400, detail="존재하지 않는 계정입니다.")

    acc_info = ACCOUNTS[req.account_id]
    state_file = acc_info["state_file"]

    if not os.path.exists(state_file):
        raise HTTPException(status_code=400, detail=f"[{acc_info['name']}] 세션 파일({os.path.basename(state_file)})을 찾을 수 없습니다.")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-gpu"
                ]
            )

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

                for sel in ["svg[aria-label='닫기']", "button:has-text('닫기')", "button:has-text('나중에 하기')", "button:has-text('Not Now')"]:
                    btn = page.locator(sel)
                    if await btn.count() > 0:
                        try:
                            await btn.first.click(timeout=1500)
                            await asyncio.sleep(1)
                        except Exception:
                            pass

                icons = page.locator("svg[aria-label*='댓글'], svg[aria-label*='Comment']").locator("..")
                if await icons.count() > 0:
                    try:
                        await icons.first.click(timeout=2000)
                        await asyncio.sleep(2)
                    except Exception:
                        pass

                box = page.locator("textarea, div[role='textbox']")
                if await box.count() == 0:
                    debug_img = os.path.join(BASE_DIR, "debug_error.png")
                    await page.screenshot(path=debug_img, full_page=True)
                    raise HTTPException(status_code=400, detail="댓글 창을 찾지 못했습니다. /debug-screen 에서 확인하세요.")

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

                now_kst = datetime.now(KST)
                history = load_history()
                history.append({
                    "id": int(now_kst.timestamp() * 1000),
                    "account_id": req.account_id,
                    "account_name": acc_info["name"],
                    "post_url": req.post_url,
                    "comment_text": req.comment_text,
                    "created_at": now_kst.strftime("%Y-%m-%d %H:%M:%S")
                })
                save_history(history)

            finally:
                await context.close()
                await browser.close()

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서버 실행 오류: {str(e)}")

    return {"status": "success", "message": f"{acc_info['name']} 댓글 작성이 완료되었습니다!"}

@app.post("/api/delete-comment")
async def delete_comment(req: DeleteRequest):
    if req.account_id not in ACCOUNTS:
        raise HTTPException(status_code=400, detail="존재하지 않는 계정입니다.")

    acc_info = ACCOUNTS[req.account_id]
    state_file = acc_info["state_file"]

    if not os.path.exists(state_file):
        raise HTTPException(status_code=400, detail="세션 파일이 없습니다.")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = await browser.new_context(storage_state=state_file, viewport={"width": 1440, "height": 900})
            page = await context.new_page()

            try:
                await page.goto(req.post_url, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(3)

                comment_node = page.locator(f"span:has-text('{req.comment_text}')").first
                if await comment_node.count() == 0:
                    raise HTTPException(status_code=404, detail="해당 댓글을 게시물에서 찾을 수 없습니다.")

                await comment_node.hover()
                await asyncio.sleep(1)

                more_btn = comment_node.locator("xpath=ancestor::ul | ancestor::li | ancestor::div[contains(@role, 'button')]").locator("svg[aria-label*='옵션'], svg[aria-label*='More'], svg[aria-label*='더보기']").first
                if await more_btn.count() > 0:
                    await more_btn.click()
                else:
                    await page.locator("svg[aria-label*='옵션'], svg[aria-label*='More'], svg[aria-label*='더보기']").first.click()
                
                await asyncio.sleep(1)

                delete_btn = page.locator("button:has-text('삭제'), div[role='button']:has-text('삭제')")
                if await delete_btn.count() > 0:
                    await delete_btn.first.click()
                    await asyncio.sleep(2)
                else:
                    raise HTTPException(status_code=400, detail="삭제 메뉴를 누르지 못했습니다.")

                history = load_history()
                history = [h for h in history if not (h.get("post_url") == req.post_url and h.get("comment_text") == req.comment_text)]
                save_history(history)

            finally:
                await context.close()
                await browser.close()

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"삭제 실패: {str(e)}")

    return {"status": "success", "message": "댓글이 삭제되었습니다."}
    