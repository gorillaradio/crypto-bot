from app.brain.providers import OpenAICompatAdapter, AnthropicAdapter, make_adapter


class _FakeOpenAI:
    def __init__(self): self.last = None
    @property
    def chat(self):
        outer = self
        class Completions:
            def create(self, **kw):
                outer.last = kw
                class M: content = '{"actions":[],"note":"ok"}'
                class C: message = M()
                class R: choices = [C()]
                return R()
        class Chat: completions = Completions()
        return Chat()


def test_openai_adapter_returns_content_and_sends_json_mode():
    fake = _FakeOpenAI()
    out = OpenAICompatAdapter(fake, "deepseek-v4-flash").complete_json("sys", "usr")
    assert out == '{"actions":[],"note":"ok"}'
    assert fake.last["response_format"] == {"type": "json_object"}
    assert fake.last["model"] == "deepseek-v4-flash"


class _FakeAnthropic:
    def __init__(self): self.last = None
    @property
    def messages(self):
        outer = self
        class Messages:
            def create(self, **kw):
                outer.last = kw
                class B: text = '{"actions":[],"note":"a"}'
                class R: content = [B()]
                return R()
        return Messages()


def test_anthropic_adapter_returns_text():
    fake = _FakeAnthropic()
    out = AnthropicAdapter(fake, "claude-haiku-4-5").complete_json("sys", "usr")
    assert out == '{"actions":[],"note":"a"}'
    assert fake.last["system"] == "sys"


def test_make_adapter_selects_type():
    assert isinstance(make_adapter("deepseek", "deepseek-v4-flash"), OpenAICompatAdapter)
    assert isinstance(make_adapter("glm", "glm-4.6"), OpenAICompatAdapter)
    assert isinstance(make_adapter("anthropic", "claude-haiku-4-5"), AnthropicAdapter)
