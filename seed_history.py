import sqlite3

def sort_and_rebuild_history():
    # 1. Verbindung zur SQLite-Datenbank herstellen
    conn = sqlite3.connect("bewertungen.db")
    cursor = conn.cursor()

    print("Lese alle bestehenden Einträge sortiert nach Mitarbeiter und Datum aus...")
    
    # Alle Spalten auslesen, sortiert nach employee_id und dem Datum (year_month) aufsteigend
    cursor.execute("""
        SELECT employee_id, year_month, positive_score, negative_score, bonus_chf 
        FROM monthly_history 
        ORDER BY employee_id ASC, year_month ASC
    """)
    all_entries = cursor.fetchall()

    if not all_entries:
        print("Keine Einträge in der Tabelle 'monthly_history' gefunden.")
        conn.close()
        return

    print(f"Es wurden {len(all_entries)} Einträge geladen. Leere die Tabelle für die Neuordnung...")
    
    # 2. Die Tabelle komplett leeren
    cursor.execute("DELETE FROM monthly_history")
    
    # Sicherer Reset des Autoincrement-Zählers (fängt den Fehler ab, falls sqlite_sequence nicht existiert)
    try:
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='monthly_history'")
        print(" -> Interne ID-Sequenz wurde zurückgesetzt.")
    except sqlite3.OperationalError:
        # Falls die Tabelle 'sqlite_sequence' nicht existiert, überspringen wir das einfach unbemerkt
        print(" -> Interne ID-Sequenz existiert noch nicht (wird von SQLite automatisch geregelt).")

    print("Schreibe Einträge in chronologisch korrekter Reihenfolge neu...")

    # 3. Die sortierten Daten wieder sequentiell einfügen
    for emp_id, ym, pos, neg, bonus in all_entries:
        cursor.execute(
            """
            INSERT INTO monthly_history (employee_id, year_month, positive_score, negative_score, bonus_chf)
            VALUES (?, ?, ?, ?, ?)
            """,
            (emp_id, ym, pos, neg, bonus)
        )
        print(f" -> Wiederhergestellt: Mitarbeiter-ID {emp_id} | Monat: {ym} | Bonus: {bonus} CHF")

    # Änderungen permanent in der DB speichern und Verbindung trennen
    conn.commit()
    conn.close()
    print("\nErfolgreich erledigt! Alle Einträge in 'monthly_history' sind jetzt permanent nach Datum sortiert.")

if __name__ == "__main__":
    sort_and_rebuild_history()