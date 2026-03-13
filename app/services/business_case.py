from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(slots=True)
class BusinessCaseResult:
    monthly_leads: int | None = None
    avg_ticket: float | None = None
    conversion_rate: float | None = None
    lost_leads_monthly: float | None = None
    recoverable_leads_monthly: float | None = None
    additional_revenue_monthly: float | None = None
    payback_months: float | None = None
    assumptions: list[str] = field(default_factory=list)
    summary: str = ""


class BusinessCaseCalculator:
    IMPLEMENTATION_PRICE = 200_000
    MONTHLY_SUPPORT_PRICE = 20_000
    DEFAULT_CONVERSION_RATE = 0.2
    DEFAULT_RECOVERY_SHARE = 0.6

    def calculate(self, qualification_data: dict) -> BusinessCaseResult | None:
        monthly_leads = self._to_int(qualification_data.get("monthly_leads"))
        avg_ticket = self._to_money(qualification_data.get("avg_ticket"))
        conversion_rate = self._to_ratio(qualification_data.get("conversion_rate"))
        lost_ratio = self._to_lost_ratio(
            raw=qualification_data.get("lost_dialogs"),
            monthly_leads=monthly_leads,
            response_time=str(qualification_data.get("response_time") or ""),
        )

        if monthly_leads is None and avg_ticket is None and lost_ratio is None:
            return None

        result = BusinessCaseResult(
            monthly_leads=monthly_leads,
            avg_ticket=avg_ticket,
            conversion_rate=conversion_rate,
        )

        if monthly_leads is None:
            result.assumptions.append("Не удалось точно определить объем заявок в месяц.")
        if avg_ticket is None:
            result.assumptions.append("Не удалось точно определить средний чек.")

        if conversion_rate is None:
            conversion_rate = self.DEFAULT_CONVERSION_RATE
            result.assumptions.append(
                "Для расчета использована ориентировочная конверсия в продажу 20%."
            )

        if lost_ratio is None:
            lost_ratio = 0.12
            result.assumptions.append(
                "Для расчета использована ориентировочная доля потерь 12% от входящих заявок."
            )

        if monthly_leads is not None:
            lost_leads_monthly = round(monthly_leads * lost_ratio, 1)
            recoverable_leads = round(lost_leads_monthly * self.DEFAULT_RECOVERY_SHARE, 1)
            result.lost_leads_monthly = lost_leads_monthly
            result.recoverable_leads_monthly = recoverable_leads

            if avg_ticket is not None:
                additional_revenue = round(recoverable_leads * conversion_rate * avg_ticket, 2)
                result.additional_revenue_monthly = additional_revenue
                if additional_revenue > 0:
                    result.payback_months = round(
                        self.IMPLEMENTATION_PRICE / max(additional_revenue - self.MONTHLY_SUPPORT_PRICE, 1.0),
                        1,
                    )

        result.summary = self._build_summary(result)
        return result

    def _build_summary(self, result: BusinessCaseResult) -> str:
        parts: list[str] = []
        if result.monthly_leads is not None:
            parts.append(f"около {result.monthly_leads} заявок в месяц")
        if result.lost_leads_monthly is not None:
            parts.append(f"теряется примерно {self._format_number(result.lost_leads_monthly)} заявок")
        if result.additional_revenue_monthly is not None:
            parts.append(
                f"потенциально можно вернуть до {self._format_money(result.additional_revenue_monthly)} выручки в месяц"
            )
        if not parts:
            return ""
        return "Если смотреть на текущую ситуацию, у вас " + ", а с AI-менеджером " + parts[-1] + "."

    def _to_int(self, value: object) -> int | None:
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, float):
            return int(value) if value >= 0 else None
        if not isinstance(value, str):
            return None
        digits = re.sub(r"[^\d]", "", value)
        if not digits:
            return None
        try:
            return int(digits)
        except ValueError:
            return None

    def _to_money(self, value: object) -> float | None:
        if isinstance(value, (int, float)):
            return float(value) if value > 0 else None
        if not isinstance(value, str):
            return None

        lowered = value.lower().replace(" ", "")
        number_match = re.search(r"(\d+(?:[.,]\d+)?)", lowered)
        if not number_match:
            return None

        try:
            number = float(number_match.group(1).replace(",", "."))
        except ValueError:
            return None

        if "млн" in lowered:
            number *= 1_000_000
        elif "тыс" in lowered or "к" in lowered:
            number *= 1_000

        return round(number, 2) if number > 0 else None

    def _to_ratio(self, value: object) -> float | None:
        if isinstance(value, (int, float)):
            numeric = float(value)
            if numeric <= 0:
                return None
            return numeric / 100 if numeric > 1 else numeric
        if not isinstance(value, str):
            return None
        match = re.search(r"(\d+(?:[.,]\d+)?)", value.replace(" ", ""))
        if not match:
            return None
        try:
            numeric = float(match.group(1).replace(",", "."))
        except ValueError:
            return None
        if numeric <= 0:
            return None
        return numeric / 100 if numeric > 1 else numeric

    def _to_lost_ratio(self, *, raw: object, monthly_leads: int | None, response_time: str) -> float | None:
        if isinstance(raw, (int, float)):
            numeric = float(raw)
            if numeric <= 0:
                return None
            if monthly_leads and numeric <= monthly_leads:
                return min(numeric / monthly_leads, 1.0)
            return min((numeric / 100) if numeric > 1 else numeric, 1.0)

        if isinstance(raw, str):
            lowered = raw.lower().strip()
            if lowered in {"неизвестно", "unknown"}:
                return self._response_time_assumption(response_time)
            match = re.search(r"(\d+(?:[.,]\d+)?)", lowered.replace(" ", ""))
            if match:
                try:
                    numeric = float(match.group(1).replace(",", "."))
                except ValueError:
                    numeric = 0.0
                if numeric > 0:
                    if "%" in lowered:
                        return min(numeric / 100, 1.0)
                    if monthly_leads and numeric <= monthly_leads:
                        return min(numeric / monthly_leads, 1.0)
                    return min((numeric / 100) if numeric > 1 else numeric, 1.0)
            if any(token in lowered for token in ("есть", "теря", "пропада", "не довод")):
                return self._response_time_assumption(response_time) or 0.12

        return self._response_time_assumption(response_time)

    def _response_time_assumption(self, response_time: str) -> float | None:
        lowered = response_time.lower()
        if not lowered:
            return None
        if "час" in lowered:
            return 0.18
        match = re.search(r"(\d+)", lowered)
        if not match:
            return None
        minutes = int(match.group(1))
        if minutes <= 5:
            return 0.05
        if minutes <= 30:
            return 0.08
        return 0.12

    def _format_money(self, value: float) -> str:
        rounded = int(round(value))
        return f"{rounded:,}".replace(",", " ") + " руб."

    def _format_number(self, value: float) -> str:
        if abs(value - int(value)) < 0.001:
            return str(int(value))
        return f"{value:.1f}".replace(".", ",")
