import anthropic

from config import settings

RESET = "\033[0m"
DIM = "\033[2m"
MAGENTA = "\033[35m"

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def run_agent_loop(
    messages: list[dict],
    system: str,
    tools: list[dict],
    execute_tool,
    model: str | None = None,
    max_iterations: int = 20,
    label: str = "",
    on_first_output=None,
    output_fn=None,
) -> tuple[str, dict]:
    """Tool-use loop: call LLM, execute tools, repeat until done."""
    model = model or settings.claude_model
    client = _get_client()
    prefix = f"[{label}] " if label else ""
    usage = {"input_tokens": 0, "output_tokens": 0}
    tools_used = []
    notified = False
    _output = output_fn or (lambda s: print(s, flush=True))

    def _notify():
        nonlocal notified
        if not notified and on_first_output:
            on_first_output()
            notified = True

    for _ in range(max_iterations):
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=messages,
            tools=tools,
        )

        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason == "tool_use":
            _notify()
            tool_results = []
            for block in assistant_content:
                if block.type == "tool_use":
                    tools_used.append(block.name)
                    _output(f"  {prefix}{MAGENTA}[TOOL]{RESET} {DIM}{block.name}({block.input}){RESET}")
                    result = execute_tool(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(result),
                        }
                    )
            messages.append({"role": "user", "content": tool_results})
        elif response.stop_reason == "end_turn":
            _notify()
            stats = {"usage": usage, "tools_used": tools_used}
            for block in assistant_content:
                if hasattr(block, "text"):
                    return block.text, stats
            return "", stats
        else:
            break

    _notify()
    return "(max iterations reached)", {"usage": usage, "tools_used": tools_used}


def simple_completion(prompt: str, system: str = "", model: str | None = None) -> str:
    """One-shot completion without tools."""
    model = model or settings.claude_model
    client = _get_client()
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    return ""
