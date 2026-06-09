from sqlalchemy.orm import Session
from database import SessionLocal
import models
from passlib.context import CryptContext

# Passwort-Hashing wie in deiner main.py
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def make_user_admin():
    db = SessionLocal()
    try:
        # HIER DEINE WUNSCH-DATEN EINTRAGEN
        admin_username = "admin"
        admin_name = "System Administrator"
        admin_password = "DeinSicheresPasswort123" # Ändere das Passwort!

        # Prüfen, ob der Benutzer bereits existiert
        user = db.query(models.Employee).filter_by(username=admin_username).first()

        if user:
            # Falls der User existiert, befördere ihn zum Admin
            user.role = "admin"
            db.commit()
            print(f"Der bestehende Benutzer '{admin_username}' wurde erfolgreich zum Admin ernannt!")
        else:
            # Falls er nicht existiert, erstelle ihn direkt als Admin
            hashed_pw = pwd_context.hash(admin_password)
            new_admin = models.Employee(
                name=admin_name,
                username=admin_username,
                password_hash=hashed_pw,
                role="admin",
                positive_score=0,
                negative_score=0
            )
            db.add(new_admin)
            db.commit()
            print(f"Ein neuer Admin-Account '{admin_username}' wurde erfolgreich erstellt!")

    finally:
        db.close()

if __name__ == "__main__":
    make_user_admin()