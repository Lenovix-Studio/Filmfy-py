import os
import random
import time
from urllib.parse import quote
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import base64
from typing import List, Optional
from starlette.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from bs4 import BeautifulSoup
import subprocess
import uuid
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as SeleniumChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExtractRequest(BaseModel):
    code: Optional[str] = None
    trailer_url: Optional[str] = None


class ExtractResponse(BaseModel):
    code: str = ""
    title: str = ""
    overview: str = ""
    director: str = ""
    studio: str = ""
    label: str = ""
    country: str = "Japan"
    language: str = "Japanese"
    release_date: str = ""
    cast: str = ""
    genres: str = ""
    series: str = ""
    runtime_minutes: int = 0
    rating: float = 0.0
    cover_url: str = ""
    gallery_urls: List[str] = []
    trailer_url: str = ""


def create_driver():
    options = uc.ChromeOptions()
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    headless = os.getenv("CHROME_HEADLESS", "false").lower() == "true"
    if headless:
        options.add_argument("--headless=new")
    driver = uc.Chrome(options=options)
    return driver


def create_trailer_driver():
    options = SeleniumChromeOptions()
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    service = ChromeService(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def scrape_javlibrary(query_code: str, max_retries: int = 2) -> ExtractResponse:
    cleaned = query_code.strip()
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        target_url = cleaned
    else:
        target_url = (
            f"https://www.javlibrary.com/en/vl_searchbyid.php?keyword={quote(cleaned)}"
        )

    attempt = 0
    last_error = ""

    while attempt < max_retries:
        attempt += 1
        driver = None
        try:
            driver = create_driver()
            driver.get(target_url)

            time.sleep(random.uniform(5, 7))

            try:
                agree_button = WebDriverWait(driver, 4).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "input.btnAdultAgree"))
                )
                agree_button.click()
                time.sleep(2)
            except Exception:
                pass

            curr_url = driver.current_url
            if "vl_searchbyid.php" in curr_url or "vl_search" in curr_url:
                try:
                    first_video = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable(
                            (By.CSS_SELECTOR, "div.videos div.video a")
                        )
                    )
                    first_video.click()
                    time.sleep(3)
                except Exception:
                    pass

            soup = BeautifulSoup(driver.page_source, "html.parser")

            # 1. Title
            title_element = soup.select_one("div#video_title h3.post-title.text a")
            title = title_element.get_text(strip=True) if title_element else ""

            # 2. Cover
            cover_element = soup.find("img", id="video_jacket_img") or soup.select_one(
                "img.imageresize"
            )
            cover = (
                str(cover_element.get("src"))
                if cover_element and cover_element.get("src")
                else ""
            )
            if cover.startswith("//"):
                cover = "https:" + cover

            # 3. ID / Code
            id_element = soup.select_one("div#video_id td.text")
            film_id = id_element.get_text(strip=True) if id_element else cleaned

            # 4. Release Date
            date_element = soup.select_one("div#video_date td.text")
            release_date = date_element.get_text(strip=True) if date_element else ""

            # 5. Director
            director_element = soup.select_one("div#video_director td.text")
            director = director_element.get_text(strip=True) if director_element else ""

            # 6. Maker / Studio
            maker_element = soup.select_one("div#video_maker td.text")
            studio = maker_element.get_text(strip=True) if maker_element else ""

            # 7. Label
            label_element = soup.select_one("div#video_label td.text")
            label = label_element.get_text(strip=True) if label_element else ""

            # 8. Genres
            genre_elements = soup.select("div#video_genres span.genre a")
            genres = ", ".join(
                [
                    g.get_text(strip=True)
                    for g in genre_elements
                    if g.get_text(strip=True)
                ]
            )

            # 9. Cast
            cast_elements = soup.select("div#video_cast span.cast span.star a")
            cast = ", ".join(
                [
                    c.get_text(strip=True)
                    for c in cast_elements
                    if c.get_text(strip=True)
                ]
            )

            # 10. Previews / Gallery
            preview_elements = soup.select("div.previewthumbs a")
            gallery_urls = []
            for p in preview_elements:
                href = p.get("href")
                if href and ("jp" in str(href) or "jpg" in str(href)):
                    full_preview = str(href)
                    if full_preview.startswith("//"):
                        full_preview = "https:" + full_preview
                    gallery_urls.append(full_preview)

            if not title and not cover and film_id == cleaned:
                raise ValueError("Video details not found on page")

            local_cover_url = ""
            if cover:
                cover_filename = f"cover_{film_id}_{uuid.uuid4().hex[:6]}.jpg"
                cover_path = os.path.join(TEMP_IMAGE_DIR, cover_filename)
                if download_image_in_browser(driver, cover, cover_path):
                    local_cover_url = f"/temp-image/{cover_filename}"
                else:
                    local_cover_url = cover

            local_gallery_urls = []
            for idx, g_url in enumerate(gallery_urls):
                g_filename = f"gallery_{film_id}_{idx}_{uuid.uuid4().hex[:6]}.jpg"
                g_path = os.path.join(TEMP_IMAGE_DIR, g_filename)
                if download_image_in_browser(driver, g_url, g_path):
                    local_gallery_urls.append(f"/temp-image/{g_filename}")
                else:
                    local_gallery_urls.append(g_url)

            return ExtractResponse(
                code=film_id,
                title=title,
                overview="",
                director=director,
                studio=studio,
                label=label,
                country="Japan",
                language="Japanese",
                release_date=release_date,
                cast=cast,
                genres=genres,
                series="",
                runtime_minutes=0,
                rating=0.0,
                cover_url=local_cover_url,
                gallery_urls=local_gallery_urls,
            )

        except Exception as e:
            last_error = str(e)
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

        if attempt < max_retries:
            time.sleep(3)

    raise HTTPException(
        status_code=400, detail=f"Failed to scrape javlibrary: {last_error}"
    )


