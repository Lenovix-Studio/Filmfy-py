import os
import random
import time
from urllib.parse import quote
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from starlette.concurrency import run_in_threadpool
from bs4 import BeautifulSoup
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
    code: str

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

def scrape_javlibrary(query_code: str, max_retries: int = 2) -> ExtractResponse:
    cleaned = query_code.strip()
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        target_url = cleaned
    else:
        target_url = f"https://www.javlibrary.com/en/vl_searchbyid.php?keyword={quote(cleaned)}"

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
                        EC.element_to_be_clickable((By.CSS_SELECTOR, "div.videos div.video a"))
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
            cover_element = soup.find('img', id='video_jacket_img') or soup.select_one("img.imageresize")
            cover = str(cover_element.get('src')) if cover_element and cover_element.get('src') else ""
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
            genres = ", ".join([g.get_text(strip=True) for g in genre_elements if g.get_text(strip=True)])

            # 9. Cast
            cast_elements = soup.select("div#video_cast span.cast span.star a")
            cast = ", ".join([c.get_text(strip=True) for c in cast_elements if c.get_text(strip=True)])

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
                cover_url=cover,
                gallery_urls=gallery_urls,
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

    raise HTTPException(status_code=400, detail=f"Failed to scrape javlibrary: {last_error}")

@app.post("/extract", response_model=ExtractResponse)
async def extract_metadata(request: ExtractRequest):
    if not request.code:
        raise HTTPException(status_code=400, detail="Code is required")

    return await run_in_threadpool(scrape_javlibrary, request.code)

@app.get("/health")
async def health():
    return {"status": "ok"}