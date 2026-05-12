import os
import json
import requests
from openai import OpenAI

class InvestmentCommittee:
    def __init__(self, ticker):
        self.ticker = ticker.upper()
        self.api_key = os.environ.get("OPENAI_API_KEY")

    def get_market_data(self):
        """2秒极限抓取，抓不到就立刻放弃，绝不拖死系统"""
        try:
            url = f"https://query2.finance.yahoo.com/v8/finance/chart/{self.ticker}?interval=1d&range=5d"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            # 极限熔断：只等2秒
            res = requests.get(url, headers=headers, timeout=2)
            data = res.json()
            price = data['chart']['result'][0]['meta']['regularMarketPrice']
            return f"最新真实价格: ${price}"
        except Exception:
            return "实时数据被拦截或超时，请基于已有知识库和近期宏观趋势进行分析。"

    def start_meeting(self):
        if not self.api_key:
            return {"score": 0, "action": "KEY MISSING", "bull_case": "请检查 Vercel 环境变量", "bear_case": "未检测到 OPENAI_API_KEY"}
        
        client = OpenAI(api_key=self.api_key)
        context = self.get_market_data()
        
        sys_prompt = """你是一个量化投资委员会。请根据股票代码和提供的数据直接综合研判。
        严格输出JSON，不要有任何 Markdown 标记，包含4个字段：
        {"score": 0-100整数, "action": "BUY/SELL/HOLD", "bull_case": "看多理由", "bear_case": "看空理由"}"""
        
        try:
            # 6秒极限思考：防止被 Vercel 10秒规则击杀
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"目标股票: {self.ticker}\n市场状态: {context}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
                timeout=6 
            )
            return json.loads(res.choices[0].message.content)
            
        except Exception as e:
            # 即使 AI 挂了，也要优雅地把错误传给前端面板
            error_str = str(e)
            if "insufficient_quota" in error_str:
                error_str = "OpenAI 账号余额不足或未绑定信用卡！"
            return {"score": 0, "action": "AI ERROR", "bull_case": "OpenAI 调用失败", "bear_case": error_str}
