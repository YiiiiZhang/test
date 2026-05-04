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
    # 新增：用于记录全局所有对话，不受 context.clear() 影响
    full_messages: List[Message] = field(default_factory=list)
    # 日志保存路径
    log_file: str = "conversation_log.json"

    def _save_log(self) -> None:
        """将全量历史覆盖保存到本地 JSON 文件中"""
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
        """清空短期上下文（但不清空全量日志）"""
        self.messages.clear()
        # 在日志中插入一条标记，方便你检查时知道这里发生了阶段性截断
        marker_msg = Message(role="system", content="[Context temporarily cleared by agent for next sub-task]")
        self.full_messages.append(marker_msg)
        self._save_log()