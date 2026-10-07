from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import re
import os
from dotenv import load_dotenv
import cloudscraper
import undetected_chromedriver as uc
import time

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ExtractRequest(BaseModel):
    url: str

class ExtractResponse(BaseModel):
    code: str = ""
    title: str = ""
    director: str = ""
    studio: str = ""
    label: str = ""
    country: str = ""
    language: str = ""
    release_date: str = ""
    cast: str = ""
    genres: str = ""

def extract_javlibrary(url: str) -> ExtractResponse:
    options = uc.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    driver = None
    try:
        driver = uc.Chrome(options=options, version_main=154)
        driver.get(url)
        time.sleep(3)
        html = driver.page_source
    except Exception as e:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        try:
            requests.post(f"{os.getenv('BACKEND_URL')}/settings/logs", json={
                'level': 'ERROR',
                'message': str(e),
                'source': 'scraper',
            })
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {str(e)}")
    finally:
        if driver:
            driver.quit()
    
    soup = BeautifulSoup(html, 'html.parser')
    result = ExtractResponse()
    
    result.country = "Japan"
    result.language = "Japanese"
    
    # Title
    title_elem = soup.select_one('#video_title a') or soup.find('h3')
    if title_elem:
        result.title = title_elem.get_text(strip=True)
    
    # Info Section
    video_info = soup.find('div', id='video_info')
    if video_info:
        def get_info_text(label_id):
            row = video_info.find('div', id=label_id)
            if row:
                val = row.find('td', class_='text')
                return val.get_text(strip=True) if val else ""
            return ""

        result.code = get_info_text('video_id')
        result.release_date = get_info_text('video_date')
        result.director = get_info_text('video_director')
        result.studio = get_info_text('video_maker')
        result.label = get_info_text('video_label')

        # Cast
        cast_row = video_info.find('div', id='video_cast')
        if cast_row:
            casts = [a.get_text(strip=True) for a in cast_row.find_all('a')]
            result.cast = ', '.join(casts)

        # Genres
        genre_row = video_info.find('div', id='video_genres')
        if genre_row:
            genres = [a.get_text(strip=True) for a in genre_row.find_all('a')]
            result.genres = ', '.join(genres)
    
    return result

@app.post("/extract", response_model=ExtractResponse)
async def extract_metadata(request: ExtractRequest):
    if not request.url:
        raise HTTPException(status_code=400, detail="URL is required")
    
    domain = urlparse(request.url).netloc.lower()
    
    if 'javlibrary' in domain:
        return extract_javlibrary(request.url)
    else:
        raise HTTPException(status_code=400, detail="Unsupported domain")

@app.get("/health")
async def health():
    return {"status": "ok"}
