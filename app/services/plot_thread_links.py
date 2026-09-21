"""Symmetric plot-thread-to-plot-thread relationship links."""

from __future__ import annotations

from typing import List, Optional, Set

from sqlmodel import Session, delete, select

from app.models import PlotThread, PlotThreadRelatedPlotThreadLink
from app.services.entity_links import parse_form_id_list


def related_plot_thread_ids(db: Session, plot_thread_id: int) -> List[int]:
    rows = db.exec(
        select(PlotThreadRelatedPlotThreadLink).where(
            PlotThreadRelatedPlotThreadLink.plot_thread_id == plot_thread_id
        )
    ).all()
    return [row.related_plot_thread_id for row in rows if row.related_plot_thread_id is not None]


def load_related_plot_threads(db: Session, campaign_id: int, plot_thread_id: int) -> List[PlotThread]:
    ids = related_plot_thread_ids(db, plot_thread_id)
    if not ids:
        return []
    return db.exec(
        select(PlotThread)
        .where(PlotThread.campaign_id == campaign_id, PlotThread.id.in_(ids))
        .order_by(PlotThread.title)
    ).all()


def _link_exists(db: Session, left_id: int, right_id: int) -> bool:
    return (
        db.exec(
            select(PlotThreadRelatedPlotThreadLink).where(
                PlotThreadRelatedPlotThreadLink.plot_thread_id == left_id,
                PlotThreadRelatedPlotThreadLink.related_plot_thread_id == right_id,
            )
        ).first()
        is not None
    )


def _add_symmetric_link(db: Session, left_id: int, right_id: int) -> None:
    if left_id == right_id:
        return
    if not _link_exists(db, left_id, right_id):
        db.add(PlotThreadRelatedPlotThreadLink(plot_thread_id=left_id, related_plot_thread_id=right_id))
    if not _link_exists(db, right_id, left_id):
        db.add(PlotThreadRelatedPlotThreadLink(plot_thread_id=right_id, related_plot_thread_id=left_id))


def _remove_symmetric_link(db: Session, left_id: int, right_id: int) -> None:
    db.exec(
        delete(PlotThreadRelatedPlotThreadLink).where(
            PlotThreadRelatedPlotThreadLink.plot_thread_id == left_id,
            PlotThreadRelatedPlotThreadLink.related_plot_thread_id == right_id,
        )
    )
    db.exec(
        delete(PlotThreadRelatedPlotThreadLink).where(
            PlotThreadRelatedPlotThreadLink.plot_thread_id == right_id,
            PlotThreadRelatedPlotThreadLink.related_plot_thread_id == left_id,
        )
    )


def replace_plot_thread_related_links(
    db: Session,
    campaign_id: int,
    plot_thread_id: int,
    related_threads: List[PlotThread],
    *,
    session_id: Optional[int] = None,
) -> None:
    old_related_ids: Set[int] = set(related_plot_thread_ids(db, plot_thread_id))
    new_related_ids: Set[int] = {
        thread.id for thread in related_threads if thread.id and thread.id != plot_thread_id
    }

    for related_id in old_related_ids - new_related_ids:
        _remove_symmetric_link(db, plot_thread_id, related_id)

    for related_id in new_related_ids - old_related_ids:
        _add_symmetric_link(db, plot_thread_id, related_id)

    from app.services.relationship_history import log_relationship_diff

    log_relationship_diff(
        db,
        campaign_id,
        "threads",
        plot_thread_id,
        "threads",
        old_related_ids,
        new_related_ids,
        session_id=session_id,
    )


def load_related_plot_thread_options(
    db: Session,
    campaign_id: int,
    plot_thread_id: int,
    selected_ids: Optional[List[str]] = None,
) -> List[dict]:
    from app.deps import related_options

    threads = db.exec(
        select(PlotThread).where(PlotThread.campaign_id == campaign_id).order_by(PlotThread.title)
    ).all()
    choices = [thread for thread in threads if thread.id != plot_thread_id]
    current_ids = (
        set(parse_form_id_list(selected_ids))
        if selected_ids is not None
        else set(related_plot_thread_ids(db, plot_thread_id))
    )
    return related_options(choices, current_ids)
