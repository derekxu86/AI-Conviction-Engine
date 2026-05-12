import os
import json
import urllib.request # 使用纯原生库，0冷启动时间
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
    return HTMLResponse(content="<h1>前端未找到</h1>", status_code=404)

@app.post("/api/analyze")
async def analyze_stock(request: AnalysisRequest):
    ticker = request.ticker.upper()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if not api_key:
        return {
            "score": 0, "action": "KEY MISSING", 
            "bull_case": "请检查 Vercel 环境变量", 
            "bear_case": "未检测到 OPENAI_API_KEY"
        }

    # 极速战术：直接用原生 urllib 发送 HTTP 请求给 OpenAI
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    sys_prompt = """你是一个量化投资委员会。请根据股票代码直接综合研判。
    严格输出JSON，不要有任何 Markdown 标记，包含4个字段：
    {"score": 0-100整数, "action": "BUY/SELL/HOLD", "bull_case": "看多理由", "bear_case": "看空理由"}"""

    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"目标股票: {ticker}。请快速分析。"}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.7
    }

    try:
        # 将请求数据打包
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
        
        # 终极防线：限制 5 秒内必须返回，绝对不给 Vercel 拔网线的机会！
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read().decode("utf-8"))
            content = result["choices"][0]["message"]["content"]
            return json.loads(content)
            
    except urllib.error.URLError as e:
        return {
            "score": 0, "action": "API ERROR", 
            "bull_case": "网络连接 OpenAI 失败", 
            "bear_case": f"错误详情: {str(e)}"
        }
    except Exception as e:
        return {
            "score": 0, "action": "SYS ERROR", 
            "bull_case": "解析报错", 
            "bear_case": f"错误详情: {str(e)}"
        }
