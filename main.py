from fastapi import FastAPI, Request, Form, Depends, status, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
import uuid
import qrcode
import io
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone

import models
from database import engine, SessionLocal

# -----------------------------------------------------------------------------
# ZENTRALE KONFIGURATION FÜR DEN MONATLICHEN RESET
# hier kannst du den Tag jederzeit ganz einfach anpassen!
# -----------------------------------------------------------------------------
RESET_DAY_OF_MONTH = 25

# -----------------------------------------------------------------------------
# AUTOMATISCHER DATA-CLEANUP & MONTHLY RESET LOGIK
# -----------------------------------------------------------------------------
def cleanup_old_tickets(db: Session):
    zeitlimit = datetime.now(timezone.utc) - timedelta(days=30)
    alte_tickets = db.query(models.JobTicket).filter(models.JobTicket.created_at < zeitlimit)
    anzahl_geloescht = alte_tickets.delete(synchronize_session=False)
    if anzahl_geloescht > 0:
        db.commit()

def check_and_run_monthly_reset(db: Session):
    """
    Prüft, ob der Reset-Tag für die Abrechnung erreicht wurde und ob
    der Vormonat bereits in die Historie überführt und archiviert wurde.
    """
    jetzt = datetime.now()
    
    # Welcher Monat soll gerade abgerechnet werden?
    # Wenn wir vor dem Stichtag (z.B. 25.) sind, gehört das Feedback noch zum Vormonat.
    # Wenn wir am oder nach dem Stichtag sind, rechnen wir den aktuellen Monat ab.
    if jetzt.day < RESET_DAY_OF_MONTH:
        # Beispiel: 10. März -> Wir prüfen, ob der Februar (Abrechnungszeitraum bis 25. Feb) archiviert wurde
        erster_dieses_monats = jetzt.replace(day=1)
        vormonat = erster_dieses_monats - timedelta(days=1)
        target_year = vormonat.year
        target_month = vormonat.month
    else:
        # Beispiel: 26. März -> Wir prüfen/archivieren den März
        target_year = jetzt.year
        target_month = jetzt.month

    year_month_str = f"{target_year}-{target_month:02d}"

    # Prüfen, ob für diesen Zeitraum bereits Einträge in der Historie existieren
    bereits_archiviert = db.query(models.MonthlyHistory).filter_by(year_month=year_month_str).first()

    if not bereits_archiviert:
        print(f"[Reset] Erstelle monatliche Historie für den Zeitraum: {year_month_str}...")
        all_employees = db.query(models.Employee).all()
        
        for emp in all_employees:
            pos = emp.positive_score or 0
            neg = emp.negative_score or 0
            netto = pos - neg
            bonus = min(netto * 5, 100) if netto > 0 else 0

            # 1. Eintrag in die Historie schreiben
            history_entry = models.MonthlyHistory(
                employee_id=emp.id,
                year_month=year_month_str,
                positive_score=pos,
                negative_score=neg,
                bonus_chf=bonus
            )
            db.add(history_entry)

            # 2. Live-Scores des Mitarbeiters für den neuen Monat zurücksetzen
            emp.positive_score = 0
            emp.negative_score = 0
        
        db.commit()
        print(f"[Reset] Monatlicher Reset erfolgreich abgeschlossen.")

# -----------------------------------------------------------------------------
# LIFESPAN-MANAGER
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    models.Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        cleanup_old_tickets(db)
        check_and_run_monthly_reset(db)
    finally:
        db.close()
    yield



app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

SECRET_KEY = "dein_super_geheimer_schluessel_fuer_jwt"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try: return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except: return False

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user_id(request: Request):
    token = request.cookies.get("access_token")
    if not token: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        if token.startswith("Bearer "): token = token[7:]
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload.get("sub"))
    except: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# -----------------------------------------------------------------------------
# ROUTEN (KUNDE & LOGIN)
# -----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def read_root(request: Request, db: Session = Depends(get_db), rated: str = None, error: str = None, ticket_id: str = None, employee_name: str = None):
    current_user = None
    try:
        logged_id = get_current_user_id(request)
        current_user = db.query(models.Employee).filter_by(id=logged_id).first()
    except: pass
    return templates.TemplateResponse(request=request, name="index.html", context={"current_user": current_user, "employees": db.query(models.Employee).all(), "rated": rated, "error": error, "prefilled_ticket_id": ticket_id, "prefilled_employee_name": employee_name})

