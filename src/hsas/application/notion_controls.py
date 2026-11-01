"""User-facing source-sync state and existing Agent review prompt."""

from typing import Any


def controls_snapshot(job: dict[str, Any], closure: dict[str, Any],
                      *, connected: bool) -> dict[str, Any]:
    state = job.get("state", "idle")
    pending = max(0, int(closure.get("pending_total", 0)))
    result = job.get("result") or {}
    retries = result.get("retry_tasks") or []
    label = {"running": "运行中", "failed": "失败", "cancelled": "已取消"}.get(state)
    if not label:
        label = "部分失败" if retries else "待 AI 整理" if pending else "完成"
    if not connected and state != "running":
        label = "等待连接"
    completed, total = max(0, int(job.get("completed", 0))), max(0, int(job.get("total", 0)))
    progress = min(1, completed / total) if total else None
    stage = job.get("detail") or {"starting": "正在准备", "enrollment": "课程列表获取",
        "moodle": "Moodle 课程资料", "sis_course_info": "SIS 课程信息",
        "timetable": "官方课表", "finished": "采集结束"}.get(job.get("stage"), "等待同步请求")
    if not connected:
        stage = "本机后台尚未连接"
    prompt = closure.get("agent_prompt", "")
    if prompt:
        prompt += "\n完成校验写入和 checkpoint 后，调用 sync_notion 将已验证的课程事实同步到 Notion；保留 Notion 个人状态、笔记正文和用户草稿。"
    return {"状态": label, "阶段": stage, "阶段进度": progress,
        "阶段完成": completed, "阶段总数": total, "待整理": pending,
        "任务 ID": job.get("job_id") or "", "AI 整理提示词": prompt,
        "详情": "采集、Agent 整理、校验写入和 Notion 发布分别记录；阶段进度不是整个流程的完成比例。"}
