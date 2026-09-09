"""
FRIDAY & Memora Integration Test
Tests FRIDAY's ability to record 'I like prawns' and retrieve it
when asked 'What is my favourite curry?'.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.friday.memory.memora_client import memora_client

def test_friday_memora():
    print("=" * 70)
    print(">>> TESTING FRIDAY MEMORA INTEGRATION")
    print("=" * 70)

    # 1. Simulate FRIDAY recording user stating "I like prawns"
    user_statement = "I like prawns"
    print(f"\n[Step 1] User tells FRIDAY: '{user_statement}'")
    rec_res = memora_client.record_interaction(
        agent_name="friday",
        user_input=user_statement,
        agent_output="Got it! I will remember that you like prawns.",
        event_type="dialogue"
    )
    print(f"  Memora record status: {rec_res.get('status')}")

    # 2. Simulate subsequent query "what is my favourite curry?"
    query = "what is my favourite curry?"
    print(f"\n[Step 2] User asks: '{query}'")
    context = memora_client.build_context_block("friday", query)
    print(f"  Context generated for FRIDAY prompt:\n{context}")

    assert "prawn" in context.lower(), "Expected prawns in context!"
    print("\n[SUCCESS] FRIDAY successfully recalled 'prawns' for 'favourite curry' query!")

if __name__ == "__main__":
    test_friday_memora()
