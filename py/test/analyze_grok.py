
import json
import re
from pathlib import Path
from datetime import datetime, timezone

# =========================
# 配置
# =========================

INPUT_FILE = Path(__file__).parent / "prod-grok-backend.json"
OUTPUT_DIR = Path(__file__).parent / "grok_export"

OUTPUT_DIR.mkdir(exist_ok=True)

# =========================
# 时间转换
# =========================


def parse_time(value):
    """解析 Grok 导出的 MongoDB 时间格式"""

    try:
        if isinstance(value, dict):
            ms = int(value["$date"]["$numberLong"])
            dt = datetime.fromtimestamp(
                ms / 1000, tz=timezone.utc
            )
            return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")

        if isinstance(value, str):
            return value

    except (KeyError, ValueError, TypeError, OSError):
        pass

    return "未知时间"


# =========================
# 安全文件名
# =========================

def safe_filename(name):
    name = re.sub(r'[\\/:*?"<>|]', "_", str(name))
    return name.strip()[:100] or "未命名会话"


# =========================
# 恢复当前会话消息链
# =========================

def get_active_messages(conversation, responses):
    """
    从 leaf_response_id 出发，
    根据 parent_response_id 反向追溯，
    最后恢复正向消息顺序。
    """

    response_map = {}

    for item in responses:
        response = item.get("response", {})
        response_id = response.get("_id")

        if response_id:
            response_map[response_id] = response

    leaf_id = conversation.get("leaf_response_id")

    if not leaf_id or leaf_id not in response_map:
        # 没有有效叶节点时，退化为按时间排序
        return sorted(
            response_map.values(),
            key=lambda x: parse_time(x.get("create_time"))
        )

    messages = []
    visited = set()
    current_id = leaf_id

    while current_id and current_id in response_map:

        if current_id in visited:
            print("警告：发现循环消息关系", current_id)
            break

        visited.add(current_id)

        current = response_map[current_id]
        messages.append(current)

        current_id = current.get("parent_response_id")

    messages.reverse()

    return messages


# =========================
# 提取单个会话
# =========================

def export_conversation(item, index):

    conversation = item.get("conversation", {})
    responses = item.get("responses", [])

    title = conversation.get("title") or f"会话{index}"
    conversation_id = conversation.get("id", "")
    messages = get_active_messages(conversation, responses)

    lines = []

    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- 会话ID：{conversation_id}")
    lines.append(f"- 创建时间：{parse_time(conversation.get('create_time'))}")
    lines.append(f"- 修改时间：{parse_time(conversation.get('modify_time'))}")
    lines.append(f"- 消息数量：{len(messages)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for i, msg in enumerate(messages, 1):

        sender = msg.get("sender", "unknown")
        content = msg.get("message", "")
        timestamp = parse_time(msg.get("create_time"))

        if sender == "human":
            role = "用户"
        elif sender == "assistant":
            role = "Grok"
        else:
            role = sender

        lines.append(f"## {i}. {role}")
        lines.append("")
        lines.append(f"> 时间：{timestamp}")
        lines.append("")

        if content:
            lines.append(content)
        else:
            lines.append("（此消息没有普通文本正文）")

        lines.append("")
        lines.append("---")
        lines.append("")

    result = "\n".join(lines)

    filename = (
        f"{index:03d}_"
        f"{safe_filename(title)}.md"
    )

    output_path = OUTPUT_DIR / filename
    output_path.write_text(result, encoding="utf-8")

    return result, len(messages), output_path


# =========================
# 主程序
# =========================

def main():

    with INPUT_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    conversations = data.get("conversations", [])

    all_content = []
    total_messages = 0

    print("=" * 50)
    print("Grok 会话解析开始")
    print("=" * 50)

    for index, item in enumerate(conversations, 1):

        result, count, path = export_conversation(
            item, index
        )

        all_content.append(result)
        total_messages += count

        print(f"[完成] {path.name}，{count} 条消息")

    # 导出全部会话合并文件
    merged_path = OUTPUT_DIR / "全部Grok会话.md"

    merged_path.write_text(
        "\n\n".join(all_content),
        encoding="utf-8"
    )

    # 输出统计
    print("\n" + "=" * 50)
    print("解析完成")
    print("会话总数：", len(conversations))
    print("消息总数：", total_messages)
    print("导出目录：", OUTPUT_DIR.resolve())
    print("合并文件：", merged_path.resolve())
    print("=" * 50)


if __name__ == "__main__":
    main()
