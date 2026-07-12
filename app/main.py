from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import json
import os

app = FastAPI(title="Event Scraper API")

class Event(BaseModel):
    title: str
    date: str
    time: Optional[str] = None
    price: Optional[float] = None
    category: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    venue: Optional[str] = None
    source_url: str

class Webhook(BaseModel):
    url: str
    name: str

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/events", response_model=List[Event])
def get_events():
    # In a real app, this would query a database
    # For now, let's try to read from docs/events.json if it exists
    events_path = "docs/events.json"
    if os.path.exists(events_path):
        try:
            with open(events_path, "r") as f:
                data = json.load(f)
                return data.get("events", [])
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    return []

@app.get("/status")
def get_status():
    return {
        "last_run": "2024-05-20T17:00:00Z",
        "scrapers": [
            {"name": "rausgegangen", "status": "healthy"},
            {"name": "eventbrite", "status": "healthy"},
            {"name": "meetup", "status": "healthy"}
        ],
        "event_count": 42
    }

@app.post("/webhooks")
def register_webhook(webhook: Webhook):
    # Logic to save webhook to DB
    return {"message": f"Webhook {webhook.name} registered successfully"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
