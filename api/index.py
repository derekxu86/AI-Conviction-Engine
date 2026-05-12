import os
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

app = FastAPI()

class AnalysisRequest(BaseModel):
    ticker: str

@app.get("/")
async def serve_frontend():
    file_path = os.path.join(os.path.dirname(__file__), "..", "index.html")
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return HTMLResponse(content="<h1>前端文件未找到</h1>", status_code=404)

@app.post("/api/analyze")
async def analyze_stock(request: AnalysisRequest):
    # 🕵️ 断路测试：什么真实数据都不查，直接秒回结果
    return {
        "score": 100,
        "action": "CONNECTION OK",
        "bull_case": "太棒了！前后端连通性完美！Vercel 路由没有任何问题。",
        "bear_case": "之前的报错，100% 是因为 OpenAI 或 雅虎的接口响应太慢，被 Vercel 强行掐断了。"
    }
