"""
Example FastAPI endpoint using the multi-provider LLM layer.

Run:
  pip install -r requirements.txt
  set LLM_PROVIDER=gemini
  set GEMINI_API_KEY=...
  uvicorn fastapi_app:app --reload --port 8000

POST:
  /chat  {"prompt": "Hello!"}
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from llm_provider import LLMProviderError, generate_response

logger = logging.getLogger("fastapi_app")

app = FastAPI(title="LLM Combo API", version="1.0.0")


class ChatRequest(BaseModel):
    prompt: str


class ChatResponse(BaseModel):
    provider: str | None = None
    response: str


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    try:
        text = generate_response(req.prompt)
        # Provider is logged inside llm_provider; return only the response text.
        return ChatResponse(response=text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except LLMProviderError as e:
        logger.exception("LLM error")
        raise HTTPException(status_code=502, detail=str(e)) from e

