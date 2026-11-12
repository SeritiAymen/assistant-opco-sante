# OPCO Santé Assistant

Assistant capable de répondre à des questions sur les règles de prise en charge
d’OPCO Santé, avec des citations vérifiables.

## État actuel

- Extraction des PDF page par page : texte et tableaux séparés.
- Suppression du texte caché dans l’en-tête des tableaux.

## Installation

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Télécharger les PDF listés dans `sources.md` dans `data/raw/`.

## Utilisation

```powershell
py src/main.py
```

## Limites connues

- Cellules fusionnées : les cellules couvertes contiennent `None`.
- Les notes signalées par `*` sont séparées des tableaux.
- Le schéma des contributions de la page 7 (SSSMS) est extrait dans le désordre.