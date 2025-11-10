import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders


def envoyer_email(
    expediteur_email,
    expediteur_password,
    destinataire_email,
    sujet,
    corps_message,
    piece_jointe=None,
    serveur_smtp="smtp.gmail.com",
    port_smtp=587
):
    """
    Envoie un email via SMTP
    
    Args:
        expediteur_email: Adresse email de l'expéditeur
        expediteur_password: Mot de passe ou mot de passe d'application
        destinataire_email: Adresse email du destinataire
        sujet: Sujet de l'email
        corps_message: Contenu du message
        piece_jointe: Chemin vers un fichier à attacher (optionnel)
        serveur_smtp: Serveur SMTP (défaut: Gmail)
        port_smtp: Port SMTP (défaut: 587)
    """
    
    # Créer le message
    message = MIMEMultipart()
    message['From'] = expediteur_email
    message['To'] = destinataire_email
    message['Subject'] = sujet
    
    # Ajouter le corps du message
    message.attach(MIMEText(corps_message, 'plain'))
    
    # Ajouter une pièce jointe si spécifiée
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
        # Connexion au serveur SMTP
        serveur = smtplib.SMTP(serveur_smtp, port_smtp)
        serveur.starttls()  # Activer la sécurité
        
        # Connexion au compte
        serveur.login(expediteur_email, expediteur_password)
        
        # Envoyer l'email
        texte = message.as_string()
        serveur.sendmail(expediteur_email, destinataire_email, texte)
        
        print(f"✓ Email envoyé avec succès à {destinataire_email}")
        return True
        
    except Exception as e:
        print(f"✗ Erreur lors de l'envoi de l'email: {e}")
        return False
    finally:
        if serveur is not None:
            try:
                serveur.quit()
            except Exception:
                pass
