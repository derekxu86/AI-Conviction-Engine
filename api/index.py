import os
import json
import math
import urllib.request
import urllib.parse
from datetime import datetime
from urllib.error import HTTPError
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
    results = []
    
    # 引擎 1：Yahoo Finance (支持美股、澳洲股等全球资产)
    try:
        y_url = f"https://query2.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(q)}"
        y_req = urllib.request.Request(y_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(y_req, timeout=3) as res:
            y_data = json.loads(res.read().decode('utf-8'))
            for quote in y_data.get('quotes', []):
                if quote.get('quoteType') in ['EQUITY', 'ETF', 'MUTUALFUND']:
                    symbol = quote.get('symbol')
                    name = quote.get('shortname') or quote.get('longname') or symbol
                    if not any(r['symbol'] == symbol for r in results):
                        results.append({"symbol": symbol, "name": name, "raw": symbol})
    except Exception: pass

    # 引擎 2：新浪财经 (支持A股汉字/拼音)
    try:
        encoded_q = urllib.parse.quote(q.encode('gbk'))
        s_url = f"https://suggest3.sinajs.cn/suggest/type=&key={encoded_q}"
        # 【致命修复】：必须带上 Referer，否则新浪会直接拦截请求！
        s_req = urllib.request.Request(s_url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://finance.sina.com.cn/'
        })
        with urllib.request.urlopen(s_req, timeout=3) as res:
            data_str = res.read().decode('gbk')
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
                            
                            if t_ticker.startswith('sh') or t_ticker.startswith('sz') or t_ticker.startswith('hk'):
                                if not any(r['symbol'] == y_ticker for r in results):
                                    results.append({"symbol": y_ticker, "name": name, "raw": t_ticker})
    except Exception: pass
    
    return results[:8]

def get_market_and_backtest_data(ticker):
    company_name = ticker
    try:
        quote_url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={ticker}"
        quote_req = urllib.request.Request(quote_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(quote_req, timeout=3) as q_res:
            q_data = json.loads(q_res.read().decode('utf-8'))
            if q_data['quoteResponse']['result']:
                info = q_data['quoteResponse']['result'][0]
                company_name = info.get('longName') or info.get('shortName') or ticker
    except Exception: pass

    chart_url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=6mo"
    req = urllib.request.Request(chart_url, headers={'User-Agent': 'Mozilla/5.0'})
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
            
            timestamps = result.get('timestamp', [])
            raw_prices = result['indicators']['quote'][0]['close']
            
            valid_data = [(ts, p) for ts, p in zip(timestamps, raw_prices) if p is not None]
            dates_list, prices_list = [], []
            if valid_data:
                timestamps, prices = zip(*valid_data)
                dates_list = [datetime.fromtimestamp(ts).strftime('%Y-%m-%d') for ts in timestamps]
                prices_list = [round(p, 2) for p in prices]
            
            backtest_res = {"win_rate": 0, "sharpe": 0, "max_dd": 0, "equity_curve": [], "trades": 0}
            if len(prices_list) > 50:
                sma20 = [sum(prices_list[i-20:i])/20 if i>=20 else None for i in range(len(prices_list))]
                sma50 = [sum(prices_list[i-50:i])/50 if i>=50 else None for i in range(len(prices_list))]
                
                equity, position, buy_price, wins, trades = 10000, 0, 0, 0, 0
                peak, max_dd = equity, 0
                daily_returns = []
                curve = []
                
                for i in range(50, len(prices_list)):
                    curr_p = prices_list[i]
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
                    "equity_curve": curve[-30:], 
                    "trades": trades
                }

            return {
                "market": {
                    "name": company_name,
                    "price": round(price, 2), "change": round(change, 2),
                    "change_pct": round(change_pct, 2), "currency": meta.get('currency', 'USD'),
                    "text_summary": f"最新价格: {price} {meta.get('currency', 'USD')}。",
                    "trend": {"dates": dates_list, "prices": prices_list}
                },
                "backtest": backtest_res
            }
    except Exception: return None

@app.post("/api/analyze")
async def analyze_stock(request: AnalysisRequest):
    original_input = request.ticker.strip()
    ticker = original_input.upper()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if not api_key: return {"error": True, "message": "未检测到 OPENAI_API_KEY"}

    data_pack = get_market_and_backtest_data(ticker)
    
    # 纠错网关
    if not data_pack:
        suggestions = await search_stock(original_input)
        if suggestions:
            ticker = suggestions[0]["symbol"]
            data_pack = get_market_and_backtest_data(ticker)

    if not data_pack:
        return {"error": True, "message": f"查无此票或已退市: {original_input}。请检查代码。"}

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    
    company_name = data_pack['market']['name']
    bt_info = f"动量策略回测胜率: {data_pack['backtest']['win_rate']}%, 夏普: {data_pack['backtest']['sharpe']}, 最大回撤: {data_pack['backtest']['max_dd']}%"

    # 【修复 400 错误】：采用纯字符串拼接，坚决不使用带括号的 f-string 逃逸
    json_schema = """{
      "radar": {"theme": "具体的行业主题", "sector_trend": "具体的微观趋势"},
      "agents": {
        "macro": {"stance": "看多/看空/中立", "opinion": "结合主营业务点出宏观催化剂(50字)"},
        "quant": {"stance": "看多/看空/中立", "opinion": "结合回测数据点评技术面(50字)"},
        "risk": {"stance": "警告/安全", "opinion": "指出该行业的特定黑天鹅风险(50字)"},
        "sentiment": {"stance": "贪婪/恐惧/中立", "opinion": "筹码与资金博弈推演(50字)"},
        "valuation": {"stance": "低估/高估/合理", "opinion": "估值水平判断(50字)"}
      },
      "chair": {
        "score": 85, "action": "STRONG BUY/BUY/HOLD/SELL/STRONG SELL",
        "bull_case": "一条具体的看多理由", "bear_case": "一条具体的看空理由", "summary": "冷血的最终裁决"
      }
    }"""

    sys_prompt = f"你是一个顶尖的华尔街量化投研委员会。\n当前分析目标：{company_name} (代码: {ticker})。\n\n【核心纪律】：\n1. 你必须指出 {company_name} 是做哪块业务的。\n2. 绝对禁止使用万能废话！\n3. Quant Agent 必须结合传入的回测数据 ({bt_info}) 给出技术点评。\n\n请输出严格的 JSON 格式，期望的数据结构如下：\n{json_schema}"

    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"请开始对 {company_name} ({ticker}) 的研判。必须返回 JSON。"}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.4
    }

    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=12) as response:
            result = json.loads(response.read().decode("utf-8"))
            content = json.loads(result["choices"][0]["message"]["content"])
            
            content["market_info"] = data_pack["market"]
            content["market_info"]["resolved_ticker"] = ticker
            content["backtest"] = data_pack["backtest"]
            return content
    # 【致命排雷】：如果 OpenAI 再次 400，拦截并打印真实死因
    except HTTPError as e:
        err_body = e.read().decode('utf-8')
        return {"error": True, "message": f"OpenAI 拒绝了请求，详细错误: {err_body}"}
    except Exception as e:
        return {"error": True, "message": f"AI 引擎网络异常: {str(e)}"}
