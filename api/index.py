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

# 接收前端请求的数据模型
class AnalysisRequest(BaseModel):
    ticker: str
    name: str = "" # 接收前端传来的真实中文名，避免大模型产生幻觉

@app.get("/")
async def serve_frontend():
    file_path = os.path.join(os.path.dirname(__file__), "..", "index.html")
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return HTMLResponse(content="<h1>前端文件未找到，请检查路径</h1>", status_code=404)

@app.get("/api/search")
async def search_stock(q: str):
    """
    搜索模块：结合东方财富(A股/港股)与 Yahoo(美股/全球) 双引擎
    """
    if not q: return []
    results = []
    
    # 引擎 1：东方财富 API (完美支持 A 股拼音与汉字，无编码乱码问题)
    try:
        # 使用东方财富公开的搜索接口 token
        token = "D43BF722C8E33BDC906FB84D85E326E8"
        east_url = f"https://searchapi.eastmoney.com/api/suggest/get?input={urllib.parse.quote(q)}&type=14&token={token}&count=5"
        east_req = urllib.request.Request(east_url, headers={'User-Agent': 'Mozilla/5.0'})
        
        with urllib.request.urlopen(east_req, timeout=3) as res:
            east_data = json.loads(res.read().decode('utf-8'))
            if "QuotationCodeTable" in east_data and "Data" in east_data["QuotationCodeTable"]:
                for item in east_data["QuotationCodeTable"]["Data"]:
                    code = item.get("Code")
                    name = item.get("Name")
                    market_type = str(item.get("MarketType"))
                    
                    # 转换为 Yahoo 标准代码后缀
                    y_ticker = code
                    if market_type == "1":   # 上海
                        y_ticker = code + ".SS"
                    elif market_type == "2": # 深圳
                        y_ticker = code + ".SZ"
                    elif market_type == "3": # 港股
                        y_ticker = code + ".HK"
                    
                    results.append({"symbol": y_ticker, "name": name, "raw": code})
    except Exception as e:
        print(f"Eastmoney Search Error: {e}")
        pass

    # 引擎 2：Yahoo Finance API (补充美股及全球资产)
    try:
        y_url = f"https://query2.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(q)}"
        y_req = urllib.request.Request(y_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(y_req, timeout=3) as res:
            y_data = json.loads(res.read().decode('utf-8'))
            for quote in y_data.get('quotes', []):
                if quote.get('quoteType') in ['EQUITY', 'ETF', 'MUTUALFUND']:
                    symbol = quote.get('symbol')
                    name = quote.get('shortname') or quote.get('longname') or symbol
                    # 去重逻辑
                    if not any(r['symbol'] == symbol for r in results):
                        results.append({"symbol": symbol, "name": name, "raw": symbol})
    except Exception as e:
        print(f"Yahoo Search Error: {e}")
        pass
    
    return results[:8]

def get_market_and_backtest_data(ticker, known_name=""):
    """
    数据模块：获取准确的 K 线数据，计算真实的涨跌幅与量化回测指标
    """
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
            
            # 过滤空数据，保证时间轴对齐
            valid_data = [(ts, p) for ts, p in zip(timestamps, raw_prices) if p is not None]
            dates_list, prices_list = [], []
            if valid_data:
                timestamps, prices = zip(*valid_data)
                dates_list = [datetime.fromtimestamp(ts).strftime('%Y-%m-%d') for ts in timestamps]
                prices_list = [round(p, 2) for p in prices]
            
            # 【代码修复】：严格使用 K 线数组的最后两天进行计算，确保涨跌幅绝对准确
            if len(prices_list) >= 2:
                price = prices_list[-1]
                prev_close = prices_list[-2]
            else:
                price = meta.get('regularMarketPrice', 0)
                prev_close = meta.get('chartPreviousClose', price)
            
            change = price - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0
            
            # 使用传入的中文名或 fallback
            final_name = known_name if known_name else ticker

            # 原生量化回测逻辑 (SMA 20/50 动量)
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
    except Exception as e:
        print(f"Data Fetch Error: {e}")
        return None

@app.post("/api/analyze")
async def analyze_stock(request: AnalysisRequest):
    """
    大模型请求模块：组装严谨的 Prompt 并请求 OpenAI
    """
    original_input = request.ticker.strip()
    ticker = original_input.upper()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if not api_key: return {"error": True, "message": "服务端未配置 OPENAI_API_KEY"}

    # 尝试获取数据
    data_pack = get_market_and_backtest_data(ticker, known_name=request.name)
    
    # 容错：如果用户直接输入名字回车，通过搜索接口自动转换代码
    if not data_pack:
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

    # 【代码修复】：增加严厉的字数和内容深度限制
    sys_prompt = f"""你是一个顶尖的量化对冲基金研究组合。
    你的任务是深度分析：【{company_name}】(股票代码: {ticker})。
    
    【强制执行规则】：
    1. 你必须准确识别 {company_name} 真实的主营业务（例如：软件、矿业、新能源等）。
    2. 每位 Agent 的分析(opinion字段)内容【必须包含丰富细节，不少于60字】，严禁使用单句敷衍！
    3. 严禁使用“整体向好”、“经济复苏”等套话。必须提及具体的行业痛点、政策或基本面逻辑。
    4. Quant Agent 必须结合传入的数据 ({bt_info})，分析策略表现。
    
    必须输出纯 JSON 格式：
    {{
      "radar": {{"theme": "具体的产业链或主题", "sector_trend": "行业趋势(20字)"}},
      "agents": {{
        "macro": {{"stance": "看多/看空/中立", "opinion": "长文：基于公司主营业务的宏观催化剂及地缘/政策分析(至少60字)"}},
        "quant": {{"stance": "看多/看空/中立", "opinion": "长文：深度解读回测胜率与夏普比率，评估技术面支撑阻力(至少60字)"}},
        "risk": {{"stance": "警告/安全", "opinion": "长文：指出特定的公司财报隐患、政策合规或竞争对手威胁(至少60字)"}},
        "sentiment": {{"stance": "贪婪/恐惧/中立", "opinion": "长文：机构资金流向预期或近期市场情绪面博弈(至少60字)"}},
        "valuation": {{"stance": "低估/高估/合理", "opinion": "长文：相对估值分析，结合同业对比或历史水位(至少60字)"}}
      }},
      "chair": {{
        "score": 85, "action": "STRONG BUY/BUY/HOLD/SELL/STRONG SELL",
        "bull_case": "具体的一条看多逻辑", "bear_case": "具体的一条看空逻辑", "summary": "综合主席最终研判"
      }}
    }}"""

    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": sys_prompt}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.4 # 调低温度保证稳定输出
    }

    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
            content = json.loads(result["choices"][0]["message"]["content"])
            
            # 将清洗后的数据返回前端
            content["market_info"] = data_pack["market"]
            content["market_info"]["resolved_ticker"] = ticker
            content["backtest"] = data_pack["backtest"]
            return content
    except Exception as e:
        return {"error": True, "message": f"AI 引擎网络请求异常: {str(e)}"}
