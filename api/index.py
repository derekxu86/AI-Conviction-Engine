import os
import json
import urllib.request
import urllib.parse
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

# ==========================================
# 模块 5 借鉴: Agent Gateway (内部工具层)
# ==========================================

async def search_stock(q: str):
    """工具 1: 资产扫描器 (scanThemes/symbolSearch) - 适配新浪接口"""
    if not q: return []
    url = f"https://suggest3.sinajs.cn/suggest/type=&key={urllib.parse.quote(q)}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn/'})
    results = []
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            data_str = response.read().decode('gbk')
            if '="' in data_str:
                raw_hints = data_str.split('="')[1].split('";')[0]
                if raw_hints:
                    items = raw_hints.split(';')
                    for item in items:
                        parts = item.split(',')
                        if len(parts) >= 4:
                            t_ticker = parts[0]
                            name = parts[4] if len(parts) > 4 else parts[2]
                            y_ticker = t_ticker
                            if t_ticker.startswith('sh'): y_ticker = t_ticker[2:] + '.SS'
                            elif t_ticker.startswith('sz'): y_ticker = t_ticker[2:] + '.SZ'
                            elif t_ticker.startswith('hk'): y_ticker = t_ticker[2:] + '.HK'
                            elif t_ticker.startswith('of'): y_ticker = t_ticker[2:] + '.SS'
                            else:
                                y_ticker = t_ticker.replace('us_', '').upper()
                                if not y_ticker.isalpha(): y_ticker = parts[3].upper()
                            results.append({"symbol": y_ticker, "name": name, "raw": t_ticker})
    except Exception: pass
    return results[:8]

def get_real_market_data(ticker):
    """工具 2: 市场数据网关 (getMarketData)"""
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode('utf-8'))
            if data['chart']['error']: return None
            
            meta = data['chart']['result'][0]['meta']
            price = meta.get('regularMarketPrice', 0)
            prev_close = meta.get('chartPreviousClose', 0)
            currency = meta.get('currency', 'USD')
            
            change = price - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0
            
            return {
                "price": round(price, 2), "change": round(change, 2),
                "change_pct": round(change_pct, 2), "currency": currency,
                "text_summary": f"最新价格: {price} {currency}, 涨跌幅: {change_pct:.2f}%"
            }
    except Exception: return None

@app.get("/api/search")
async def api_search(q: str):
    """暴露给前端的搜索接口"""
    return await search_stock(q)

# ==========================================
# 模块 1 & 2 借鉴: AI Radar & Multi-agent Research
# ==========================================

@app.post("/api/analyze")
async def analyze_stock(request: AnalysisRequest):
    original_input = request.ticker.upper().strip()
    ticker = original_input
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if not api_key: return {"error": True, "message": "未检测到 OPENAI_API_KEY"}

    # 调用 Agent Gateway 获取数据
    market_data = get_real_market_data(ticker)
    if not market_data:
        suggestions = await search_stock(request.ticker.strip())
        if suggestions:
            ticker = suggestions[0]["symbol"]
            market_data = get_real_market_data(ticker)

    if not market_data:
        return {"error": True, "message": f"查无此票或已退市: {original_input}。"}

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    
    # 构建完整的 QuantDinger 级多智能体 Prompt
    sys_prompt = """你是一个由顶级专家组成的量化投研委员会 (AI Investment Committee)。
    请基于目标资产和市场数据，模拟 5 位专家的内部博弈，最后由主席进行裁决。
    必须严格输出JSON格式，每位Agent的分析需精炼且具备机构级专业度（约50-80字）。
    包含以下结构：
    {
      "macro_agent": {"stance": "看多/看空/中立", "opinion": "宏观经济周期、行业政策或流动性分析。"},
      "quant_agent": {"stance": "看多/看空/中立", "opinion": "量化动量、均线形态或资金面特征分析。"},
      "risk_agent": {"stance": "警告/安全", "opinion": "潜在黑天鹅、尾部风险或支撑位跌破风险。"},
      "sentiment_agent": {"stance": "贪婪/恐惧/中立", "opinion": "散户/机构博弈状态或新闻热度分析。"},
      "valuation_agent": {"stance": "低估/高估/合理", "opinion": "相对估值、历史分位或股息率吸引力分析。"},
      "chair": {
        "score": 0到100的整数,
        "action": "STRONG BUY/BUY/HOLD/SELL/STRONG SELL",
        "bull_case": "核心看多逻辑精简",
        "bear_case": "核心看空逻辑精简",
        "summary": "主席综合5位委员意见的最终结论"
      }
    }"""

    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"目标资产代码: {ticker}\n近期表现: {market_data['text_summary']}\n请执行多智能体深度研判。"}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.7
    }

    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=12) as response:
            result = json.loads(response.read().decode("utf-8"))
            content = json.loads(result["choices"][0]["message"]["content"])
            market_data['resolved_ticker'] = ticker
            content["market_info"] = market_data 
            return content
    except Exception as e:
        return {"error": True, "message": f"AI 引擎响应异常: {str(e)}"}
