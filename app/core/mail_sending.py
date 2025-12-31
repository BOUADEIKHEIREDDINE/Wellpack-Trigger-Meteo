import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

def envoyerEmail(
    expediteur_email,
    expediteur_password,
    destinataire_email,
    sujet,
    corps_message,
    piece_jointe=None,
    serveur_smtp="smtp.gmail.com",
    port_smtp=587
):

    message = MIMEMultipart()
    message['From'] = expediteur_email
    message['To'] = destinataire_email
    message['Subject'] = sujet

    message.attach(MIMEText(corps_message, 'plain'))

    if piece_jointe:
        try:
            with open(piece_jointe, 'rb') as fichier:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(fichier.read())
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename= {piece_jointe.split("/")[-1]}'
                )
                message.attach(part)
        except Exception as e:
            print(f"Erreur lors de l'ajout de la pièce jointe: {e}")

    serveur = None
    try:
        serveur = smtplib.SMTP(serveur_smtp, port_smtp)
        serveur.starttls()

        serveur.login(expediteur_email, expediteur_password)

        texte = message.as_string()
        serveur.sendmail(expediteur_email, destinataire_email, texte)

        print(f"[OK] Email envoye avec succes a {destinataire_email}")
        return True

    except Exception as e:
        print(f"[ERROR] Erreur lors de l'envoi de l'email: {e}")
        return False
    finally:
        if serveur is not None:
            try:
                serveur.quit()
            except Exception:
                pass
