
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

    def add_user_message(self, content: str) -> None:
        self.messages.append(Message(role="user", content=content))

    def add_assistant_message(self, content: str) -> None:
        self.messages.append(Message(role="assistant", content=content))

    def last_n_messages(self, n: int) -> List[Message]:
        return self.messages[-n:]

    def to_message_dicts(self) -> List[Dict[str, str]]:
        return [message.to_dict() for message in self.messages]
    
    def clear(self) -> None:
        self.messages.clear()