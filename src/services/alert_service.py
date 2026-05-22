from __future__ import annotations


class AlertService:
    def __init__(self, alert_repo, telegram_client, dry_run: bool = False, db=None) -> None:
        self.alert_repo = alert_repo
        self.telegram_client = telegram_client
        self.dry_run = dry_run
        self.db = db
        self.batched: list[dict] = []

    def route(self, resolved_event: dict, channel: str = "telegram") -> None:
        level = resolved_event.get("alert_level")
        if level == "critical":
            self.send_if_needed(resolved_event, channel)
        elif level in {"important", "info"}:
            self.batched.append(resolved_event)

    def flush_batched(self, channel: str = "telegram") -> None:
        important = [e for e in self.batched if e.get("alert_level") == "important"]
        if not important:
            self.batched.clear()
            return
        
        summary = ["📋 <b>IMPORTANT ALERTS SUMMARY</b>\n"]
        for event in important[:20]:
            event_text = event.get("summary_text") or event.get("title") or ""
            sentiment_prefix = "⚪"
            
            if self.db and event.get("raw_event_id"):
                try:
                    insight = self.db.llm_insight_repo().get_by_raw_event(event["raw_event_id"])
                    if insight:
                        event_text = insight.get("summary") or event_text
                        sent = str(insight.get("sentiment", "neutral")).lower()
                        if sent == "positive":
                            sentiment_prefix = "🟢"
                        elif sent == "negative":
                            sentiment_prefix = "🔴"
                except Exception:
                    pass
            
            summary.append(f"{sentiment_prefix} <b>{event.get('symbol')}</b>: {event_text}")
            
        message = "\n".join(summary)
        if not self.dry_run and self.telegram_client:
            self.telegram_client.send(message)
        self.batched.clear()

    def send_if_needed(self, resolved_event: dict, channel: str = "telegram") -> None:
        if resolved_event["alert_level"] not in {"critical", "important"}:
            return
        if self.alert_repo.already_sent(resolved_event["resolved_event_id"], channel):
            return
            
        # Try to pull LLM insight if available
        insight = None
        if self.db and resolved_event.get("raw_event_id"):
            try:
                insight = self.db.llm_insight_repo().get_by_raw_event(resolved_event["raw_event_id"])
            except Exception:
                pass

        payload = {
            "symbol": resolved_event.get("symbol"),
            "category": resolved_event.get("primary_category"),
            "alert_level": resolved_event.get("alert_level"),
            "summary_text": resolved_event.get("summary_text"),
        }
        
        if insight:
            payload["summary"] = insight.get("summary") or payload["summary_text"]
            payload["key_facts"] = insight.get("key_facts") or []
            payload["sentiment"] = insight.get("sentiment") or "neutral"
            payload["risk_flags"] = insight.get("risk_flags") or []
            payload["financials"] = insight.get("financials") or {}
            payload["period_label"] = insight.get("period_label")

        alert_id = self.alert_repo.create_pending(resolved_event["resolved_event_id"], channel, payload)
        try:
            if not self.dry_run and self.telegram_client:
                self.telegram_client.send(self._build_message(payload))
            self.alert_repo.mark_sent(alert_id)
        except Exception as exc:
            self.alert_repo.mark_failed(alert_id, str(exc))
            raise

    def _build_message(self, payload: dict) -> str:
        prefix = "🔴 CRITICAL" if payload["alert_level"] == "critical" else "🟡 IMPORTANT"
        
        # Determine emoji for sentiment
        sentiment = str(payload.get("sentiment", "neutral")).lower()
        if sentiment == "positive":
            sent_emoji = "🟢 Positive"
        elif sentiment == "negative":
            sent_emoji = "🔴 Negative"
        else:
            sent_emoji = "⚪ Neutral"

        if "summary" in payload:
            lines = [
                f"🚨 <b>{prefix} ALERT</b>",
                f"🏢 <b>Symbol:</b> {payload.get('symbol')}",
                f"🏷️ <b>Category:</b> {payload.get('category')}",
                f"⚖️ <b>Sentiment:</b> {sent_emoji}",
                "",
                f"📝 <b>Summary:</b> {payload.get('summary')}",
            ]
            
            category = payload.get("category")
            financials = payload.get("financials", {})
            if category == "results" and financials:
                rev = financials.get("revenue_cr")
                pat = financials.get("pat_cr")
                ebitda = financials.get("ebitda_cr")
                eps = financials.get("eps")
                period = financials.get("period_label") or payload.get("period_label") or ""
                
                rev_yoy = financials.get("revenue_yoy_pct")
                rev_qoq = financials.get("revenue_qoq_pct")
                pat_yoy = financials.get("pat_yoy_pct")
                pat_qoq = financials.get("pat_qoq_pct")
                ebitda_yoy = financials.get("ebitda_yoy_pct")
                ebitda_qoq = financials.get("ebitda_qoq_pct")
                
                def format_metric(label, value_cr, yoy_pct, qoq_pct):
                    if value_cr is None:
                        return None
                    try:
                        val_formatted = f"₹{float(value_cr):,.2f} Cr"
                    except (ValueError, TypeError):
                        val_formatted = f"₹{value_cr} Cr"
                    parts = [f"• <b>{label}:</b> {val_formatted}"]
                    
                    comp_parts = []
                    if yoy_pct is not None:
                        try:
                            yoy_val = float(yoy_pct)
                            trend = "🟢" if yoy_val > 0 else "🔴" if yoy_val < 0 else "⚪"
                            sign = "+" if yoy_val > 0 else ""
                            comp_parts.append(f"{trend} {sign}{yoy_val:.1f}% YoY")
                        except (ValueError, TypeError):
                            pass
                    if qoq_pct is not None:
                        try:
                            qoq_val = float(qoq_pct)
                            trend = "🟢" if qoq_val > 0 else "🔴" if qoq_val < 0 else "⚪"
                            sign = "+" if qoq_val > 0 else ""
                            comp_parts.append(f"{trend} {sign}{qoq_val:.1f}% QoQ")
                        except (ValueError, TypeError):
                            pass
                    if comp_parts:
                        parts.append(f" ({' | '.join(comp_parts)})")
                    return "".join(parts)

                perf_lines = []
                r_line = format_metric("Revenue", rev, rev_yoy, rev_qoq)
                if r_line: perf_lines.append(r_line)
                eb_line = format_metric("EBITDA", ebitda, ebitda_yoy, ebitda_qoq)
                if eb_line: perf_lines.append(eb_line)
                p_line = format_metric("Net Profit (PAT)", pat, pat_yoy, pat_qoq)
                if p_line: perf_lines.append(p_line)
                if eps is not None:
                    try:
                        eps_formatted = f"₹{float(eps):,.2f}"
                    except (ValueError, TypeError):
                        eps_formatted = f"₹{eps}"
                    perf_lines.append(f"• <b>EPS:</b> {eps_formatted}")

                if perf_lines:
                    p_hdr = f" ({period})" if period else ""
                    lines.append(f"\n📊 <b>Financial Performance{p_hdr}:</b>")
                    lines.extend(perf_lines)
            
            key_facts = payload.get("key_facts", [])
            if key_facts:
                lines.append("\n🔑 <b>Key Highlights:</b>")
                for fact in key_facts:
                    lines.append(f"• {fact}")
                    
            risk_flags = payload.get("risk_flags", [])
            if risk_flags:
                lines.append("\n⚠️ <b>Risk Flags:</b>")
                for flag in risk_flags:
                    lines.append(f"• {flag}")
                    
            return "\n".join(lines)
        else:
            return (
                f"🚨 <b>{prefix} ALERT</b>\n"
                f"🏢 <b>Symbol:</b> {payload.get('symbol')}\n"
                f"🏷️ <b>Category:</b> {payload.get('category')}\n"
                f"📝 <b>Detail:</b> {payload.get('summary_text')}"
            )