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
    
    title_elem = soup.find('h1', class_='title')
    if title_elem:
        result.title = title_elem.get_text(strip=True)
    
    code_match = re.search(r'([A-Z]+-\d+)', result.title or url)
    if code_match:
        result.code = code_match.group(1)
    
    info_section = soup.find('div', class_='video-info')
    if info_section:
        rows = info_section.find_all('div', class_='row')
        for row in rows:
            label = row.find('span', class_='text')
            value_div = row.find('div')
            
            if not label or not value_div:
                continue
            
            label_text = label.get_text(strip=True).lower()
            value_text = value_div.get_text(strip=True)
            
            if 'director' in label_text:
                result.director = value_text
            elif 'studio' in label_text:
                result.studio = value_text
            elif 'label' in label_text:
                result.label = value_text
            elif 'release' in label_text or 'date' in label_text:
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', value_text)
                if date_match:
                    result.release_date = date_match.group(1)
    
    genres_section = soup.find('div', class_='genre')
    if genres_section:
        genre_links = genres_section.find_all('a')
        genres = [g.get_text(strip=True) for g in genre_links]
        result.genres = ', '.join(genres)
    
    cast_section = soup.find('div', class_='cast')
    if cast_section:
        cast_links = cast_section.find_all('a')
        cast = [c.get_text(strip=True) for c in cast_links]
        result.cast = ', '.join(cast)
    
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
