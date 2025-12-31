from flask import Flask, render_template, request, jsonify, send_file
import json
import os
import threading
import time
import webbrowser

from app.config.settings import BASE_DIR, CACHE_FILE, CONDITIONS_FILE, TEMPLATES_DIR
from app.core.data_to_mail import (
    loadEnvFile,
    executeAnalysis,
    markRun,
    buildEntriesFromExcel,
    loadFailureCounters,
)

env_file_path = BASE_DIR / ".env"
if env_file_path.exists():
    loadEnvFile(str(env_file_path))

app = Flask(__name__, template_folder=str(TEMPLATES_DIR))

@app.route("/", methods=["GET"]) 
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"]) 
def submit():
    entries_payload = request.form.get("entries_payload", "[]")
    summary, stores_results, issues, smtp_context = executeAnalysis(entries_payload)

    try:
        if CACHE_FILE.exists():
            with CACHE_FILE.open("r", encoding="utf-8") as f:
                cache = json.load(f) or {}
        else:
            cache = {}
    except Exception:
        cache = {}

    cache["last_input"] = entries_payload
    cache["state"] = bool(summary.get("emails_sent", 0))

    try:
        markRun(cache)
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
def downloadExcelTemplate():
    excel_path = CONDITIONS_FILE
    if excel_path.exists():
        return send_file(str(excel_path), as_attachment=True, download_name="Conditions.xlsx")
    return jsonify({"error": "Fichier Excel non trouvé"}), 404

@app.route("/export-excel", methods=["GET", "POST"])
def exportExcel():
    if request.method == "POST":
        excel_file = request.files.get("excel_file")
        if not excel_file or excel_file.filename == "":
            return render_template("export_excel.html", message="Veuillez sélectionner un fichier Excel.")

        try:
            entries = buildEntriesFromExcel(excel_file)
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
        summary, stores_results, issues, smtp_context = executeAnalysis(entries_payload)

        try:
            if CACHE_FILE.exists():
                with CACHE_FILE.open("r", encoding="utf-8") as f:
                    cache = json.load(f) or {}
            else:
                cache = {}
        except Exception:
            cache = {}

        cache["last_input"] = entries_payload
        cache["state"] = bool(summary.get("emails_sent", 0))

        try:
            markRun(cache)
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

@app.route("/api/failure-counters", methods=["GET"])
def apiFailureCounters():
    try:
        counters = loadFailureCounters()
        return jsonify({"success": True, "counters": counters})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    def openBrowser():
        time.sleep(1)
        webbrowser.open_new("http://127.0.0.1:5000")

    # N'ouvrir le navigateur que dans le processus principal (pas dans le reloader)
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        threading.Thread(target=openBrowser, daemon=True).start()

    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=True)

