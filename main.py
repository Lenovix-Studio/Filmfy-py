from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import re
import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from starlette.concurrency import run_in_threadpool

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
    def _scrape_sync():
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            ctx = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            )
            page = ctx.new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=45000)
            
            # poll until Cloudflare challenge cleared (max 120s)
            import time as _time
            deadline = _time.time() + 120
            while _time.time() < deadline:
                title = page.title()
                if "Just a moment" not in title and "Attention Required" not in title:
                    if page.query_selector('#video_title h3.post-title a'):
                        break
                page.wait_for_timeout(1000)
                
            page.wait_for_timeout(3000)
            html = page.content()
            ctx.close()
            browser.close()
            return html
    
    try:
        html = _scrape_sync()
    except Exception as e:
        try:
            requests.post(f"{os.getenv('BACKEND_URL')}/settings/logs", json={
                'level': 'ERROR',
                'message': str(e),
                'source': 'scraper',
                'request': {'url': url},
                'response': None,
            })
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {str(e)}")
    
    soup = BeautifulSoup(html, 'html.parser')
    result = ExtractResponse()
    
    result.country = "Japan"
    result.language = "Japanese"
    
    # Title
    title_elem = soup.select_one('#video_title h3.post-title a')
    if title_elem:
        result.title = title_elem.get_text(strip=True)
    
    # ID (Code)
    id_elem = soup.select_one('#video_id td.text')
    if id_elem:
        result.code = id_elem.get_text(strip=True)
    
    # Release Date
    date_elem = soup.select_one('#video_date td.text')
    if date_elem:
        result.release_date = date_elem.get_text(strip=True)
    
    # Director
    director_elem = soup.select_one('#video_director td.text a')
    if director_elem:
        result.director = director_elem.get_text(strip=True)
    
    # Studio (Maker)
    studio_elem = soup.select_one('#video_maker td.text a')
    if studio_elem:
        result.studio = studio_elem.get_text(strip=True)
    
    # Label
    label_elem = soup.select_one('#video_label td.text a')
    if label_elem:
        result.label = label_elem.get_text(strip=True)
    
    # Cast
    cast_elems = soup.select('#video_cast td.text a')
    if cast_elems:
        result.cast = ', '.join([a.get_text(strip=True) for a in cast_elems])
    
    # Genres
    genre_elems = soup.select('#video_genres span.genre a')
    if genre_elems:
        result.genres = ', '.join([a.get_text(strip=True) for a in genre_elems])
    
    try:
        requests.post(f"{os.getenv('BACKEND_URL')}/settings/logs", json={
            'level': 'INFO',
            'message': 'Extraction successful',
            'source': 'scraper',
            'request': {'url': url},
            'response': result.dict(),
        })
    except Exception:
        pass
    
    return result

@app.post("/extract", response_model=ExtractResponse)
async def extract_metadata(request: ExtractRequest):
    if not request.url:
        raise HTTPException(status_code=400, detail="URL is required")
    
    domain = urlparse(request.url).netloc.lower()
    
    if 'javlibrary' in domain:
        result = await run_in_threadpool(extract_javlibrary, request.url)
        return result
    else:
        raise HTTPException(status_code=400, detail="Unsupported domain")

@app.get("/health")
async def health():
    return {"status": "ok"}
