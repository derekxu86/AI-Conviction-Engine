import os
import json
import math
import urllib.request
import urllib.parse
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

app = FastAPI()

class AnalysisRequest(BaseModel):
    ticker: str
    name: str = "" 

@app.get("/")
async def serve_frontend():
    file_path = os.path.join(os.path.dirname(__file__), "..", "index.html")
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return HTMLResponse(content="<h1>前端文件未找到</h1>", status_code=404)

@app.get("/api/search")
async def search_stock(q: str):
    if not q: return []
    results = []
    
    # 核心修复 1：清洗查询词，去掉后缀，让东方财富能听懂
    clean_q = q.upper().replace('.SZ', '').replace('.SS', '').replace('.HK', '')
    
    # 引擎 1：东方财富 API (精准匹配A股中文)
    try:
        token = "D43BF722C8E33BDC906FB84D85E326E8"
        east_url = f"https://searchapi.eastmoney.com/api/suggest/get?input={urllib.parse.quote(clean_q)}&type=14&token={token}&count=5"
        east_req = urllib.request.Request(east_url, headers={'User-Agent': 'Mozilla/5.0'})
        
        with urllib.request.urlopen(east_req, timeout=3) as res:
            east_data = json.loads(res.read().decode('utf-8'))
            if "QuotationCodeTable" in east_data and "Data" in east_data["QuotationCodeTable"]:
                for item in east_data["QuotationCodeTable"]["Data"]:
                    code = item.get("Code")
                    name = item.get("Name")
                    market_type = str(item.get("MarketType"))
                    
                    y_ticker = code
                    if market_type == "1": y_ticker = code + ".SS"
                    elif market_type == "2": y_ticker = code + ".SZ"
                    elif market_type == "3": y_ticker = code + ".HK"
                    
                    results.append({"symbol": y_ticker, "name": name, "raw": code})
    except Exception: pass

    # 引擎 2：Yahoo (补全美股/澳洲股全称)
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
    
    return results[:8]

def get_market_and_backtest_data(ticker, known_name=""):
    # 核心修复 2：如果名字是空的，强制去 Yahoo 抓取官方英文/中文全称
    final_name = known_name
    if not final_name or final_name == ticker:
        try:
            quote_url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={ticker}"
            quote_req = urllib.request.Request(quote_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(quote_req, timeout=3) as q_res:
                q_data = json.loads(q_res.read().decode('utf-8'))
                if q_data['quoteResponse']['result']:
                    info = q_data['quoteResponse']['result'][0]
                    final_name = info.get('longName') or info.get('shortName') or ticker
        except Exception: 
            final_name = ticker

    chart_url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=6mo"
    req = urllib.request.Request(chart_url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            if data['chart']['error']: return None
            
            result = data['chart']['result'][0]
            meta = result['meta']
            
            timestamps = result.get('timestamp', [])
            raw_prices = result['indicators']['quote'][0]['close']
            
            valid_data = [(ts, p) for ts, p in zip(timestamps, raw_prices) if p is not None]
            dates_list, prices_list = [], []
            if valid_data:
                timestamps, prices = zip(*valid_data)
                dates_list = [datetime.fromtimestamp(ts).strftime('%Y-%m-%d') for ts in timestamps]
                prices_list = [round(p, 2) for p in prices]
            
            if len(prices_list) >= 2:
                price = prices_list[-1]
                prev_close = prices_list[-2]
            else:
                price = meta.get('regularMarketPrice', 0)
                prev_close = meta.get('chartPreviousClose', price)
            
            change = price - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0
            
            backtest_res = {"win_rate": 0, "sharpe": 0, "max_dd": 0, "equity_curve": [], "trades": 0}
            if len(prices_list) > 50:
                sma20 = [sum(prices_list[i-20:i])/20 if i>=20 else None for i in range(len(prices_list))]
                sma50 = [sum(prices_list[i-50:i])/50 if i>=50 else None for i in range(len(prices_list))]
                
                equity, position, buy_price, wins, trades = 10000, 0, 0, 0, 0
                peak, max_dd = equity, 0
                daily_returns, curve = [], []
                
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
                    "name": final_name,
                    "price": round(price, 2), 
                    "change": round(change, 2),
                    "change_pct": round(change_pct, 2), 
                    "currency": meta.get('currency', 'USD'),
                    "trend": {"dates": dates_list, "prices": prices_list}
                },
                "backtest": backtest_res
            }
    except Exception: return None

