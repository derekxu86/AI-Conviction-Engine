from fastapi import FastAPI
from pydantic import BaseModel
from .agent_committee import InvestmentCommittee

# 1. 这一行是 Vercel 的命根子，绝对不能缺少，且前面不能有任何空格！
app = FastAPI()

class AnalysisRequest(BaseModel):
    ticker: str

# 2. 避免拦截主页的健康检查
@app.get("/api")
@app.get("/api/analyze")
async def health_check():
    return {"status": "Online", "message": "API is running!"}

# 3. 接收前端请求的核心接口
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
