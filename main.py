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
    code: str

class ExtractResponse(BaseModel):
    code: str = ""
    title: str = ""
    overview: str = ""
    director: str = ""
    studio: str = ""
    label: str = ""
    country: str = ""
    language: str = ""
    release_date: str = ""
    cast: str = ""
    genres: str = ""

def extract_javinfo(code: str) -> ExtractResponse:
    url = "https://api.javinfo.dev/movie"
    headers = {
        "x-javinfo-key": os.getenv("JAVINFO_KEY", "jvi_VQvjDrBXubfDCGvydcLOSmPzTuEfVdhIReZJDwvdFaBIOnQwRoNSIAlsswqLntbM"),
        "Content-Type": "application/json"
    }
    payload = {
        "q": code,
        "providers": "missav,javlibrary,sextb,javdatabase,dmm,fanza"
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        
        movie_data = data.get("result", {})
        if not movie_data:
            raise HTTPException(status_code=404, detail="Movie not found")
            
        result = ExtractResponse()
        result.code = movie_data.get("dvdId") or code
        result.title = movie_data.get("titleEn") or movie_data.get("titleJa") or ""
        result.overview = movie_data.get("commentEn") or movie_data.get("commentJa") or ""
        result.director = ", ".join(movie_data.get("directors", []))
        result.studio = ", ".join(movie_data.get("makers", []))
        result.label = movie_data.get("label") or ""
        result.country = "Japan"
        result.language = "Japanese"
        result.release_date = movie_data.get("releaseDate") or ""
        
        # Combine actresses and actors for cast
        actresses = movie_data.get("actresses", [])
        actors = movie_data.get("actors", [])
        result.cast = ", ".join(actresses + actors)
        
        result.genres = ", ".join(movie_data.get("categories", []))
        
        try:
            requests.post(f"{os.getenv('BACKEND_URL')}/settings/logs", json={
                'level': 'INFO',
                'message': f'Extraction successful for code: {code}',
                'source': 'scraper',
                'request': {'code': code},
                'response': result.dict(),
            })
        except Exception:
            pass
            
        return result
    except Exception as e:
        error_msg = str(e)
        if hasattr(e, 'response') and e.response:
            try:
                error_msg = e.response.json().get('message', error_msg)
            except:
                pass
        
        try:
            requests.post(f"{os.getenv('BACKEND_URL')}/settings/logs", json={
                'level': 'ERROR',
                'message': f'Extraction failed: {error_msg}',
                'source': 'scraper',
                'request': {'code': code},
                'response': None,
            })
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=f"Failed to fetch data: {error_msg}")

@app.post("/extract", response_model=ExtractResponse)
async def extract_metadata(request: ExtractRequest):
    if not request.code:
        raise HTTPException(status_code=400, detail="Code is required")
    
    return extract_javinfo(request.code)

@app.get("/health")
async def health():
    return {"status": "ok"}