@app.post("/api/analyze")
async def analyze_stock(request: AnalysisRequest):
    original_input = request.ticker.strip()
    ticker = original_input.upper()
    req_name = request.name.strip()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if not api_key: return {"error": True, "message": "服务端未配置 OPENAI_API_KEY"}

    # 如果前端因为缓存没传过来名字，我们强制搜一遍
    if not req_name or req_name == ticker:
        suggestions = await search_stock(original_input)
        if suggestions:
            ticker = suggestions[0]["symbol"]
            req_name = suggestions[0]["name"]

    data_pack = get_market_and_backtest_data(ticker, known_name=req_name)
    
    if not data_pack:
        return {"error": True, "message": f"未找到标的: {original_input}。请确认代码是否正确。"}

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    
    company_name = data_pack['market']['name']
    bt_info = f"动量策略(SMA20/50)回测 -> 胜率: {data_pack['backtest']['win_rate']}%, 夏普比率: {data_pack['backtest']['sharpe']}, 最大回撤: {data_pack['backtest']['max_dd']}%"

    # 核心修复 3：防幻觉的铁血 Prompt
    sys_prompt = f"""你是一个华尔街顶级对冲基金的高级研究员组合。
    
    【核心铁律】：
    1. 你当前分析的真实公司是：【{company_name}】(代码: {ticker})。
    2. 绝不允许望文生义！例如 NVA 可能是 Nova Minerals 矿业勘探，002626 是 金达威(保健品/辅酶Q10)。你必须基于你的知识库确认其主业。如果拿不准，请直接回答“无法确认主营业务，拒绝分析”。
    3. 每个 Agent 的分析必须极度详实，指出具体的业务、财报隐患或行业竞争，字数【绝对不可少于80字】！禁止一句话敷衍。
    
    请严格输出纯 JSON 格式：
    {{
      "radar": {{"theme": "具体的产业逻辑或主线", "sector_trend": "行业当前周期的微观状态"}},
      "agents": {{
        "macro": {{"stance": "看多/看空/中立", "opinion": "【字数80+】基于真实公司主营业务展开，点明该产业面临的原材料周期、宏观政策催化或出海逻辑。"}},
        "quant": {{"stance": "看多/看空/中立", "opinion": "【字数80+】深度解读传给你的回测胜率与夏普比率({bt_info})，结合价格走势评估动量策略。"}},
        "risk": {{"stance": "警告/安全", "opinion": "【字数80+】一针见血指出特定雷区，例如地缘制裁、成本上升、或特定竞争对手带来的压力。"}},
        "sentiment": {{"stance": "贪婪/恐惧/中立", "opinion": "【字数80+】判断当前资金更偏好哪类资产，这家公司近期是否被机构抱团或冷落。"}},
        "valuation": {{"stance": "低估/高估/合理", "opinion": "【字数80+】判断它在同业中的估值倍数溢价情况，探讨目前股价是否透支了未来业绩。"}}
      }},
      "chair": {{
        "score": 85, "action": "STRONG BUY/BUY/HOLD/SELL/STRONG SELL",
        "bull_case": "具体看多催化剂", "bear_case": "具体看空黑天鹅", "summary": "综合主席最终研判"
      }}
    }}"""

    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": sys_prompt}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.3 # 温度降至0.3，让AI像机器一样理性输出
    }

    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
            content = json.loads(result["choices"][0]["message"]["content"])
            
            content["market_info"] = data_pack["market"]
            content["market_info"]["resolved_ticker"] = ticker
            content["backtest"] = data_pack["backtest"]
            return content
    except Exception as e:
        return {"error": True, "message": f"AI 引擎网络请求异常: {str(e)}"}
