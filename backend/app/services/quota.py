from datetime import datetime
from typing import Dict, Tuple


class QuotaService:
    """In-memory quota service (replace with DB + transaction for production)."""

    def __init__(self, free_daily_quota: int = 3):
        self.free_daily_quota = free_daily_quota
        self.membership: Dict[str, str] = {}
        self.daily_quota: Dict[Tuple[str, str], int] = {}

    def get_plan(self, user_id: str) -> str:
        if not user_id:
            raise ValueError('user_id is required')
        return self.membership.get(user_id, 'free')

    def set_plan(self, user_id: str, plan: str) -> None:
        if plan not in {'free', 'pro', 'family'}:
            raise ValueError('invalid plan')
        self.membership[user_id] = plan

    def today(self) -> str:
        return datetime.utcnow().date().isoformat()

    def get_quota(self, user_id: str) -> dict:
        plan = self.get_plan(user_id)
        if plan in {'pro', 'family'}:
            return {'date': self.today(), 'left': -1}

        key = (user_id, self.today())
        left = self.daily_quota.get(key, self.free_daily_quota)
        self.daily_quota[key] = left
        return {'date': key[1], 'left': left}

    def consume(self, user_id: str) -> dict:
        quota = self.get_quota(user_id)
        if quota['left'] == -1:
            return {'allowed': True, **quota}

        if quota['left'] <= 0:
            return {'allowed': False, **quota}

        key = (user_id, self.today())
        next_left = max(0, quota['left'] - 1)
        self.daily_quota[key] = next_left
        return {'allowed': True, 'date': key[1], 'left': next_left}
