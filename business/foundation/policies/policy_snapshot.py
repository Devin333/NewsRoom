from business.foundation.models import BusinessPolicyProfile, BusinessPolicySnapshot


def create_policy_snapshot(run_id: str, profiles: list[BusinessPolicyProfile]) -> BusinessPolicySnapshot:
    return BusinessPolicySnapshot.create(run_id, profiles)


__all__ = ["create_policy_snapshot"]
