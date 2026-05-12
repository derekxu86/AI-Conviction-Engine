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
    else:
        return HTMLResponse(content="<h1>前端文件未找到</h1>", status_code=404)

@app.post("/api/analyze")
async def analyze_stock(request: AnalysisRequest):
    ticker = request.ticker
    
    # 实例化委员会
    committee = InvestmentCommittee(ticker=ticker)
    
    # 启动真实数据抓取与 AI 讨论
    final_result = committee.start_meeting()
    
    return final_result
