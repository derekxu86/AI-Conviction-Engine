# api/index.py 顶部修改为：
from fastapi import FastAPI
from pydantic import BaseModel
from .agent_committee import InvestmentCommittee  

app = FastAPI()

class AnalysisRequest(BaseModel):
    ticker: str

# 删除了 @app.get("/")，防止拦截主页
@app.get("/api")
@app.get("/api/analyze")
async def health_check():
    return {"status": "Online", "message": "API is running!"}

@app.post("/api/analyze")
async def analyze_stock(request: AnalysisRequest):
    # 下面的代码保持不变...