@app.post("/submit_rating")
def submit_rating(name: str = Form(...), score: int = Form(...), ticket_id: str = Form(...), db: Session = Depends(get_db)):
    ticket = db.query(models.JobTicket).filter_by(ticket_id=ticket_id.strip()).first()
    if not ticket: return RedirectResponse(url="/?error=Job-Ticket+nicht+gefunden.", status_code=status.HTTP_303_SEE_OTHER)
    if ticket.is_closed: return RedirectResponse(url="/?error=Feedback+bereits+abgegeben.", status_code=status.HTTP_303_SEE_OTHER)
    
    employee = db.query(models.Employee).filter_by(name=name).first()
    if not employee or ticket.employee_id != employee.id: return RedirectResponse(url=f"/?error=Falscher+Mitarbeiter.&ticket_id={ticket_id}&employee_name={name}", status_code=status.HTTP_303_SEE_OTHER)

    if score == 1: employee.positive_score = (employee.positive_score or 0) + 1
    elif score == 0: employee.negative_score = (employee.negative_score or 0) + 1

    ticket.is_closed = True
    db.commit()
    return RedirectResponse(url=f"/?rated={name}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = None, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request=request, name="login.html", context={"error": error, "current_user": None})

@app.post("/login")
def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    employee = db.query(models.Employee).filter_by(username=username).first()
    if not employee or not verify_password(password, employee.password_hash): return RedirectResponse(url="/login?error=Ungueltige+Anmeldaten", status_code=status.HTTP_303_SEE_OTHER)
    response = RedirectResponse(url=f"/dashboard/{employee.id}", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key="access_token", value=f"Bearer {create_access_token(data={'sub': str(employee.id)})}", httponly=True)
    return response

@app.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response

# -----------------------------------------------------------------------------
# ROUTE: DASHBOARD MIT DIAGRAMM & HISTORIE
# -----------------------------------------------------------------------------
@app.get("/dashboard/{user_id}", response_class=HTMLResponse)
def dashboard(user_id: int, request: Request, db: Session = Depends(get_db)):
    try: logged_in_id = get_current_user_id(request)
    except: return RedirectResponse(url="/login?error=Bitte+einloggen", status_code=status.HTTP_303_SEE_OTHER)

    current_user = db.query(models.Employee).filter_by(id=logged_in_id).first()
    if logged_in_id != user_id and current_user.role != "admin": raise HTTPException(status_code=403, detail="Keine Berechtigung")

    target_user = db.query(models.Employee).filter_by(id=user_id).first()
    
    # Bei jedem Dashboard-Aufruf vorsichtshalber prüfen, ob ein Reset fällig ist
    check_and_run_monthly_reset(db)

    pos = target_user.positive_score or 0
    neg = target_user.negative_score or 0
    total = pos + neg
    pos_percentage = int((pos / total) * 100) if total > 0 else 50

    netto = pos - neg
    current_bonus = min(netto * 5, 100) if netto > 0 else 0

    # Historische Daten laden
    history_entries = db.query(models.MonthlyHistory).filter_by(employee_id=target_user.id).all()

    # Datenstrukturen für das JavaScript Chart vorbereiten
    chart_labels = []
    chart_pos = []
    chart_neg = []
    chart_bonus = []

    for h in history_entries:
        chart_labels.append(h.year_month)
        chart_pos.append(h.positive_score)
        chart_neg.append(h.negative_score)
        chart_bonus.append(h.bonus_chf)

    open_tickets = db.query(models.JobTicket).filter_by(employee_id=target_user.id, is_closed=False).all()
    
    return templates.TemplateResponse(
        request=request, name="dashboard.html",
        context={
            "current_user": current_user, "target_user": target_user,
            "pos_percentage": pos_percentage, "open_tickets": open_tickets,
            "current_bonus": current_bonus, "reset_day": RESET_DAY_OF_MONTH,
            "history": history_entries,
            "chart_labels": chart_labels, "chart_pos": chart_pos, "chart_neg": chart_neg, "chart_bonus": chart_bonus
        }
    )

@app.post("/create_ticket")
def create_ticket(request: Request, db: Session = Depends(get_db)):
    try: logged_in_id = get_current_user_id(request)
    except: return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    cleanup_old_tickets(db)
    new_ticket = models.JobTicket(ticket_id=f"JOB-{uuid.uuid4().hex[:6].upper()}", employee_id=logged_in_id, is_closed=False)
    db.add(new_ticket)
    db.commit()
    return RedirectResponse(url=f"/dashboard/{logged_in_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/download_qr/{ticket_id}")
def download_single_qr(ticket_id: str, request: Request, db: Session = Depends(get_db)):
    try: get_current_user_id(request)
    except: raise HTTPException(status_code=401)
    ticket = db.query(models.JobTicket).filter_by(ticket_id=ticket_id).first()
    if not ticket or ticket.is_closed: raise HTTPException(status_code=404)
    
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(f"{str(request.base_url)}?ticket_id={ticket.ticket_id}&employee_name={ticket.employee.name}")
    qr.make(fit=True)
    buffer = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="image/png", headers={"Content-Disposition": f"attachment; filename={ticket_id}.png"})

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, db: Session = Depends(get_db), success: str = None, error: str = None):
    try: 
        u_id = get_current_user_id(request)
    except: 
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        
    current_user = db.query(models.Employee).filter_by(id=u_id).first()
    if not current_user or current_user.role != "admin": 
        raise HTTPException(status_code=403)
        
    all_employees = db.query(models.Employee).all()
    
    employees_with_bonus = []
    for emp in all_employees:
        # Hole den neuesten (aktuellsten) Eintrag aus der MonthlyHistory für diesen Mitarbeiter
        latest_history = db.query(models.MonthlyHistory)\
                           .filter_by(employee_id=emp.id)\
                           .order_by(models.MonthlyHistory.year_month.desc())\
                           .first()
        
        # Wenn ein Eintrag existiert, nimm den Betrag, andernfalls 0.0
        emp.last_month_bonus = latest_history.bonus_chf if latest_history else 0.0
        employees_with_bonus.append(emp)

    return templates.TemplateResponse(
        request=request, 
        name="admin.html", 
        context={
            "current_user": current_user, 
            "employees": employees_with_bonus, 
            "success": success, 
            "error": error
        }
    )

