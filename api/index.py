import os
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from .agent_committee import InvestmentCommittee

app = FastAPI()

class AnalysisRequest(BaseModel):
    ticker: str

# 核心破解逻辑：如果有人访问主页，Python 直接把前端文件扔给他
@app.get("/")
async def serve_frontend():
    # 寻找根目录下的 index.html
    file_path = os.path.join(os.path.dirname(__file__), "..", "index.html")
    
    # 自动诊断：如果文件真的在，直接显示网页
    if os.path.exists(file_path):
        return FileResponse(file_path)
    # 如果文件不在，屏幕上直接显示大字报错，告诉你问题出在哪
    else:
        return HTMLResponse(
            content="<h1 style='color:red; text-align:center; margin-top:50px;'>重大错误：系统找不到 index.html 文件！</h1><h3 style='text-align:center;'>请检查 GitHub 仓库：<br>1. 文件是否在最外层（不能在 api 文件夹里）。<br>2. 名字必须是纯小写的 index.html。</h3>", 
            status_code=404
        )

# 接收前端请求的核心接口
@app.post("/api/analyze")
async def analyze_stock(request: AnalysisRequest):
    ticker = request.ticker
    committee = InvestmentCommittee(ticker=ticker)
    mock_context = {"trend": "upward"}
    final_result = committee.start_meeting(context_data=mock_context)
    return final_result
