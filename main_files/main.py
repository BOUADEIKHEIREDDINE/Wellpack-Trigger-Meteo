from flask import Flask, render_template, request, jsonify, send_file
import os
import sys
import json
import threading
import time
import webbrowser

# Ajouter le répertoire racine au path pour les imports
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from modules.data_to_mail import (
    CACHE_PATH,
    load_env_file,
    execute_analysis,
    mark_run,
    build_entries_from_excel,
)

# Charger les variables d'environnement depuis .env
env_path = os.path.join(BASE_DIR, ".env")
if os.path.exists(env_path):
    load_env_file(env_path)

# Les templates sont situés dans html_files/
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "html_files"))


@app.route("/", methods=["GET"]) 
def index():
    return render_template("index.html")


@app.route("/submit", methods=["POST"]) 
def submit():
    entries_payload = request.form.get("entries_payload", "[]")
    summary, stores_results, issues, smtp_context = execute_analysis(entries_payload)

    try:
        if os.path.exists(CACHE_PATH):
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                cache = json.load(f) or {}
        else:
            cache = {}
    except Exception:
        cache = {}

    cache["last_input"] = entries_payload
    cache["state"] = bool(summary.get("emails_sent", 0))

    try:
        mark_run(cache)
    except Exception:
        pass

    if summary.get("total", 0) == 0 and issues:
        error_message = issues[0]
        return render_template(
            "index.html",
            error_message=error_message,
            form_data={"entries_payload": entries_payload},
        )

    return render_template(
        "results.html",
        summary=summary,
        stores=stores_results,
        issues=issues,
        smtp=smtp_context,
    )


@app.route("/cron", methods=["POST", "GET"])
def cron():
    return jsonify({"ok": False, "reason": "deprecated_endpoint"}), 404


@app.route("/download-excel-template", methods=["GET"])
def download_excel_template():
    """Télécharge le fichier Excel Conditions.xlsx"""
    excel_path = os.path.join(BASE_DIR, "Conditions.xlsx")
    if os.path.exists(excel_path):
        return send_file(excel_path, as_attachment=True, download_name="Conditions.xlsx")
    return jsonify({"error": "Fichier Excel non trouvé"}), 404


@app.route("/export-excel", methods=["GET", "POST"])
def export_excel():
    """Page d'export/import du fichier Excel rempli"""
    if request.method == "POST":
        excel_file = request.files.get("excel_file")
        if not excel_file or excel_file.filename == "":
            return render_template("export_excel.html", message="Veuillez sélectionner un fichier Excel.")

        try:
            entries = build_entries_from_excel(excel_file)
        except Exception as exc:
            return render_template(
                "export_excel.html",
                message=f"Erreur lors de la lecture du fichier Excel : {exc}",
            )

        if not entries:
            return render_template(
                "export_excel.html",
                message="Aucune filiale valide trouvée dans le fichier Excel.",
            )

        entries_payload = json.dumps(entries, ensure_ascii=False)
        summary, stores_results, issues, smtp_context = execute_analysis(entries_payload)

        # Mettre à jour le cache comme pour le formulaire classique
        try:
            if os.path.exists(CACHE_PATH):
                with open(CACHE_PATH, "r", encoding="utf-8") as f:
                    cache = json.load(f) or {}
            else:
                cache = {}
        except Exception:
            cache = {}

        cache["last_input"] = entries_payload
        cache["state"] = bool(summary.get("emails_sent", 0))

        try:
            mark_run(cache)
        except Exception:
            pass

        if summary.get("total", 0) == 0 and issues:
            error_message = issues[0]
            return render_template(
                "export_excel.html",
                message=error_message,
            )

        return render_template(
            "results.html",
            summary=summary,
            stores=stores_results,
            issues=issues,
            smtp=smtp_context,
        )

    return render_template("export_excel.html")


if __name__ == "__main__":
    # Ouvre automatiquement le navigateur en HTTP simple
    def open_browser():
        time.sleep(1)
        webbrowser.open_new("http://127.0.0.1:5000")

    threading.Thread(target=open_browser, daemon=True).start()

    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=True)

