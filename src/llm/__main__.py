"""Smoke test: `python -m src.llm "your prompt"` sends one prompt to the agent model."""
import sys

from src.ports.factory import build_deps


def main() -> None:
    prompt = " ".join(sys.argv[1:]) or "Reply with the single word: ok"
    llm = build_deps("eval").agent_llm
    print(f"[{llm.model}] {llm.complete(prompt)}")


if __name__ == "__main__":
    main()
