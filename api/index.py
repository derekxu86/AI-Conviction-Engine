# api/index.py
from fastapi import FastAPI
from pydantic import BaseModel
from .agent_committee import InvestmentCommittee  

app = FastAPI()

class AnalysisRequest(BaseModel):
    ticker: str

# 💡 新增：让你在浏览器直接点击链接时，能看到成功提示，而不是报错
@app.get("/")
@app.get("/api")
@app.get("/api/analyze")
async def health_check():
    return {
        "status": "Online", 
        "message": "AI Conviction Engine 后端运行正常！请返回主域名访问可视化界面。"
    }

# 💡 优化：双重路由绑定，防止 Vercel 路径重写时丢失前缀
@app.post("/api/analyze")
@app.post("/analyze")
async def analyze_stock(request: AnalysisRequest):
    ticker = request.ticker
    # 实例化我们的委员会逻辑
    committee = InvestmentCommittee(ticker=ticker)
    
    # 模拟简单的上下文数据
    mock_context = {"trend": "upward"}
    
    # 运行委员会并获取结果
    final_result = committee.start_meeting(context_data=mock_context)
    
    return final_result