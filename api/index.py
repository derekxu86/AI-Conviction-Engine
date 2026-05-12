import os
import json
import urllib.request
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

# --- 新增：智能搜索接口（支持A股拼音与汉字） ---
@app.get("/api/search")
async def search_stock(q: str):
    if not q:
        return []
    # 使用腾讯 Smartbox 接口，完美支持拼音首字母和汉字
    url = f"https://smartbox.gtimg.cn/s3/?q={urllib.parse.quote(q)}&t=all"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    
    results = []
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            data_str = response.read().decode('utf-8')
            # 解析腾讯返回的特有格式: v_hint="sh600000,1,浦发银行,pfyh...^usAAPL,1,苹果..."
            if 'v_hint="' in data_str:
                raw_hints = data_str.split('v_hint="')[1].split('";')[0]
                if raw_hints:
                    items = raw_hints.split('^')
                    for item in items:
                        parts = item.split(',')
                        if len(parts) >= 3:
                            t_ticker = parts[0] # 如 sh600000, usAAPL
                            name = parts[2]
                            
                            # 转换为 Yahoo 标准代码
                            y_ticker = t_ticker
                            if t_ticker.startswith('sh'): y_ticker = t_ticker[2:] + '.SS'
                            elif t_ticker.startswith('sz'): y_ticker = t_ticker[2:] + '.SZ'
                            elif t_ticker.startswith('hk'): y_ticker = t_ticker[2:] + '.HK'
                            elif t_ticker.startswith('us'): y_ticker = t_ticker[2:].upper()
                            
                            results.append({"symbol": y_ticker, "name": name, "raw": t_ticker})
    except Exception as e:
        pass
    return results[:8] # 最多返回 8 个建议

# --- 升级：获取更丰富的真实市场数据 ---
def get_real_market_data(ticker):
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode('utf-8'))
            if data['chart']['error']:
                return None
            
            meta = data['chart']['result'][0]['meta']
            price = meta.get('regularMarketPrice', 0)
            prev_close = meta.get('chartPreviousClose', 0)
            currency = meta.get('currency', 'USD')
            
            change = price - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0
            
            return {
                "price": round(price, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "currency": currency,
                "text_summary": f"最新价格: {price} {currency}, 涨跌幅: {change_pct:.2f}%"
            }
    except Exception:
        return None

@app.post("/api/analyze")
async def analyze_stock(request: AnalysisRequest):
    ticker = request.ticker.upper().strip()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if not api_key:
        return {"error": True, "message": "未检测到 OPENAI_API_KEY"}

    market_data = get_real_market_data(ticker)
    if not market_data:
        return {"error": True, "message": f"查无此票或已退市: {ticker}"}

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    # 升级：要求 AI 模拟三个 Agent 的独立思考和博弈
    sys_prompt = """你是一个多智能体量化投资委员会。请根据股票代码和市场数据进行圆桌讨论。
    必须严格输出JSON，包含以下结构：
    {
      "macro_agent": {"stance": "看多/看空/中立", "opinion": "一句话宏观逻辑"},
      "quant_agent": {"stance": "看多/看空/中立", "opinion": "一句话技术面逻辑"},
      "risk_agent": {"stance": "警告/安全", "opinion": "一句话核心风险"},
      "chair": {"score": 0-100整数, "action": "STRONG BUY/BUY/HOLD/SELL", "summary": "主席最终裁决"}
    }"""

    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"目标资产: {ticker}\n近期表现: {market_data['text_summary']}"}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.7
    }

    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=7) as response:
            result = json.loads(response.read().decode("utf-8"))
            content = json.loads(result["choices"][0]["message"]["content"])
            # 将抓取到的真实数据合并返回给前端展示
            content["market_info"] = market_data 
            return content
            
    except Exception as e:
        return {"error": True, "message": f"AI 引擎响应超时或异常: {str(e)}"}