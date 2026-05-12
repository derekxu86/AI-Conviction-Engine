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

@app.get("/api/search")
async def search_stock(q: str):
    """改用极其稳定的新浪证券 Suggest 接口，完美支持 A 股拼音/代码/汉字"""
    if not q:
        return []
    url = f"https://suggest3.sinajs.cn/suggest/type=&key={urllib.parse.quote(q)}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn/'})
    results = []
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            # 新浪接口返回的是 GBK 编码数据
            data_str = response.read().decode('gbk')
            if '="' in data_str:
                raw_hints = data_str.split('="')[1].split('";')[0]
                if raw_hints:
                    items = raw_hints.split(';')
                    for item in items:
                        parts = item.split(',')
                        if len(parts) >= 4:
                            t_ticker = parts[0] # sh601318, us_aapl
                            name = parts[4] if len(parts) > 4 else parts[2] # 优先取中文名
                            
                            # 转换为 Yahoo 标准代码
                            y_ticker = t_ticker
                            if t_ticker.startswith('sh'): y_ticker = t_ticker[2:] + '.SS'
                            elif t_ticker.startswith('sz'): y_ticker = t_ticker[2:] + '.SZ'
                            elif t_ticker.startswith('hk'): y_ticker = t_ticker[2:] + '.HK'
                            elif t_ticker.startswith('of'): y_ticker = t_ticker[2:] + '.SS' # 基金
                            else:
                                # 处理美股，新浪美股带有 'us_' 前缀或者直接是字母
                                y_ticker = t_ticker.replace('us_', '').upper()
                                if not y_ticker.isalpha():
                                    y_ticker = parts[3].upper() # 尝试从拼音字段拿纯英文代码
                            
                            results.append({"symbol": y_ticker, "name": name, "raw": t_ticker})
    except Exception:
        pass
    return results[:8] 

def get_real_market_data(ticker):
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

@app.post("/api/analyze")
async def analyze_stock(request: AnalysisRequest):
    original_input = request.ticker.upper().strip()
    ticker = original_input
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if not api_key: return {"error": True, "message": "未检测到 OPENAI_API_KEY"}

    market_data = get_real_market_data(ticker)
    if not market_data:
        suggestions = await search_stock(request.ticker.strip())
        if suggestions:
            ticker = suggestions[0]["symbol"]
            market_data = get_real_market_data(ticker)

    if not market_data:
        return {"error": True, "message": f"查无此票或已退市: {original_input}。请输入标准代码或全拼。"}

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    
    # 【核心升级】：要求 AI 写出深度的、包含数据的分析长文
    sys_prompt = """你是一个顶级的量化投资与多智能体研究委员会。
    必须严格输出JSON格式，每位Agent的分析必须极其专业、深入，字数在60-120字之间，具备机构级研报水准。
    包含以下结构：
    {
      "macro_agent": {"stance": "看多/看空/中立", "opinion": "详细分析该资产所处行业的宏观周期、近期政策催化剂或流动性环境。"},
      "quant_agent": {"stance": "看多/看空/中立", "opinion": "详细分析技术面形态、均线趋势、动量指标或机构资金博弈情况。"},
      "risk_agent": {"stance": "警告/安全", "opinion": "指出最大的潜在黑天鹅、估值泡沫风险或关键的下行支撑位跌破风险。"},
      "chair": {"score": 0-100整数, "action": "STRONG BUY/BUY/HOLD/SELL/STRONG SELL", "summary": "综合胜率与赔率，给出具体的建仓或减仓建议。"}
    }"""

    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"目标资产代码: {ticker}\n近期表现: {market_data['text_summary']}\n请提供深度分析。"}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.7
    }

    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
            content = json.loads(result["choices"][0]["message"]["content"])
            market_data['resolved_ticker'] = ticker
            content["market_info"] = market_data 
            return content
    except Exception as e:
        return {"error": True, "message": f"AI 引擎响应异常: {str(e)}"}
