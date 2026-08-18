import os
from friday.agent.agent import FridayAgent
from friday.voice.mock_provider import MockVoiceProvider

# Ensure environment is loaded (Settings will read .env automatically)

def main():
    # Create a FridayAgent with default settings (mock LLM provider will be used)
    agent = FridayAgent()
    # Define mock transcripts for the voice session
    transcripts = [
        "What is your name?",
        "What time is it?"
    ]
    # Initialize mock voice provider
    voice = MockVoiceProvider(transcripts)
    # Run the voice session; this will process each transcript through the agent
    voice.run_session(agent)
    print("Mock voice session completed.")

if __name__ == "__main__":
    main()
