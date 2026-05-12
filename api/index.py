import os
import json
import math
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
    if not q: return []
    url = f"https://suggest3.sinajs.cn/suggest/type=&key={urllib.parse.quote(q)}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
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

def get_market_and_backtest_data(ticker):
    """【模块整合】网关：同时获取最新价格，并拉取半年历史数据进行量化回测验证"""
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=6mo"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=4) as response:
            data = json.loads(response.read().decode('utf-8'))
            if data['chart']['error']: return None
            
            result = data['chart']['result'][0]
            meta = result['meta']
            price = meta.get('regularMarketPrice', 0)
            prev_close = meta.get('chartPreviousClose', 0)
            change = price - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0
            
            # 【模块3&4: 纯原生 IndicatorStrategy 回测 - 20日/50日双均线动量策略】
            prices = result['indicators']['quote'][0]['close']
            prices = [p for p in prices if p is not None]
            
            backtest_res = {"win_rate": 0, "sharpe": 0, "max_dd": 0, "equity_curve": [], "trades": 0}
            if len(prices) > 50:
                sma20 = [sum(prices[i-20:i])/20 if i>=20 else None for i in range(len(prices))]
                sma50 = [sum(prices[i-50:i])/50 if i>=50 else None for i in range(len(prices))]
                
                equity, position, buy_price, wins, trades = 10000, 0, 0, 0, 0
                peak, max_dd = equity, 0
                daily_returns = []
                curve = []
                
                for i in range(50, len(prices)):
                    curr_p = prices[i]
                    # 交叉信号发生
                    if sma20[i-1] and sma50[i-1]:
                        if sma20[i-1] > sma50[i-1] and position == 0:
                            position = equity / curr_p
                            buy_price = curr_p
                        elif sma20[i-1] < sma50[i-1] and position > 0:
                            equity = position * curr_p
                            if curr_p > buy_price: wins += 1
                            trades += 1
                            position = 0
                            
                    curr_val = equity if position == 0 else position * curr_p
                    curve.append(curr_val)
                    if curr_val > peak: peak = curr_val
                    max_dd = max(max_dd, (peak - curr_val) / peak)
                    if len(curve) > 1: daily_returns.append((curve[-1] - curve[-2])/curve[-2])
                
                mean_ret = sum(daily_returns)/len(daily_returns) if daily_returns else 0
                variance = sum((r - mean_ret)**2 for r in daily_returns)/len(daily_returns) if daily_returns else 0
                std_dev = math.sqrt(variance)
                
                backtest_res = {
                    "win_rate": round((wins/trades)*100, 1) if trades > 0 else 0,
                    "sharpe": round((mean_ret / std_dev) * math.sqrt(252), 2) if std_dev > 0 else 0,
                    "max_dd": round(max_dd * 100, 1),
                    "equity_curve": curve[-30:], # 取最后30天绘制
                    "trades": trades
                }

            return {
                "market": {
                    "price": round(price, 2), "change": round(change, 2),
                    "change_pct": round(change_pct, 2), "currency": meta.get('currency', 'USD'),
                    "text_summary": f"最新价格: {price}, 近半年振幅完成回测采集。"
                },
                "backtest": backtest_res
            }
    except Exception: return None

@app.post("/api/analyze")
async def analyze_stock(request: AnalysisRequest):
    original_input = request.ticker.upper().strip()
    ticker = original_input
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if not api_key: return {"error": True, "message": "未检测到 OPENAI_API_KEY"}

    # Agent Gateway: 自动纠错与数据采集
    data_pack = get_market_and_backtest_data(ticker)
    if not data_pack:
        suggestions = await search_stock(request.ticker.strip())
        if suggestions:
            ticker = suggestions[0]["symbol"]
            data_pack = get_market_and_backtest_data(ticker)

    if not data_pack:
        return {"error": True, "message": f"查无此票或已退市: {original_input}。"}

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    
    # 【模块1 & 2整合】：AI Radar 雷达主题 + 5人投研委员会博弈
    sys_prompt = """你是 QuantDinger 架构下的 AI Conviction Engine。
    请分析目标资产，输出包含 雷达趋势(radar)、智能体意见(agents)、主席总结(chair) 的严格JSON格式：
    {
      "radar": {"theme": "未来6-12个月机会主题", "sector_trend": "行业趋势研判"},
      "agents": {
        "macro": {"stance": "看多/看空/中立", "opinion": "宏观/政策分析(50字)"},
        "quant": {"stance": "看多/看空/中立", "opinion": "技术面/量化形态分析(50字)"},
        "risk": {"stance": "警告/安全", "opinion": "核心风险提示(50字)"},
        "sentiment": {"stance": "贪婪/恐惧/中立", "opinion": "散户与机构情绪博弈(50字)"},
        "valuation": {"stance": "低估/高估/合理", "opinion": "估值水平与性价比(50字)"}
      },
      "chair": {
        "score": 0-100整数, "action": "STRONG BUY/BUY/HOLD/SELL/STRONG SELL",
        "bull_case": "看多逻辑点", "bear_case": "看空逻辑点", "summary": "综合主席裁决"
      }
    }"""

    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"目标资产代码: {ticker} (识别真实公司)\n近期状态: {data_pack['market']['text_summary']}"}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.7
    }

    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=12) as response:
            result = json.loads(response.read().decode("utf-8"))
            content = json.loads(result["choices"][0]["message"]["content"])
            
            # 整合所有数据下发给前端
            content["market_info"] = data_pack["market"]
            content["market_info"]["resolved_ticker"] = ticker
            content["backtest"] = data_pack["backtest"]
            return content
    except Exception as e:
        return {"error": True, "message": f"AI 引擎响应异常: {str(e)}"}