@app.post("/create_user")
def create_user(name: str = Form(...), username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    if db.query(models.Employee).filter_by(name=name).first() or db.query(models.Employee).filter_by(username=username).first():
        return RedirectResponse(url="/admin?error=Existiert+bereits", status_code=status.HTTP_303_SEE_OTHER)
    db.add(models.Employee(name=name, username=username, password_hash=hash_password(password), positive_score=0, negative_score=0, role="employee"))
    db.commit()
    return RedirectResponse(url="/admin?success=Erstellt", status_code=status.HTTP_303_SEE_OTHER)

# -----------------------------------------------------------------------------
# NEU: PASSWORT ÄNDERN & ADMIN FUNKTIONEN (LÖSCHEN / RESET)
# -----------------------------------------------------------------------------

@app.post("/change_password")
def change_password(
    old_password: str = Form(...), 
    new_password: str = Form(...), 
    db: Session = Depends(get_db), 
    request: Request = None
):
    try:
        logged_in_id = get_current_user_id(request)
    except:
        return RedirectResponse(url="/login?error=Bitte+einloggen", status_code=status.HTTP_303_SEE_OTHER)

    user = db.query(models.Employee).filter_by(id=logged_in_id).first()
    if not user or not verify_password(old_password, user.password_hash):
        return RedirectResponse(url=f"/dashboard/{logged_in_id}?error=Altes+Passwort+ist+falsch.", status_code=status.HTTP_303_SEE_OTHER)

    user.password_hash = hash_password(new_password)
    db.commit()
    return RedirectResponse(url=f"/dashboard/{logged_in_id}?success=Passwort+erfolgreich+geändert.", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/reset_password/{user_id}")
def admin_reset_password(
    user_id: int, 
    new_password: str = Form(...), 
    db: Session = Depends(get_db), 
    request: Request = None
):
    try:
        u_id = get_current_user_id(request)
    except:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        
    current_user = db.query(models.Employee).filter_by(id=u_id).first()
    if not current_user or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    target_user = db.query(models.Employee).filter_by(id=user_id).first()
    if not target_user:
        return RedirectResponse(url="/admin?error=Mitarbeiter+nicht+gefunden.", status_code=status.HTTP_303_SEE_OTHER)

    target_user.password_hash = hash_password(new_password)
    db.commit()
    return RedirectResponse(url=f"/admin?success=Passwort+für+{target_user.name}+zurückgesetzt.", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/delete_user/{user_id}")
def admin_delete_user(
    user_id: int, 
    db: Session = Depends(get_db), 
    request: Request = None
):
    try:
        u_id = get_current_user_id(request)
    except:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        
    current_user = db.query(models.Employee).filter_by(id=u_id).first()
    if not current_user or current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    # Verhindern, dass der Admin sich selbst löscht
    if u_id == user_id:
        return RedirectResponse(url="/admin?error=Sie+können+sich+nicht+selbst+löschen.", status_code=status.HTTP_303_SEE_OTHER)

    target_user = db.query(models.Employee).filter_by(id=user_id).first()
    if not target_user:
        return RedirectResponse(url="/admin?error=Mitarbeiter+nicht+gefunden.", status_code=status.HTTP_303_SEE_OTHER)

    # Kaskadierendes Löschen von verknüpften Daten (Tickets & Historie), um Foreign-Key-Fehler zu vermeiden
    db.query(models.JobTicket).filter_by(employee_id=user_id).delete()
    db.query(models.MonthlyHistory).filter_by(employee_id=user_id).delete()
    
    db.delete(target_user)
    db.commit()
    return RedirectResponse(url="/admin?success=Mitarbeiter+erfolgreich+gelöscht.", status_code=status.HTTP_303_SEE_OTHER)