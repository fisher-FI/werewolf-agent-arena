"""信息隔离测试 — 思考链绝不泄露为发言"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from engine.models import AIConfig
from ai.adapter import AIAdapter, AIResponse


class FakeTransport:
    """模拟 LLM 响应：只返回 reasoning_content，content 为空（推理模型常见行为）"""
    def __init__(self, reasoning: str, content: str = ""):
        self.reasoning = reasoning
        self.content = content

    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass

    async def post(self, url, json=None, headers=None):
        class Resp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {
                    "content": self._t.content,
                    "reasoning_content": self._t.reasoning,
                }}]}
        resp = Resp()
        resp._t = self
        return resp


def make_adapter():
    cfg = AIConfig(api_key="test", base_url="http://fake")
    a = AIAdapter(cfg)
    return a


def test_reasoning_never_becomes_speech():
    """content 为空、只有思考链时，发言必须是空而不是思考内容"""
    import ai.adapter as adapter_mod
    reasoning = "我是狼人，我要骗过预言家，假装自己是平民。输出 {\"vote_target\": 3, \"speech\": \"我怀疑3号\"}"
    fake = FakeTransport(reasoning=reasoning, content="")
    a = make_adapter()
    a._http = fake

    # 直接测 _call + _parse_response 链路
    import asyncio
    raw = asyncio.run(a._call([{"role": "user", "content": "test"}]))
    parsed = a._parse_response(raw)
    speech = parsed.get("speech", "")

    assert "我是狼人" not in speech, "思考链泄露为发言！"
    assert "骗过预言家" not in speech, "思考链泄露为发言！"
    # 思考链应该进入 reasoning（观战展示用）
    assert "我是狼人" in parsed.get("reasoning", ""), "思考链应保留在 reasoning 字段"


def test_reasoning_with_json_content():
    """content 是合法 JSON 时，speech 用 content 的，思考链注入 reasoning"""
    import ai.adapter as adapter_mod
    fake = FakeTransport(
        reasoning="思考：3号发言可疑",
        content='{"speech": "我怀疑3号", "vote_target": 3, "confidence": 0.8}',
    )
    a = make_adapter()
    a._http = fake
    import asyncio
    raw = asyncio.run(a._call([{"role": "user", "content": "test"}]))
    parsed = a._parse_response(raw)
    assert parsed.get("speech") == "我怀疑3号"
    assert "思考" in parsed.get("reasoning", "")
    assert parsed.get("vote_target") == 3


def test_make_speech_never_falls_back_to_raw():
    """_parse_response 失败时发言是占位符，不是原始文本"""
    import asyncio
    from engine.models import Player, Role
    from engine.game import GameEngine
    from engine.boards import get_board

    players = [Player(id=f"p{i}", name=f"玩家{i}", seat=i) for i in range(1, 13)]
    eng = GameEngine(players, get_board("ywls"))
    eng.assign_roles()

    a = make_adapter()
    # 模拟 _call 返回无法解析的垃圾（理论上不会，但防御）
    async def bad_call(messages, temperature=None):
        return "不是 JSON 的纯文本思考链"
    a._call = bad_call

    resp = asyncio.run(a.make_speech(eng, "p1"))
    assert resp.content == "[本回合未发言]", f"发言应为占位符，实际: {resp.content}"
    assert "不是 JSON" not in resp.content


# ─── JSON 修复链 ───

class TestJsonRepair:
    def test_bad_json_triggers_repair(self):
        """第一次返回坏 JSON，回炉后返回合法 JSON"""
        import asyncio
        from engine.models import Player
        from engine.game import GameEngine
        from engine.boards import get_board

        players = [Player(id=f"p{i}", name=f"玩家{i}", seat=i) for i in range(1, 13)]
        eng = GameEngine(players, get_board("ywls"))
        eng.assign_roles()

        a = make_adapter()
        calls = []

        async def fake_call(messages, temperature=None):
            calls.append(messages)  # 记录完整消息列表
            if len(calls) == 1:
                return "这不是 JSON 的文本 response"
            return '{"speech": "修复成功", "vote_target": 3}'

        a._call = fake_call
        result = asyncio.run(a._call_json([{"role": "user", "content": "x"}]))
        assert result["speech"] == "修复成功"
        assert result["vote_target"] == 3
        assert len(calls) == 2, "应回炉一次"
        # 修复消息应包含错误提示，且消息数为 3（原2条 + 修复1条）
        repair_msgs = calls[1]
        assert len(repair_msgs) == 3
        assert "不是合法的 JSON" in repair_msgs[2]["content"]

    def test_always_bad_json_returns_empty(self):
        """一直坏 JSON，超限后返回空 dict（不抛异常）"""
        import asyncio
        a = make_adapter()
        async def fake_call(messages, temperature=None):
            return "还是坏 JSON"

        a._call = fake_call
        result = asyncio.run(a._call_json([{"role": "user", "content": "x"}]))
        assert result == {}
