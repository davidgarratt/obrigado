import uuid
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import httpx

from app.database import get_db_connection, utc_now_iso

logger = logging.getLogger(__name__)

class TokenService:
    def __init__(self):
        pass

    def record_usage(
        self,
        provider: str,
        model: str,
        activity_type: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Record an LLM invocation's token usage, compute estimated cost,
        and store it in token_usage_logs.
        """
        prompt_tokens = max(0, int(prompt_tokens or 0))
        completion_tokens = max(0, int(completion_tokens or 0))
        if total_tokens is None or total_tokens <= 0:
            total_tokens = prompt_tokens + completion_tokens
        else:
            total_tokens = max(total_tokens, prompt_tokens + completion_tokens)

        # Lookup pricing
        pricing = self.get_model_pricing(model)
        input_rate = pricing.get("input_cost_per_million", 0.15)
        output_rate = pricing.get("output_cost_per_million", 0.60)

        # Calculate estimated cost in USD
        estimated_cost = round(
            (prompt_tokens / 1_000_000.0) * input_rate +
            (completion_tokens / 1_000_000.0) * output_rate,
            7
        )

        log_id = str(uuid.uuid4())
        created_at = utc_now_iso()
        meta_json = json.dumps(metadata or {})

        conn = get_db_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO token_usage_logs (
                        id, created_at, provider, model, activity_type,
                        prompt_tokens, completion_tokens, total_tokens,
                        estimated_cost, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        log_id, created_at, provider.lower(), model, activity_type.lower(),
                        prompt_tokens, completion_tokens, total_tokens,
                        estimated_cost, meta_json
                    )
                )
        except Exception as e:
            logger.error(f"Failed to record token usage: {e}")
        finally:
            conn.close()

        return {
            "id": log_id,
            "created_at": created_at,
            "provider": provider.lower(),
            "model": model,
            "activity_type": activity_type.lower(),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "estimated_cost": estimated_cost
        }

    def get_model_pricing(self, model_id: str) -> Dict[str, Any]:
        """Get model pricing rates (input & output per 1M tokens)."""
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT * FROM model_pricing WHERE LOWER(model_id) = LOWER(?)",
                (model_id,)
            ).fetchone()
            if not row:
                # Try prefix or substring match
                row = conn.execute(
                    "SELECT * FROM model_pricing WHERE LOWER(?) LIKE '%' || LOWER(model_id) || '%' ORDER BY LENGTH(model_id) DESC LIMIT 1",
                    (model_id,)
                ).fetchone()
            if not row:
                # Default fallback rate
                row = conn.execute(
                    "SELECT * FROM model_pricing WHERE model_id = 'default'"
                ).fetchone()

            if row:
                return dict(row)
            return {
                "model_id": model_id,
                "provider": "unknown",
                "display_name": model_id,
                "input_cost_per_million": 0.15,
                "output_cost_per_million": 0.60
            }
        finally:
            conn.close()

    def get_all_pricing(self) -> List[Dict[str, Any]]:
        """Return all configured model pricing entries."""
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM model_pricing ORDER BY provider ASC, model_id ASC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def set_model_pricing(
        self,
        model_id: str,
        provider: str,
        display_name: str,
        input_cost_per_million: float,
        output_cost_per_million: float,
        is_auto_fetched: bool = False
    ) -> Dict[str, Any]:
        """Upsert custom or updated pricing for a model."""
        now_str = utc_now_iso()
        conn = get_db_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO model_pricing (
                        model_id, provider, display_name,
                        input_cost_per_million, output_cost_per_million,
                        is_auto_fetched, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(model_id) DO UPDATE SET
                        provider = excluded.provider,
                        display_name = excluded.display_name,
                        input_cost_per_million = excluded.input_cost_per_million,
                        output_cost_per_million = excluded.output_cost_per_million,
                        is_auto_fetched = excluded.is_auto_fetched,
                        updated_at = excluded.updated_at
                    """,
                    (
                        model_id.strip(), provider.strip().lower(), display_name.strip(),
                        float(input_cost_per_million), float(output_cost_per_million),
                        1 if is_auto_fetched else 0, now_str
                    )
                )
            return self.get_model_pricing(model_id)
        finally:
            conn.close()

    def delete_model_pricing(self, model_id: str) -> bool:
        if model_id.lower() == "default":
            return False
        conn = get_db_connection()
        try:
            with conn:
                conn.execute("DELETE FROM model_pricing WHERE model_id = ?", (model_id,))
            return True
        finally:
            conn.close()

    def fetch_openrouter_pricing(self) -> Dict[str, Any]:
        """
        Auto-fetch latest live pricing from OpenRouter API and update model_pricing table.
        """
        url = "https://openrouter.ai/api/v1/models"
        synced_count = 0
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(url)
                if res.status_code != 200:
                    return {"success": False, "error": f"HTTP {res.status_code}: {res.text}"}
                data = res.json().get("data", [])

            now_str = utc_now_iso()
            conn = get_db_connection()
            try:
                with conn:
                    for m in data:
                        mid = m.get("id")
                        if not mid:
                            continue
                        pricing = m.get("pricing", {})
                        # OpenRouter prices are per token (e.g. "0.000003")
                        try:
                            prompt_per_m = float(pricing.get("prompt", 0) or 0) * 1_000_000.0
                            comp_per_m = float(pricing.get("completion", 0) or 0) * 1_000_000.0
                        except (ValueError, TypeError):
                            continue

                        conn.execute(
                            """
                            INSERT INTO model_pricing (
                                model_id, provider, display_name,
                                input_cost_per_million, output_cost_per_million,
                                is_auto_fetched, updated_at
                            ) VALUES (?, 'openrouter', ?, ?, ?, 1, ?)
                            ON CONFLICT(model_id) DO UPDATE SET
                                input_cost_per_million = excluded.input_cost_per_million,
                                output_cost_per_million = excluded.output_cost_per_million,
                                is_auto_fetched = 1,
                                updated_at = excluded.updated_at
                            """,
                            (mid, m.get("name") or mid, prompt_per_m, comp_per_m, now_str)
                        )
                        synced_count += 1
            finally:
                conn.close()

            return {"success": True, "models_synced": synced_count}
        except Exception as e:
            logger.error(f"Failed to fetch OpenRouter pricing: {e}")
            return {"success": False, "error": str(e)}

    def get_analytics(
        self,
        timeframe: str = "day", # "day", "week", "month", "year"
        period: int = 30,
        activity: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Aggregate token consumption and costs by time, activity, model, and provider.
        """
        conn = get_db_connection()
        try:
            # 1. Base filter conditions
            where_clauses = ["1=1"]
            params: List[Any] = []

            if activity:
                where_clauses.append("activity_type = ?")
                params.append(activity.lower())
            if model:
                where_clauses.append("model = ?")
                params.append(model)
            if provider:
                where_clauses.append("provider = ?")
                params.append(provider.lower())

            where_str = " AND ".join(where_clauses)

            # 2. KPI Summary Totals
            now = datetime.now(timezone.utc)
            today_str = now.strftime("%Y-%m-%d")
            week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
            month_start = now.strftime("%Y-%m-01")
            year_start = now.strftime("%Y-01-01")

            def fetch_kpi(date_filter_clause: str, extra_param: Optional[str] = None):
                query = f"""
                    SELECT 
                        COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                        COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                        COALESCE(SUM(total_tokens), 0) as total_tokens,
                        COALESCE(SUM(estimated_cost), 0.0) as total_cost,
                        COUNT(*) as request_count
                    FROM token_usage_logs
                    WHERE {where_str} {date_filter_clause}
                """
                p = list(params)
                if extra_param:
                    p.append(extra_param)
                r = conn.execute(query, p).fetchone()
                return {
                    "prompt_tokens": int(r[0]),
                    "completion_tokens": int(r[1]),
                    "total_tokens": int(r[2]),
                    "total_cost": round(float(r[3]), 5),
                    "request_count": int(r[4])
                }

            kpi_today = fetch_kpi("AND created_at >= ?", today_str)
            kpi_week = fetch_kpi("AND created_at >= ?", week_start)
            kpi_month = fetch_kpi("AND created_at >= ?", month_start)
            kpi_year = fetch_kpi("AND created_at >= ?", year_start)
            kpi_all_time = fetch_kpi("")

            # 3. Time Series Aggregation (Day, Week, Month, Year)
            # Choose date formatting based on timeframe
            tf = timeframe.lower()
            if tf == "week":
                group_fmt = "%Y-W%W"
                date_limit = (now - timedelta(weeks=period)).strftime("%Y-%m-%d")
            elif tf == "month":
                group_fmt = "%Y-%m"
                date_limit = (now - timedelta(days=period * 30)).strftime("%Y-%m-%d")
            elif tf == "year":
                group_fmt = "%Y"
                date_limit = "1970-01-01"
            else: # "day"
                group_fmt = "%Y-%m-%d"
                date_limit = (now - timedelta(days=period)).strftime("%Y-%m-%d")

            time_query = f"""
                SELECT 
                    strftime('{group_fmt}', created_at) as bucket,
                    COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(SUM(estimated_cost), 0.0) as cost,
                    COUNT(*) as request_count
                FROM token_usage_logs
                WHERE {where_str} AND created_at >= ?
                GROUP BY bucket
                ORDER BY bucket ASC
            """
            time_params = list(params) + [date_limit]
            time_rows = conn.execute(time_query, time_params).fetchall()

            time_series = [
                {
                    "period": r[0],
                    "prompt_tokens": int(r[1]),
                    "completion_tokens": int(r[2]),
                    "total_tokens": int(r[3]),
                    "cost": round(float(r[4]), 5),
                    "requests": int(r[5])
                }
                for r in time_rows
            ]

            # 4. Activity Breakdown
            act_query = f"""
                SELECT 
                    activity_type,
                    COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(SUM(estimated_cost), 0.0) as cost,
                    COUNT(*) as request_count
                FROM token_usage_logs
                WHERE {where_str}
                GROUP BY activity_type
                ORDER BY total_tokens DESC
            """
            act_rows = conn.execute(act_query, params).fetchall()
            activity_breakdown = [
                {
                    "activity": r[0],
                    "prompt_tokens": int(r[1]),
                    "completion_tokens": int(r[2]),
                    "total_tokens": int(r[3]),
                    "cost": round(float(r[4]), 5),
                    "requests": int(r[5])
                }
                for r in act_rows
            ]

            # 5. Model & Provider Breakdown
            model_query = f"""
                SELECT 
                    provider,
                    model,
                    COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(SUM(estimated_cost), 0.0) as cost,
                    COUNT(*) as request_count
                FROM token_usage_logs
                WHERE {where_str}
                GROUP BY provider, model
                ORDER BY total_tokens DESC
            """
            model_rows = conn.execute(model_query, params).fetchall()
            model_breakdown = [
                {
                    "provider": r[0],
                    "model": r[1],
                    "prompt_tokens": int(r[2]),
                    "completion_tokens": int(r[3]),
                    "total_tokens": int(r[4]),
                    "cost": round(float(r[5]), 5),
                    "requests": int(r[6])
                }
                for r in model_rows
            ]

            # 6. Provider Breakdown
            prov_query = f"""
                SELECT 
                    provider,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(SUM(estimated_cost), 0.0) as cost,
                    COUNT(*) as request_count
                FROM token_usage_logs
                WHERE {where_str}
                GROUP BY provider
                ORDER BY total_tokens DESC
            """
            prov_rows = conn.execute(prov_query, params).fetchall()
            provider_breakdown = [
                {
                    "provider": r[0],
                    "total_tokens": int(r[1]),
                    "cost": round(float(r[2]), 5),
                    "requests": int(r[3])
                }
                for r in prov_rows
            ]

            # 7. Recent Invocations (limit 50)
            recent_query = f"""
                SELECT id, created_at, provider, model, activity_type,
                       prompt_tokens, completion_tokens, total_tokens,
                       estimated_cost, metadata_json
                FROM token_usage_logs
                WHERE {where_str}
                ORDER BY created_at DESC
                LIMIT 50
            """
            recent_rows = conn.execute(recent_query, params).fetchall()
            recent_logs = []
            for r in recent_rows:
                recent_logs.append({
                    "id": r[0],
                    "created_at": r[1],
                    "provider": r[2],
                    "model": r[3],
                    "activity_type": r[4],
                    "prompt_tokens": int(r[5]),
                    "completion_tokens": int(r[6]),
                    "total_tokens": int(r[7]),
                    "estimated_cost": round(float(r[8]), 6),
                    "metadata": json.loads(r[9] or "{}")
                })

            # 8. Available distinct values for UI filters
            distinct_activities = [row[0] for row in conn.execute("SELECT DISTINCT activity_type FROM token_usage_logs ORDER BY activity_type").fetchall()]
            distinct_models = [row[0] for row in conn.execute("SELECT DISTINCT model FROM token_usage_logs ORDER BY model").fetchall()]
            distinct_providers = [row[0] for row in conn.execute("SELECT DISTINCT provider FROM token_usage_logs ORDER BY provider").fetchall()]

            return {
                "timeframe": tf,
                "period": period,
                "kpis": {
                    "today": kpi_today,
                    "this_week": kpi_week,
                    "this_month": kpi_month,
                    "this_year": kpi_year,
                    "all_time": kpi_all_time
                },
                "time_series": time_series,
                "activity_breakdown": activity_breakdown,
                "model_breakdown": model_breakdown,
                "provider_breakdown": provider_breakdown,
                "recent_logs": recent_logs,
                "filter_options": {
                    "activities": distinct_activities,
                    "models": distinct_models,
                    "providers": distinct_providers
                }
            }
        finally:
            conn.close()

    get_token_analytics = get_analytics

token_service = TokenService()
