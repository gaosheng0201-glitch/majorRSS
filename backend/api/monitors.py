from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlmodel import Session, select
from typing import List
from db.database import get_session
from db.models import Subscription, SubscriptionUpdate
from backend.schemas import SubscriptionCreate, SubscriptionResponse, SubscriptionUpdateResponse
from worker_subscription import run_subscription_job

router = APIRouter(prefix="/monitors", tags=["monitors"])

@router.get("/", response_model=List[SubscriptionResponse])
def get_subscriptions(session: Session = Depends(get_session)):
    return session.exec(select(Subscription)).all()

@router.post("/", response_model=SubscriptionResponse)
def create_subscription(sub_in: SubscriptionCreate, session: Session = Depends(get_session)):
    db_sub = Subscription(**sub_in.model_dump())
    session.add(db_sub)
    session.commit()
    session.refresh(db_sub)
    return db_sub

@router.delete("/{sub_id}")
def delete_subscription(sub_id: int, session: Session = Depends(get_session)):
    sub = session.get(Subscription, sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    session.delete(sub)
    session.commit()
    return {"message": f"Subscription {sub_id} deleted successfully"}

@router.post("/{sub_id}/toggle", response_model=SubscriptionResponse)
def toggle_subscription(sub_id: int, session: Session = Depends(get_session)):
    sub = session.get(Subscription, sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    sub.is_active = not sub.is_active
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub

@router.get("/updates", response_model=List[SubscriptionUpdateResponse])
def get_subscription_updates(limit: int = 50, session: Session = Depends(get_session)):
    updates = session.exec(
        select(SubscriptionUpdate)
        .order_by(SubscriptionUpdate.created_at.desc())
        .limit(limit)
    ).all()
    
    response = []
    for u in updates:
        sub = session.get(Subscription, u.subscription_id)
        sub_name = sub.name if sub else "Unknown"
        response.append(SubscriptionUpdateResponse(
            id=u.id,
            subscription_id=u.subscription_id,
            subscription_name=sub_name,
            diff_text=u.diff_text,
            is_read=u.is_read,
            llm_summary=u.llm_summary,
            created_at=u.created_at
        ))
    return response

@router.post("/updates/{update_id}/read")
def mark_update_as_read(update_id: int, session: Session = Depends(get_session)):
    update = session.get(SubscriptionUpdate, update_id)
    if not update:
        raise HTTPException(status_code=404, detail="Update not found")
    update.is_read = True
    session.add(update)
    session.commit()
    return {"message": "Update marked as read"}

@router.post("/run")
def force_run_subscription_check(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_subscription_job)
    return {"message": "Web page monitor change detection triggered"}
