# api/index.py
from fastapi import FastAPI
from pydantic import BaseModel
from .agent_committee import InvestmentCommittee  # 使用相对导入

app = FastAPI()

class AnalysisRequest(BaseModel):
    ticker: str

@app.post("/api/analyze")
async def analyze_stock(request: AnalysisRequest):
    ticker = request.ticker
    # 实例化我们的委员会逻辑
    committee = InvestmentCommittee(ticker=ticker)
    
    # 模拟简单的上下文数据
    mock_context = {"trend": "upward"}
    
    # 运行委员会并获取结果
    final_result = committee.start_meeting(context_data=mock_context)
    
    return final_result