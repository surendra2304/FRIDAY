import sys
from friday.agent.agent import FridayAgent
from friday.core.config import Settings

def test_screen_center_manual():
    settings = Settings()
    agent = FridayAgent(settings=settings)
    
    response = agent.process_message("Move the mouse cursor to the center of the screen.")
    print("RESPONSE:", response.content)
    
    memory = agent.memory.get_messages()
    for msg in memory:
        if msg.tool_calls:
            for tc in msg.tool_calls:
                print("TOOL CALL:", tc.name, tc.arguments)

if __name__ == "__main__":
    test_screen_center_manual()
