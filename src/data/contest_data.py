"""Contest MOCK data loading and cross-source service-context assembly."""

from __future__ import annotations

import json
import logging
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

SPREADSHEET_NS = {
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
BUSINESS_FIELDS = {
    "订单号", "工单号", "关联订单号", "商品名称", "商品货号", "数量",
    "实付金额(元)", "退款金额(元)", "订单状态", "工单状态", "任务状态", "转账状态",
    "下单时间", "付款时间", "发货时间", "创建时间", "完成时间", "快递公司",
    "物流单号", "补发物流单号", "工单类型", "问题类型", "类型", "售后原因",
    "症状描述", "是否停用", "是否就医", "不适部位", "用后多久出现",
    "产品批次号", "使用商品", "是否异常", "包裹类型", "签收建议",
    "退款编号", "退款问题类型", "退货原因", "赠品",
}
STATUS_FIELDS = {"订单状态", "工单状态", "任务状态", "转账状态", "是否停用", "是否就医"}


def parse_time(value: str) -> datetime | None:
    """Parse supplied local workbook timestamps; malformed dates are not counted."""
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    """Read shared strings without adding a spreadsheet runtime dependency."""
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(part.text or "" for part in item.findall(".//s:t", SPREADSHEET_NS))
        for item in root.findall("s:si", SPREADSHEET_NS)
    ]


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    """Resolve inline, shared-string and primitive worksheet values."""
    value = cell.find("s:v", SPREADSHEET_NS)
    raw = value.text if value is not None else ""
    if cell.attrib.get("t") == "s" and raw:
        return shared_strings[int(raw)]
    if cell.attrib.get("t") == "inlineStr":
        return "".join(part.text or "" for part in cell.findall(".//s:t", SPREADSHEET_NS))
    return raw


def _worksheet_targets(archive: zipfile.ZipFile) -> dict[str, str]:
    """Map relationship IDs to worksheet paths."""
    root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    return {
        item.attrib["Id"]: "xl/" + item.attrib["Target"].lstrip("/")
        for item in root.findall(f"{{{REL_NS}}}Relationship")
        if item.attrib.get("Type", "").endswith("/worksheet")
    }


def load_workbook(path: str | Path) -> dict[str, list[dict[str, str]]]:
    """Load all worksheets except the explanatory data sheet."""
    source = Path(path)
    with zipfile.ZipFile(source) as archive:
        strings = _read_shared_strings(archive)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        targets = _worksheet_targets(archive)
        tables: dict[str, list[dict[str, str]]] = {}
        for sheet in workbook.findall("s:sheets/s:sheet", SPREADSHEET_NS):
            name = sheet.attrib["name"]
            if name == "数据说明":
                continue
            relationship_id = sheet.attrib[f"{{{SPREADSHEET_NS['r']}}}id"]
            root = ET.fromstring(archive.read(targets[relationship_id]))
            rows = root.findall("s:sheetData/s:row", SPREADSHEET_NS)
            if not rows:
                tables[name] = []
                continue
            headers: dict[str, str] = {}
            for cell in rows[0].findall("s:c", SPREADSHEET_NS):
                column = "".join(char for char in cell.attrib["r"] if char.isalpha())
                headers[column] = _cell_value(cell, strings)
            records = []
            for row in rows[1:]:
                values = {}
                for cell in row.findall("s:c", SPREADSHEET_NS):
                    column = "".join(char for char in cell.attrib["r"] if char.isalpha())
                    values[headers.get(column, column)] = _cell_value(cell, strings)
                records.append(values)
            tables[name] = records
    return tables


