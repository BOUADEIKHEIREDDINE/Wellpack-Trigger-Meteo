# Wellpack Predictor - Système d'Alertes Météorologiques

Application web Flask pour analyser les conditions météorologiques et envoyer des alertes par email lorsque les seuils configurés sont atteints pour différentes filiales.

## Fonctionnalités

- **Analyse météorologique** : Vérification automatique des conditions météo (température, précipitations, vent, UV) pour plusieurs filiales
- **Interface web intuitive** : Formulaire interactif pour configurer les seuils et périodes d'analyse
- **Import Excel** : Possibilité d'importer des configurations via fichier Excel (`Conditions.xlsx`)
- **Notifications par email** : Envoi automatique d'un email de synthèse regroupant toutes les filiales conformes
- **Mécanisme de seuil** : Désactivation automatique des notifications après 7 échecs consécutifs pour éviter le spam
- **Exécution planifiée** : Script de backend pour analyses automatiques quotidiennes
- **Mise à jour en temps réel** : Interface mise à jour dynamiquement lors de l'exécution du backend

## Structure du Projet

```
Wellpack_predictor/
├── app/
│   ├── __init__.py
│   ├── main.py                 # Application Flask principale
│   ├── scheduler.py            # Script d'exécution planifiée
│   ├── config/
│   │   └── settings.py         # Configuration des chemins
│   └── core/
│       ├── data_to_mail.py     # Logique métier principale
│       ├── weather_analyser.py # Analyse des données météo
│       └── mail_sending.py     # Envoi d'emails
├── frontend/
│   └── templates/
│       ├── index.html          # Page principale (formulaire)
│       ├── results.html        # Page de résultats
│       └── export_excel.html   # Page d'import Excel
├── data/
│   ├── cache/
│   │   └── cache.json          # Cache des données (état, compteurs d'échecs)
│   └── input/
│       └── Conditions.xlsx     # Template Excel
├── scripts/
│   └── backend_start_weather.cmd  # Script Windows pour lancer le scheduler
├── requirements.txt
└── README.md
```

## Installation

### Prérequis

- Python 3.8 ou supérieur
- pip (gestionnaire de paquets Python)

### Étapes d'installation

1. **Cloner ou télécharger le projet**

2. **Installer les dépendances** :
   ```bash
   pip install -r requirements.txt
   ```

3. **Configuration des variables d'environnement** (développement local) :
   
   Créer un fichier `.env` à la racine du projet avec les variables suivantes :
   ```env
   SMTP_EMAIL=votre_email@gmail.com
   SMTP_PASSWORD=votre_mot_de_passe
   SMTP_SERVER=smtp.gmail.com
   SMTP_PORT=587
   ```
   
   **Note** : Le fichier `.env` est ignoré par Git pour des raisons de sécurité.

4. **Pour la production** (GitHub Actions) :
   
   Utiliser les Repository Secrets de GitHub Actions pour configurer les variables d'environnement SMTP et PostgreSQL.

## Utilisation

### Mode Web (Interface utilisateur)

1. **Lancer l'application Flask** :
   ```bash
   python -m app.main
   ```
   
   L'application démarre sur `http://127.0.0.1:5000` et s'ouvre automatiquement dans votre navigateur.

2. **Configurer les filiales** :
   - Renseigner l'adresse email unique pour toutes les filiales
   - Ajouter une ou plusieurs filiales avec leurs paramètres :
     - Nom de la filiale
     - Code postal
     - Période d'analyse (J-x à J+y)
     - Seuils météorologiques (température, précipitations, vent, UV)
     - Fréquence d'analyse
   - Activer/désactiver les conditions selon vos besoins

3. **Soumettre l'analyse** :
   - Cliquer sur "Analyser les conditions météorologiques"
   - Consulter les résultats sur la page de résultats

### Import Excel

1. **Télécharger le template** :
   - Cliquer sur "Exporter le fichier Excel" sur la page principale
   - Le fichier `Conditions.xlsx` est téléchargé

