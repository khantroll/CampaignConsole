"""Safe permanent deletion for application-local users."""

from typing import List, Tuple

from sqlmodel import Session, select

from app.models import AppSession, Campaign, CampaignMembership, PlayerReveal, RevealAudience, User


def user_delete_blockers(db: Session, target: User, current_user_id: int) -> List[str]:
    blockers: List[str] = []
    if target.id == current_user_id:
        blockers.append("You cannot delete the account you are currently using.")

    if target.is_admin and target.is_active:
        other_active_admin = db.exec(
            select(User.id).where(
                User.is_admin == True,  # noqa: E712
                User.is_active == True,  # noqa: E712
                User.id != target.id,
            )
        ).first()
        if not other_active_admin:
            blockers.append("You cannot delete the last active administrator.")

    owner_memberships = db.exec(
        select(CampaignMembership).where(
            CampaignMembership.user_id == target.id,
            CampaignMembership.role == "owner",
        )
    ).all()
    orphaned_names: List[str] = []
    for membership in owner_memberships:
        another_owner = db.exec(
            select(CampaignMembership.id).where(
                CampaignMembership.campaign_id == membership.campaign_id,
                CampaignMembership.role == "owner",
                CampaignMembership.user_id != target.id,
            )
        ).first()
        if not another_owner:
            campaign = db.get(Campaign, membership.campaign_id)
            orphaned_names.append(campaign.name if campaign else f"Campaign {membership.campaign_id}")
    if orphaned_names:
        blockers.append(
            "Assign another owner before deleting this user for: " + ", ".join(sorted(orphaned_names))
        )
    return blockers


def delete_local_user(db: Session, target: User, current_user_id: int) -> Tuple[bool, str]:
    blockers = user_delete_blockers(db, target, current_user_id)
    if blockers:
        return False, " ".join(blockers)

    memberships = db.exec(
        select(CampaignMembership).where(CampaignMembership.user_id == target.id)
    ).all()
    membership_ids = [membership.id for membership in memberships if membership.id is not None]

    if membership_ids:
        audience_rows = db.exec(
            select(RevealAudience).where(RevealAudience.membership_id.in_(membership_ids))
        ).all()
        for row in audience_rows:
            db.delete(row)

    for membership in memberships:
        db.delete(membership)

    for session in db.exec(select(AppSession).where(AppSession.user_id == target.id)).all():
        db.delete(session)

    authored_reveals = db.exec(
        select(PlayerReveal).where(PlayerReveal.created_by_user_id == target.id)
    ).all()
    for reveal in authored_reveals:
        reveal.created_by_user_id = None
        db.add(reveal)

    db.delete(target)
    db.commit()
    return True, "User deleted. Campaign content and player characters were retained."