TEMP_TRAILER_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "temp_trailers"
)
os.makedirs(TEMP_TRAILER_DIR, exist_ok=True)
TEMP_IMAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_images")
os.makedirs(TEMP_IMAGE_DIR, exist_ok=True)


def download_image_in_browser(driver, image_url: str, output_path: str) -> bool:
    try:
        base64_data = driver.execute_async_script(
            """
            var callback = arguments[arguments.length - 1];
            var imgUrl = arguments[0];
            fetch(imgUrl)
                .then(r => {
                    if (!r.ok) throw new Error("HTTP " + r.status);
                    return r.blob();
                })
                .then(blob => {
                    var reader = new FileReader();
                    reader.onloadend = function() {
                        var b64 = reader.result.split(',')[1];
                        callback(b64);
                    };
                    reader.readAsDataURL(blob);
                })
                .catch(err => {
                    callback(null);
                });
        """,
            image_url,
        )

        if base64_data:
            with open(output_path, "wb") as f:
                f.write(base64.b64decode(base64_data))
            return True
    except Exception as e:
        print(f"Error in-browser image download: {e}")

    try:
        cmd = [
            "curl.exe",
            "-s",
            "-L",
            "-e",
            "https://www.dmm.co.jp/",
            image_url,
            "-o",
            output_path,
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if (
            res.returncode == 0
            and os.path.exists(output_path)
            and os.path.getsize(output_path) > 500
        ):
            return True
    except Exception:
        pass
    return False


def download_trailer(trailer_page_url: str) -> Optional[str]:
    url = trailer_page_url.strip()
    if not url:
        return None

    driver = None
    try:
        print(f"\n[TRAILER] Mulai download trailer dari: {url}")
        driver = create_trailer_driver()
        driver.get(url)

        video_id = url.strip("/").split("/")[-1] or uuid.uuid4().hex[:8]
        output_filename = f"trailer_{video_id}_{uuid.uuid4().hex[:6]}.mp4"
        output_filepath = os.path.join(TEMP_TRAILER_DIR, output_filename)

        wait = WebDriverWait(driver, 10)
        try:
            play_button = wait.until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "button.vjs-big-play-button")
                )
            )
            play_button.click()
            print("[TRAILER] Tombol play diklik")
        except Exception as e:
            print(f"[TRAILER] Tombol play tidak ditemukan / lewat: {e}")

        time.sleep(5)

        logs = driver.get_log("performance")
        m3u8_url = None

        for entry in logs:
            try:
                log_data = json.loads(entry["message"])["message"]
                if log_data["method"] == "Network.requestWillBeSent":
                    request_url = log_data["params"]["request"]["url"]
                    if ".m3u8" in request_url and (
                        "mmb.m3u8" in request_url or "hmb.m3u8" in request_url
                    ):
                        m3u8_url = request_url
                        break
            except Exception:
                continue

        if not m3u8_url:
            print("[TRAILER] M3U8 url belum tertangkap")
            return None

        print(f"[TRAILER] Ditemukan m3u8 url: {m3u8_url}")
        base_url = m3u8_url.rsplit("/", 1)[0] + "/"
        driver.set_script_timeout(300)

        video_base64_data = driver.execute_async_script(
            """
            var callback = arguments[arguments.length - 1];
            var m3u8Url = arguments[0];
            var baseUrl = arguments[1];
            
            async function downloadAndProcess() {
                try {
                    let response = await fetch(m3u8Url);
                    let text = await response.text();
                    let lines = text.split('\\n');
                    let tsFiles = [];
                    
                    for (let line of lines) {
                        line = line.trim();
                        if (line && !line.startsWith('#')) {
                            tsFiles.push(line);
                        }
                    }
                    
                    let blobs = [];
                    for (let file of tsFiles) {
                        let tsUrl = baseUrl + file;
                        let tsRes = await fetch(tsUrl);
                        let tsBlob = await tsRes.blob();
                        blobs.push(tsBlob);
                    }
                    
                    let finalBlob = new Blob(blobs, { type: 'video/mp4' });
                    let reader = new FileReader();
                    reader.readAsDataURL(finalBlob); 
                    reader.onloadend = function() {
                        let base64data = reader.result.split(',')[1];
                        callback(base64data);
                    }
                } catch (e) {
                    console.error(e);
                    callback(null);
                }
            }
            
            downloadAndProcess();
        """,
            m3u8_url,
            base_url,
        )

        if video_base64_data:
            binary_data = base64.b64decode(video_base64_data)
            with open(output_filepath, "wb") as f:
                f.write(binary_data)
            print(
                f"[TRAILER] File video tersimpan: {output_filepath} ({len(binary_data)} bytes)"
            )
            return output_filename
        else:
            print("[TRAILER] Gagal menggabungkan segmen video melalui browser")
    except Exception as e:
        print(f"[TRAILER] Error download_trailer: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
    return None


def process_extract(request: ExtractRequest) -> ExtractResponse:
    res = ExtractResponse()
    code_clean = request.code.strip() if request.code else ""
    trailer_clean = request.trailer_url.strip() if request.trailer_url else ""

    if code_clean:
        res = scrape_javlibrary(code_clean)
    elif trailer_clean:
        guessed_code = trailer_clean.strip("/").split("/")[-1].upper()
        res.code = guessed_code
        res.title = guessed_code

    if trailer_clean:
        trailer_filename = download_trailer(trailer_clean)
        if trailer_filename:
            res.trailer_url = f"/trailer-file/{trailer_filename}"

    return res


@app.get("/trailer-file/{filename}")
async def get_trailer_file(filename: str):
    safe_filename = os.path.basename(filename)
    filepath = os.path.join(TEMP_TRAILER_DIR, safe_filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Trailer file not found")
    return FileResponse(filepath, media_type="video/mp4", filename=safe_filename)


@app.get("/temp-image/{filename}")
async def get_temp_image(filename: str):
    safe_filename = os.path.basename(filename)
    filepath = os.path.join(TEMP_IMAGE_DIR, safe_filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(filepath, media_type="image/jpeg", filename=safe_filename)


@app.post("/extract", response_model=ExtractResponse)
async def extract_metadata(request: ExtractRequest):
    code_clean = request.code.strip() if request.code else ""
    trailer_clean = request.trailer_url.strip() if request.trailer_url else ""

    if not code_clean and not trailer_clean:
        raise HTTPException(status_code=400, detail="Minimal isi Code atau Trailer URL")

    return await run_in_threadpool(process_extract, request)


class ConvertVideoRequest(BaseModel):
    file_path: str
    delete_source: bool = True


class ConvertVideoResponse(BaseModel):
    success: bool
    output_path: str
    message: str = ""


def run_ffmpeg_convert(input_path: str, delete_source: bool = True) -> str:
    if not os.path.exists(input_path):
        raise HTTPException(
            status_code=404, detail=f"Source video not found: {input_path}"
        )

    base, ext = os.path.splitext(input_path)
    output_path = f"{base}_compressed_{uuid.uuid4().hex[:6]}.mp4"

    cmd_compress = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-c:v",
        "libx264",
        "-crf",
        "22",
        "-preset",
        "medium",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        output_path,
    ]

    res = subprocess.run(cmd_compress, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        err = res.stderr.decode("utf-8", errors="ignore")
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass
        raise HTTPException(
            status_code=500, detail=f"FFmpeg compression failed: {err[-500:]}"
        )

    if delete_source and os.path.exists(input_path):
        try:
            os.remove(input_path)
        except Exception:
            pass

    return output_path


@app.post("/convert-video", response_model=ConvertVideoResponse)
async def convert_video(req: ConvertVideoRequest):
    if not req.file_path:
        raise HTTPException(status_code=400, detail="file_path is required")

    output_file = await run_in_threadpool(
        run_ffmpeg_convert, req.file_path, req.delete_source
    )
    return ConvertVideoResponse(
        success=True,
        output_path=output_file,
        message="Video converted to MP4 successfully without losing resolution",
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
