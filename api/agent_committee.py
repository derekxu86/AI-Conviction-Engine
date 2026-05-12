import os
import json
import requests
from openai import OpenAI

class InvestmentCommittee:
    def __init__(self, ticker):
        self.ticker = ticker
        
        # 获取 Vercel 环境变量中的 API Key
        api_key = os.environ.get("OPENAI_API_KEY")
        self.client = OpenAI(api_key=api_key) if api_key else None

    def fetch_real_data(self):
        """轻量级获取真实数据，绕过 yfinance 的体积限制"""
        try:
            # 直接调用雅虎金融的底层接口，极其快速
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{self.ticker}?interval=1d&range=1mo"
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers, timeout=5)
            data = resp.json()
            
            # 解析价格
            close_prices = data['chart']['result'][0]['indicators']['quote'][0]['close']
            valid_prices = [p for p in close_prices if p is not None]
            
            if not valid_prices:
                return "暂无行情数据"
                
            current_price = valid_prices[-1]
            past_price = valid_prices[0]
            pct_change = ((current_price - past_price) / past_price) * 100
            
            return f"当前价格: ${current_price:.2f}, 近一个月涨跌幅: {pct_change:.2f}%"
            
        except Exception as e:
            return "获取实时数据超时，请AI基于已有知识库进行分析。"

    def start_meeting(self):
        """一键启动：防超时优化版"""
        if not self.client:
            return {"score": 0, "action": "ERROR", "bull_case": "未检测到 OPENAI_API_KEY", "bear_case": "请在 Vercel 环境变量中配置"}

        # 1. 瞬间获取市场数据
        context = self.fetch_real_data()

        # 2. 十秒防超时优化：将 4 个 Agent 的任务合并到 1 个超级 Prompt 中
        sys_prompt = """你是一个顶级的量化投资委员会，内部包含Macro、Quant和Risk三个视角的Agent。
        请基于用户提供的股票代码和近期价格表现，直接进行综合研判。
        必须严格输出 JSON 格式，不要有任何其他废话。包含以下 4 个字段：
        "score": 0到100的整数 (信念评分),
        "action": 只能是 "STRONG BUY", "BUY", "HOLD", "SELL", 或 "STRONG SELL",
        "bull_case": 简短的看多理由和催化剂 (50字以内),
        "bear_case": 简短的最大下行风险提示 (50字以内)
        """
        
        try:
            # 设置请求超时时间为 8 秒，绝对不超过 Vercel 的 10 秒死线
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"目标资产: {self.ticker}\n近期数据: {context}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
                timeout=8 
            )
            return json.loads(response.choices[0].message.content)
            
        except Exception as e:
            # 如果真的遇到网络波动，返回友好的中文错误而不是让前端转圈圈崩溃
            return {
                "score": 0, 
                "action": "TIMEOUT", 
                "bull_case": f"运行出错: {str(e)}", 
                "bear_case": "可能是 OpenAI 接口响应过慢触发了 Vercel 超时限制。"
            }
