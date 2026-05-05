import json
from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class Message:
    role: str
    content: str

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}

@dataclass
class ConversationContext:
    messages: List[Message] = field(default_factory=list)
    # save all of conversation history for logging, not just the recent context used for LLM input
    full_messages: List[Message] = field(default_factory=list)
    log_file: str = "conversation_log.json"

    def _save_log(self) -> None:
        # Save the full conversation history to a JSON file after each update, for debugging and analysis
        try:
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump(
                    [m.to_dict() for m in self.full_messages], 
                    f, 
                    ensure_ascii=False, 
                    indent=2
                )
        except Exception as e:
            print(f"[Warning] Failed to save conversation log: {e}")

    def add_user_message(self, content: str) -> None:
        msg = Message(role="user", content=content)
        self.messages.append(msg)
        self.full_messages.append(msg)
        self._save_log()

    def add_assistant_message(self, content: str) -> None:
        msg = Message(role="assistant", content=content)
        self.messages.append(msg)
        self.full_messages.append(msg)
        self._save_log()

    def last_n_messages(self, n: int) -> List[Message]:
        return self.messages[-n:]

    def to_message_dicts(self) -> List[Dict[str, str]]:
        return [message.to_dict() for message in self.messages]
        
    def clear(self) -> None:
        """Clear the current context messages but keep the full conversation history for logging."""
        self.messages.clear()
        # Add a marker message to indicate context was cleared for the next sub-task, for better log readability *\
        marker_msg = Message(role="system", content="[Context temporarily cleared by agent for next sub-task]")
        self.full_messages.append(marker_msg)
        self._save_log()