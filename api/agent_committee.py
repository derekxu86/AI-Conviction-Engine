import os
import json
import yfinance as yf
from openai import OpenAI

class InvestmentCommittee:
    def __init__(self, ticker, sector="Global Market"):
        self.ticker = ticker
        self.sector = sector
        self.reports = {}
        
        # 初始化 OpenAI 客户端，它会自动读取 Vercel 中的 OPENAI_API_KEY 环境变量
        api_key = os.environ.get("OPENAI_API_KEY")
        self.client = OpenAI(api_key=api_key) if api_key else None

    def fetch_real_data(self):
        """使用 yfinance 获取真实的近期股票数据"""
        try:
            stock = yf.Ticker(self.ticker)
            # 获取近一个月的历史数据
            hist = stock.history(period="1mo")
            if hist.empty:
                return f"无法获取 {self.ticker} 的数据，可能是代码错误。"
            
            current_price = hist['Close'].iloc[-1]
            past_price = hist['Close'].iloc[0]
            price_change = ((current_price - past_price) / past_price) * 100
            
            context = (
                f"当前价格: ${current_price:.2f}\n"
                f"近一个月价格变化: {price_change:.2f}%\n"
                f"最新日交易量: {int(hist['Volume'].iloc[-1])}\n"
            )
            return context
        except Exception as e:
            return f"数据获取失败: {str(e)}"

    def _call_real_ai(self, prompt, sys_prompt, require_json=False):
        """调用真实的 OpenAI 接口"""
        if not self.client:
            # 防御机制：如果没有配置 API Key，返回友好的报错
            if require_json:
                return json.dumps({"score": 0, "action": "ERROR", "bull_case": "未配置 OpenAI API Key", "bear_case": "请在 Vercel 环境变量中设置 OPENAI_API_KEY"})
            return "API Key 未配置。"

        try:
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": prompt}
            ]
            
            kwargs = {
                "model": "gpt-4o-mini",  # 推荐使用 4o-mini，非常适合这种分析
                "messages": messages,
                "temperature": 0.7
            }
            
            # 如果是主席发话，强制要求大模型输出纯 JSON 格式，防止前端崩溃
            if require_json:
                kwargs["response_format"] = {"type": "json_object"}
                
            response = self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
            
        except Exception as e:
            error_msg = f"AI 调用失败: {str(e)}"
            if require_json:
                return json.dumps({"score": 0, "action": "API ERROR", "bull_case": error_msg, "bear_case": error_msg})
            return error_msg

    def run_macro_agent(self, context_data):
        sys_prompt = "你是 Macro Agent。请用极其简短的1句话（不超过30字）分析该股票当前宏观环境是利好还是利空。"
        user_prompt = f"分析 {self.ticker}。市场数据：\n{context_data}"
        analysis = self._call_real_ai(user_prompt, sys_prompt)
        self.reports['macro'] = analysis

    def run_quant_agent(self, context_data):
        sys_prompt = "你是 Quant Agent。请用极其简短的1句话（不超过30字）分析该股票的技术面和资金面倾向。"
        user_prompt = f"分析 {self.ticker}。市场数据：\n{context_data}"
        analysis = self._call_real_ai(user_prompt, sys_prompt)
        self.reports['quant'] = analysis

    def run_risk_agent(self, context_data):
        sys_prompt = "你是 Risk Agent。请用极其简短的1句话（不超过30字）指出当前最大的下行风险或阻力。"
        user_prompt = f"分析 {self.ticker}。市场数据：\n{context_data}"
        analysis = self._call_real_ai(user_prompt, sys_prompt)
        self.reports['risk'] = analysis

    def run_committee_chair(self):
        sys_prompt = """你是 Committee Chair。阅读前三位 Agent 的报告，给出一个综合结论。
        你必须严格输出 JSON 格式，包含以下 4 个字段：
        "score": 0到100的整数，
        "action": 只能是 "STRONG BUY", "BUY", "HOLD", "SELL", 或 "STRONG SELL",
        "bull_case": 简短的看多逻辑（50字内）,
        "bear_case": 简短的看空逻辑（50字内）"""
        
        compiled_reports = f"Macro: {self.reports.get('macro')}\nQuant: {self.reports.get('quant')}\nRisk: {self.reports.get('risk')}"
        user_prompt = f"请综合评估 {self.ticker}。\n报告汇总：\n{compiled_reports}"
        
        final_decision_str = self._call_real_ai(user_prompt, sys_prompt, require_json=True)
        return json.loads(final_decision_str)

    def start_meeting(self):
        """一键启动真实会议流程"""
        # 1. 抓取真实数据
        context_data = self.fetch_real_data()
        
        # 2. 各位 Agent 基于真实数据发言
        self.run_macro_agent(context_data)
        self.run_quant_agent(context_data)
        self.run_risk_agent(context_data)
        
        # 3. 主席总结并返回结构化数据给前端
        return self.run_committee_chair()
