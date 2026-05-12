import os
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from .agent_committee import InvestmentCommittee

app = FastAPI()

class AnalysisRequest(BaseModel):
    ticker: str

@app.get("/")
async def serve_frontend():
    file_path = os.path.join(os.path.dirname(__file__), "..", "index.html")
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return HTMLResponse(content="<h1>前端未找到</h1>", status_code=404)

@app.post("/api/analyze")
async def analyze_stock(request: AnalysisRequest):
    # 召唤带有“熔断机制”的真实 AI 委员会
    committee = InvestmentCommittee(ticker=request.ticker)
    return committee.start_meeting()