def export_tables(tables: dict[str, list[dict[str, str]]], output_dir: str | Path) -> Path:
    """Persist an explicit imported snapshot with provenance metadata."""
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        (target / f"{name}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (target / "manifest.json").write_text(
        json.dumps({
            "source_type": "contest_mock",
            "warning": "Synthetic contest data; not production facts.",
            "tables": {name: len(rows) for name, rows in tables.items()},
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


class ContestDataStore:
    """Cross-reference chats, orders and tickets by contest session IDs."""

    TABLE_FILES = {
        "chats": "聊天记录.json",
        "orders": "订单.json",
        "replacement_tickets": "补发换货工单.json",
        "payment_tickets": "线下打款工单.json",
        "logistics_tickets": "物流工单.json",
        "adverse_tickets": "不良反应工单.json",
        "return_tickets": "售后退货工单.json",
    }

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.tables = self._load_tables()
        self._by_session: dict[str, dict[str, list[dict]]] = defaultdict(
            lambda: defaultdict(list))
        self._index()

    def _load_tables(self) -> dict[str, list[dict]]:
        tables = {}
        for key, filename in self.TABLE_FILES.items():
            path = self.data_dir / filename
            tables[key] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        return tables

    def _index(self) -> None:
        for key, rows in self.tables.items():
            for row in rows:
                session_id = str(row.get("会话ID", "")).strip()
                if session_id:
                    self._by_session[session_id][key].append(row)

    @property
    def available(self) -> bool:
        """Whether at least chats from the imported contest snapshot exist."""
        return bool(self.tables["chats"])

    def list_sessions(self, limit: int = 200) -> list[dict]:
        """Return latest buyer-facing sessions for the workbench selector."""
        groups: dict[str, list[dict]] = defaultdict(list)
        for row in self.tables["chats"]:
            groups[str(row.get("会话ID", ""))].append(row)
        sessions = []
        for session_id, messages in groups.items():
            if not session_id:
                continue
            buyers = [row for row in messages if row.get("角色") == "买家"]
            latest = max(messages, key=lambda row: row.get("发送时间", ""))
            first = buyers[0] if buyers else latest
            sessions.append({
                "session_id": session_id,
                "buyer_name": first.get("买家昵称", "未知买家"),
                "latest_time": latest.get("发送时间", ""),
                "latest_message": latest.get("message_text") or latest.get("chat_content", ""),
                "scene_major": first.get("scene_major", "其他服务"),
                "scene_minor": first.get("scene_minor", ""),
                "message_count": len(messages),
                "buyer_message_count": len(buyers),
                "has_order": bool(self._by_session[session_id]["orders"]),
                "has_ticket": any(
                    self._by_session[session_id][key]
                    for key in self.TABLE_FILES if key.endswith("tickets")
                ),
            })
        return sorted(
            sessions,
            key=lambda item: (item["has_ticket"], item["has_order"], item["latest_time"]),
            reverse=True,
        )[:limit]

    def get_session(
        self, session_id: str, message_limit: int = 40, *,
        before_message_id: str | None = None, analysis_mode: str = "snapshot",
    ) -> dict:
        """Bound chats at a buyer message; do not invent historical ticket states."""
        if analysis_mode not in {"snapshot", "replay"}:
            raise ValueError("invalid analysis mode")
        indexed = self._by_session.get(session_id, {})
        all_messages = sorted(indexed.get("chats", []), key=lambda row: (
            row.get("发送时间", ""), int(row.get("消息序号") or 0)))
        buyers = [row for row in all_messages if row.get("角色") == "买家"]
        if before_message_id:
            selected = next((row for row in buyers if row.get("message_id") == before_message_id), None)
            if selected is None:
                raise ValueError("The analysis point must be a buyer message in this session")
        else:
            selected = buyers[-1] if buyers else None
        point = all_messages.index(selected) if selected else len(all_messages) - 1
        messages = all_messages[:point + 1][-message_limit:]
        cutoff = selected.get("发送时间", "") if selected else ""
        orders, tickets = [], []
        omitted = 0
        for row in indexed.get("orders", []):
            if analysis_mode == "replay" and (not row.get("下单时间") or row["下单时间"] > cutoff):
                omitted += 1
                continue
            orders.append(self._business_record(row, cutoff, analysis_mode))
        for key, rows in indexed.items():
            if key.endswith("tickets"):
                for row in rows:
                    if analysis_mode == "replay" and (not row.get("创建时间") or row["创建时间"] > cutoff):
                        omitted += 1
                        continue
                    tickets.append(self._business_record(row, cutoff, analysis_mode))
        buyer = next((row.get("买家昵称") for row in messages if row.get("买家昵称")), "未知买家")
        latest_buyer = selected or {}
        evidence = []
        for row in orders:
            evidence.append({"type": "order", "id": row.get("订单号", ""), "label": "订单",
                             "summary": f"{row.get('商品名称', '')} / {row.get('订单状态', '')}",
                             "fields": row, "basis": analysis_mode})
        for row in tickets:
            evidence.append({"type": "ticket", "id": row.get("工单号", ""), "label": row.get("工单类型") or row.get("问题类型") or row.get("类型", "工单"),
                             "summary": row.get("售后原因") or row.get("问题类型") or row.get("症状描述") or row.get("退款问题类型", ""),
                             "fields": row, "basis": analysis_mode})
        clean_messages = [{
            "message_id": row.get("message_id", ""), "消息序号": row.get("消息序号", ""),
            "发送时间": row.get("发送时间", ""), "角色": row.get("角色", ""),
            "message_text": row.get("message_text", ""), "内容类型": row.get("内容类型", "文本"),
            "关联订单号": row.get("关联订单号", ""),
            "关联工单号": row.get("关联工单号", ""),
            "image_available": False,
        } for row in messages]
        timeline = [{
            "time": row["发送时间"], "type": "message", "label": row["角色"],
            "detail": row["message_text"][:120],
        } for row in clean_messages]
        for item in evidence:
            fields = item["fields"]
            timeline.append({
                "time": fields.get("创建时间") or fields.get("下单时间") or "",
                "type": item["type"], "label": item["label"],
                "detail": f"{item['id']} · {item['summary']}",
            })
        return {
            "source_type": "contest_mock",
            "warning": "赛题提供的虚构 MOCK 数据，仅用于演示。",
            "session_id": session_id,
            "buyer_name": buyer,
            "latest_buyer_message": latest_buyer.get("message_text") or latest_buyer.get("chat_content", ""),
            "scene_major": latest_buyer.get("scene_major", ""),
            "scene_minor": latest_buyer.get("scene_minor", ""),
            "messages": clean_messages,
            "message_choices": [{"id": row["message_id"], "time": row.get("发送时间", ""),
                                 "text": row.get("message_text", "")[:80]} for row in buyers],
            "orders": orders,
            "tickets": tickets,
            "evidence": evidence,
            "analysis_mode": analysis_mode, "analysis_at": cutoff,
            "analysis_point": latest_buyer.get("message_id", ""),
            "omitted_future_records": omitted,
            "basis_warning": "业务状态为附件最终快照，不代表该消息发生时状态。"
            if analysis_mode == "snapshot" else "仅使用当时已存在的记录；附件没有历史状态，状态标为未知。",
            "timeline": sorted(timeline, key=lambda item: item["time"]),
        }

    def identity_candidates(self, session_id: str, cutoff: str) -> list[dict]:
        """List same-name candidates without merging their messages or records."""
        current = self._by_session.get(session_id, {}).get("chats", [])
        if not current:
            return []
        names = {row.get("买家昵称") for row in current if row.get("角色") == "买家"}
        candidates = []
        for candidate in self.list_sessions(1000):
            if candidate["session_id"] == session_id or candidate["buyer_name"] not in names:
                continue
            chats = self._by_session[candidate["session_id"]]["chats"]
            first = min((row.get("发送时间", "") for row in chats), default="")
            if first and first <= cutoff:
                candidates.append({
                    "session_id": candidate["session_id"], "buyer_name": candidate["buyer_name"],
                    "first_contact_at": first, "basis": "masked_name_only_unconfirmed",
                })
        return candidates

    def with_service_history(self, context: dict, identity: dict) -> dict:
        """Add only confirmed past sessions; compute counts from independently timestamped records."""
        context = dict(context)
        cutoff = context["analysis_at"]
        reference = parse_time(cutoff)
        linked = identity["sessions"] if identity["basis"] != "unconfirmed" else [context["session_id"]]
        contacts, refunds, older_messages, older_evidence = [], [], [], []
        same_name = self.identity_candidates(context["session_id"], cutoff)
        known_orders = {item["id"] for item in context["evidence"]}
        for linked_id in dict.fromkeys(linked):
            indexed = self._by_session.get(linked_id, {})
            chats = [row for row in indexed.get("chats", []) if
                     row.get("角色") == "买家" and row.get("发送时间") and row["发送时间"] <= cutoff]
            if chats:
                first = min(row["发送时间"] for row in chats)
                time = parse_time(first)
                if reference and time and reference - timedelta(days=7) <= time <= reference:
                    contacts.append({"session_id": linked_id, "first_contact_at": first})
                if linked_id != context["session_id"]:
                    # Unknown historical business state is kept unknown, even in snapshot mode.
                    last = max(chats, key=lambda row: (row["发送时间"], int(row.get("消息序号") or 0)))
                    detail = self.get_session(linked_id, before_message_id=last["message_id"],
                                              analysis_mode="replay")
                    older_messages.extend({**row, "session_id": linked_id} for row in detail["messages"])
                    for evidence in detail["evidence"]:
                        if evidence["id"] not in known_orders:
                            older_evidence.append({**evidence, "session_id": linked_id})
                            known_orders.add(evidence["id"])
            # Distinguish payment/refund records from refund applications; never infer completion.
            for row in indexed.get("payment_tickets", []):
                time = parse_time(row.get("创建时间", ""))
                if reference and time and reference - timedelta(days=30) <= time <= reference:
                    if row.get("工单号") and row.get("工单号") not in {item["ticket_id"] for item in refunds}:
                        refunds.append({
                            "ticket_id": row["工单号"], "session_id": linked_id,
                            "created_at": row["创建时间"],
                            "description": "退款/打款记录，不代表实际退款完成",
                        })
        older_messages.sort(key=lambda row: (row["发送时间"], row.get("session_id", "")))
        context["service_history"] = {
            "identity_basis": identity["basis"],
            "confirmed_session_ids": linked,
            "candidate_sessions": [item for item in same_name if item["session_id"] not in linked],
            "contacts_7d": contacts, "refund_records_30d": refunds,
            "messages": older_messages[-16:],
            "warning": "脱敏昵称不代表唯一消费者，只有人工确认关系才用于跨会话统计。"
                       "退款记录数不等于退款完成次数。",
        }
        context["evidence"] = context["evidence"] + older_evidence
        context["timeline"] = sorted(
            context["timeline"] + [{
                "time": row["发送时间"], "type": "confirmed_history",
                "label": f"已确认历史 · {row['session_id']}",
                "detail": row["message_text"][:120],
            } for row in older_messages[-16:]],
            key=lambda event: event["time"],
        )
        return context

    @staticmethod
    def _business_record(row: dict, cutoff: str, mode: str) -> dict:
        """Allowlist business facts; exclude accounts, identities and future dates."""
        clean = {key: value for key, value in row.items() if key in BUSINESS_FIELDS}
        if mode == "replay":
            for key in STATUS_FIELDS & clean.keys():
                clean[key] = "历史状态未提供"
            for key in ("付款时间", "发货时间", "完成时间"):
                if clean.get(key, "") > cutoff:
                    clean.pop(key, None)
            # A logistics code without a known pre-cutoff shipping time is not temporal evidence.
            if not clean.get("发货时间"):
                clean.pop("物流单号", None)
                clean.pop("补发物流单号", None)
        return clean

    @staticmethod
    def model_context(context: dict) -> dict:
        """Use only bounded text and explicit evidence, never scene labels or raw chat JSON."""
        history = context.get("service_history", {})
        return {
            "source_type": "contest_mock", "analysis_mode": context.get("analysis_mode", "snapshot"),
            "basis_warning": context.get("basis_warning", ""),
            "analysis_at": context.get("analysis_at", ""),
            "messages": [{
                "role": row.get("角色"), "text": row.get("message_text", "")[:240],
                "order_id": row.get("关联订单号", ""),
                "ticket_id": row.get("关联工单号", ""),
            }
                         for row in context["messages"][-8:]],
            "evidence": context["evidence"],
            "service_history": {
                "identity_basis": history.get("identity_basis", "unconfirmed"),
                "contacts_7d": history.get("contacts_7d", []),
                "refund_records_30d": history.get("refund_records_30d", []),
                "messages": [{
                    "session_id": row["session_id"], "role": row["角色"],
                    "time": row["发送时间"], "text": row["message_text"][:180],
                } for row in history.get("messages", [])[-6:]],
                "warning": history.get("warning", ""),
            },
        }

    def context_text(self, session_id: str) -> str:
        """Render concise structured context for a model prompt."""
        context = self.get_session(session_id)
        messages = "\n".join(
            f"{row.get('角色', '')}: {(row.get('message_text') or row.get('chat_content', ''))[:180]}"
            for row in context["messages"][-8:]
        )
        evidence = "\n".join(
            f"{item['label']} {item['id']}: {item['summary']}" for item in context["evidence"]
        )
        return (
            f"数据来源：赛题提供的虚构 MOCK 数据，仅供人工客服辅助参考。\n"
            f"会话：{context['session_id']}；买家：{context['buyer_name']}\n"
            f"场景：{context['scene_major']} / {context['scene_minor']}\n"
            f"关联业务记录：\n{evidence or '暂无'}\n"
            f"最近对话：\n{messages or '暂无'}"
        )