2. **Remplir le fichier Excel** :
   - **C1** : Nom du magasin
   - **C2** : Email de contact
   - **C4, C5, C6...** : Noms des filiales (une par ligne)
   - **D4, D5, D6...** : Codes postaux
   - **E4, E5, E6...** : J-x (jours avant)
   - **F4, F5, F6...** : J+x (jours après)
   - **G4, G5, G6...** : Précipitations (Pluie faible/moderée/forte/Tout niveau/Vide)
   - **H4, H5, H6...** : Vent (< x ou > x)
   - **I4, I5, I6...** : Température (< x ou > x)
   - **J4, J5, J6...** : Indice UV (< x ou > x)
   - **K4, K5, K6...** : Fréquence d'analyse

3. **Importer le fichier** :
   - Aller sur la page "Exporter le fichier Excel"
   - Glisser-déposer ou sélectionner le fichier rempli
   - Cliquer sur "Importer"
   - Consulter les résultats

### Mode Backend (Exécution planifiée)

Pour exécuter l'analyse automatiquement selon une planification :

**Windows** :
```bash
scripts\backend_start_weather.cmd
```

**Linux/Mac** :
```bash
python -m app.scheduler
```

Le script :
- Lit la dernière configuration depuis `data/cache/cache.json`
- Évalue les conditions météorologiques
- Envoie un email si les conditions sont remplies
- Met à jour les compteurs d'échecs consécutifs

## Configuration

### Mécanisme de seuil

Le système inclut un mécanisme anti-spam :
- Après **7 échecs consécutifs** (conditions non remplies), les notifications pour une filiale sont automatiquement désactivées
- Le compteur se réinitialise automatiquement au premier succès
- L'interface affiche une barre de progression indiquant le nombre d'échecs restants avant désactivation

### Conditions météorologiques

Chaque filiale peut configurer :
- **Température** : Minimum ou maximum (°C)
- **Précipitations** : Niveau de pluie (faible/moderée/forte/tout niveau/pas de pluie)
- **Vent** : Vitesse minimale ou maximale (km/h)
- **Indice UV** : Seuil minimum ou maximum

Les conditions peuvent être activées/désactivées individuellement via des cases à cocher dans l'interface.

### Tolérance

Le système applique une tolérance de **1/3 des jours** dans la fenêtre d'analyse : si moins d'un tiers des jours ne respectent pas les conditions, la filiale est considérée comme conforme.

## Format des Emails

L'application envoie un **email unique de synthèse** regroupant toutes les filiales conformes :

**Objet** : `Synthèse météo – Filiales conformes`

**Contenu** :
- Liste des filiales conformes
- Pour chaque filiale :
  - Période analysée
  - Seuils configurés
  - Prévisions détaillées (date, température, vent, précipitations)

## Dépendances

- **Flask** : Framework web
- **pandas** : Manipulation de données
- **requests** : Requêtes HTTP vers l'API météo (Open-Meteo)
- **openpyxl** : Lecture/écriture de fichiers Excel
- **python-dotenv** : Gestion des variables d'environnement
- **APScheduler** : Planification de tâches (optionnel)
- **gunicorn** : Serveur WSGI pour la production (optionnel)

## API Météorologique

L'application utilise l'API **Open-Meteo** pour récupérer les données météorologiques historiques et prévisionnelles.

## Stockage des Données

- **Cache** : `data/cache/cache.json`
  - `last_input` : Dernière configuration soumise
  - `state` : État de la dernière exécution
  - `failure_counters` : Compteurs d'échecs consécutifs par filiale

## Dépannage

### Erreur "ModuleNotFoundError: No module named 'app'"

Exécuter depuis la racine du projet :
```bash
python -m app.main
```

### Erreur "Variable d'environnement SMTP_EMAIL manquante"

Créer un fichier `.env` à la racine avec les variables SMTP requises (voir section Installation).

### Les emails ne sont pas envoyés

Vérifier :
1. Les variables d'environnement SMTP sont correctement configurées
2. Le serveur SMTP est accessible
3. Les identifiants sont valides
4. Le port SMTP est correct (587 pour Gmail)

## Notes

- Le projet utilise un système de cache JSON (pas de base de données SQL)
- Les traces SQL ont été supprimées comme demandé
- Le fichier `.env` est ignoré par Git pour la sécurité
- En production, utiliser GitHub Actions Secrets pour les variables sensibles

## Licence

Ce projet est un projet académique développé dans le cadre du cours AI_Clinic.

