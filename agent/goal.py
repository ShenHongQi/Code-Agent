"""自动目标模式：设定目标后 agent 自主迭代直到完成。"""

from __future__ import annotations
from typing import Any


class GoalManager:
    """管理当前活跃目标和自主迭代状态。"""

    def __init__(self):
        self._goal: str | None = None
        self._iterations: int = 0
        self._max_auto_turns: int = 20

    @property
    def active(self) -> bool:
        return self._goal is not None

    @property
    def goal(self) -> str | None:
        return self._goal

    @property
    def iterations(self) -> int:
        return self._iterations

    def set_goal(self, description: str) -> None:
        self._goal = description
        self._iterations = 0

    def clear(self) -> None:
        self._goal = None
        self._iterations = 0

    def tick(self) -> bool:
        """记录一次自动迭代。返回 True 表示可以继续，False 表示达到上限。"""
        self._iterations += 1
        return self._iterations < self._max_auto_turns

    def build_initial_prompt(self) -> str:
        """构建首次目标注入的 prompt。"""
        return (
            f"## 🎯 自动目标模式\n\n"
            f"**目标**: {self._goal}\n\n"
            f"请自主完成此目标。你需要：\n"
            f"1. 分析目标，理解需要完成什么\n"
            f"2. 制定计划并立即执行\n"
            f"3. 逐步调用工具完成所有必要操作\n"
            f"4. 每完成一个步骤，继续下一步，不要等待用户输入\n"
            f"5. 全部完成后，输出一段简洁的完成总结\n\n"
            f"现在开始工作。"
        )

    def build_continue_prompt(self) -> str:
        """构建继续迭代的 prompt。"""
        return (
            f"[System] 目标「{self._goal}」尚未完成。继续工作。\n"
            f"如果已经完成所有工作，输出最终总结并停止。\n"
            f"如果遇到需要用户决策的问题，说明情况并停止。"
        )

    def should_auto_continue(self, last_result: Any, history: Any = None) -> bool:
        """判断是否应该自动继续（基于上一轮结果和历史内容）。"""
        if not self.active:
            return False
        if not self.tick():
            return False
        # fatal_error / context_exhausted → 停止
        if last_result.reason in ("fatal_error", "context_exhausted"):
            return False
        # max_iterations → agent 还在忙，继续
        if last_result.reason == "max_iterations":
            return True
        # natural_stop → 检查 agent 是否表示完成
        if last_result.reason == "natural_stop" and history:
            last_content = self._get_last_assistant_content(history)
            if self._looks_like_done(last_content):
                return False
            return True
        return True

    @staticmethod
    def _get_last_assistant_content(history: Any) -> str:
        for msg in reversed(history.messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                return msg["content"]
        return ""

    @staticmethod
    def _looks_like_done(content: str) -> bool:
        """检测 agent 回复是否表示目标已完成。"""
        import re
        indicators = [
            bool(re.search(r"(全部|所有|目标).{0,10}(完成|完毕|搞定)", content)),
            bool(re.search(r"已[全全部]完成", content)),
            bool(re.search(r"任务完成|工作完成|完成总结", content)),
            bool(re.search(r"(all|everything).{0,10}(done|completed|finished)", content, re.I)),
            bool(re.search(r"总结[：:]", content)),
            bool(re.search(r"以上.{0,5}(全部|所有|即是)", content)),
        ]
        return sum(indicators) >= 1


class PlanManager:
    """设计方案模式：先规划后执行。"""

    def __init__(self):
        self._request: str | None = None
        self._phase: str = "idle"  # idle → planning → awaiting_approval → executing

    @property
    def active(self) -> bool:
        return self._phase != "idle"

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def request(self) -> str | None:
        return self._request

    def start(self, request: str) -> None:
        self._request = request
        self._phase = "planning"

    def move_to_approval(self) -> None:
        self._phase = "awaiting_approval"

    def approve(self) -> None:
        self._phase = "executing"

    def finish(self) -> None:
        self._request = None
        self._phase = "idle"

    def reject(self) -> None:
        self._request = None
        self._phase = "idle"

    def build_planning_prompt(self) -> str:
        """构建规划阶段的 prompt。"""
        return (
            f"## 📋 设计方案模式\n\n"
            f"**需求**: {self._request}\n\n"
            f"请进入规划模式。你需要：\n"
            f"1. **分析**: 阅读相关代码和文件，理解现有架构\n"
            f"2. **设计**: 产出一份清晰的实现方案，包括：\n"
            f"   - 需要修改/创建的文件列表\n"
            f"   - 每个文件的具体改动描述\n"
            f"   - 关键设计决策及理由\n"
            f"   - 可能的风险和注意事项\n"
            f"3. **输出格式**: 用结构化的 Markdown 输出方案\n\n"
            f"⚠️ 在此阶段**只分析和规划**，不要执行任何写操作（不调用 write_file/edit_file/bash 写命令）。\n"
            f"只使用 read_file/glob/grep/list_dir 等读取工具来了解代码。\n\n"
            f"规划完成后，直接输出完整方案。"
        )

    def build_execution_prompt(self) -> str:
        """构建执行阶段的 prompt。"""
        return (
            f"用户已批准上述方案。现在按照方案逐步执行实现。\n"
            f"严格按照方案中列出的步骤操作，如遇到方案中未覆盖的情况，"
            f"选择最合理的方式处理并在完成后说明。"
        )
