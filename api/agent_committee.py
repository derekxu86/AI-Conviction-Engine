# api/agent_committee.py
import json

class InvestmentCommittee:
    def __init__(self, ticker, sector="AI & Tech"):
        self.ticker = ticker
        self.sector = sector
        self.reports = {}

    def _mock_llm_call(self, prompt, role_system_prompt):
        if "Chair" in role_system_prompt:
            return json.dumps({
                "score": 88,
                "action": "STRONG BUY",
                "bull_case": f"{self.ticker} 拥有强大的行业护城河，机构资金持续流入。",
                "bear_case": "宏观经济波动可能带来短期的估值杀跌风险。"
            })
        return "分析完毕"

    def run_committee_chair(self):
        sys_prompt = "你是 Committee Chair。阅读其他Agent报告，输出JSON。"
        user_prompt = f"请综合评估 {self.ticker}。"
        final_decision_str = self._mock_llm_call(user_prompt, sys_prompt)
        self.reports['final_decision'] = json.loads(final_decision_str)
        return self.reports['final_decision']

    def start_meeting(self, context_data):
        return self.run_committee_chair()