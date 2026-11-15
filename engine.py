"""Moteur de recherche de voitures : interprétation, liens et classement prudent."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, asdict
from datetime import date
from typing import Any
from urllib.parse import urlencode, urlparse


@dataclass
class Criteria:
    budget_max: int | None = None
    km_max: int | None = None
    year_min: int | None = None
    brand: str = ""
    model: str = ""
    fuel: str = ""
    gearbox: str = ""
    city: str = ""
    radius_km: int = 50
    passengers: int | None = None
    family: bool = False
    reliability: bool = False
    low_maintenance: bool = False
    trunk: bool = False
    isofix: bool = False
    highway: bool = False


def norm(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def amount(s: str) -> int | None:
    s = str(s or "").replace("\u202f", " ").replace("\xa0", " ").lower().strip()
    m = re.search(r"(\d[\d .]*)(k\b)?", s)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    if not digits:
        return None
    return int(digits) * (1000 if m.group(2) else 1)


def extract_fallback(query: str) -> Criteria:
    raw = norm(query)
    c = Criteria()
    c.family = bool(re.search(r"famil|enfant|poussette|4 personnes|quatre personnes|monospace|break", raw))
    c.reliability = bool(re.search(r"fiab|robust|solide|durable|sans panne", raw))
    c.low_maintenance = bool(re.search(r"entretien (pas cher|economique|peu couteux)|faible cout|economique a entretenir", raw))
    c.trunk = bool(re.search(r"coffre|poussette|bagages", raw))
    c.isofix = "isofix" in raw or "siege auto" in raw
    c.highway = bool(re.search(r"autoroute|longs? trajets?|voyages?", raw))
    m = re.search(r"(\d+)\s*(?:personnes?|places?)", raw)
    if m:
        c.passengers = int(m.group(1))
        c.family |= c.passengers >= 3
    if c.family and c.passengers is None:
        c.passengers = 4  # hypothèse pratique, modifiable dans l'interface

    # Accepte "budget 12 000", "max 12k €", "moins de 12000 euros".
    price_patterns = [
        r"(?:budget|prix|maximum|max|moins de|jusqu.a|pas plus de)\D{0,24}(\d[\d\s.]*(?:k)?)\s*(?:€|euros?)",
        r"(\d[\d\s.]*(?:k)?)\s*(?:€|euros?)",
        r"(?:budget|prix)\s*(?:de|:)?\s*(\d[\d\s.]*(?:k)?)",
    ]
    for pat in price_patterns:
        m = re.search(pat, raw)
        if m:
            v = amount(m.group(1))
            if v is not None and 500 <= v <= 500000:
                c.budget_max = v
                break
    # Nombres de km, avec espaces ou séparateurs de milliers.
    for pat in [r"(?:moins de|max(?:imum)?|jusqu.a|sous)\s*(\d[\d\s.]*(?:k)?)\s*(?:km|kilometres?)", r"(\d[\d\s.]*(?:k)?)\s*(?:km|kilometres?)"]:
        m = re.search(pat, raw)
        if m:
            v = amount(m.group(1))
            if v is not None and v >= 1000:
                c.km_max = v
                break
    for pat in [r"(?:a partir de|depuis|apres|minimum|min|annee)\D{0,9}(20\d{2}|19\d{2})", r"\b(20\d{2})\b"]:
        m = re.search(pat, raw)
        if m:
            y = int(m.group(1))
            if 1990 <= y <= 2030:
                c.year_min = y
                break
    for fuel in ["diesel", "essence", "hybride", "electrique"]:
        if fuel in raw:
            c.fuel = {"electrique": "Électrique"}.get(fuel, fuel.capitalize())
            break
    if "automatique" in raw or "boite auto" in raw:
        c.gearbox = "Automatique"
    elif "manuelle" in raw:
        c.gearbox = "Manuelle"
    for brand in ["renault", "peugeot", "citroen", "dacia", "toyota", "honda", "skoda", "volkswagen", "bmw", "audi", "mercedes", "ford", "kia", "hyundai", "mazda", "volvo", "seat", "opel", "nissan"]:
        if re.search(r"\b" + brand + r"\b", raw):
            c.brand = brand.title()
            break
    # Le dictionnaire est un secours, pas une base automobile exhaustive.
    for model in ["Corolla", "Octavia", "Scenic", "Megane", "Clio", "Captur", "Touran", "Golf", "Passat", "308", "3008", "5008", "C4", "C5", "Duster", "Jogger", "Ceed", "Focus", "Mondeo", "Serie 3"]:
        if norm(model) in raw:
            c.model = model
            break
    for city in ["Paris", "Lyon", "Marseille", "Toulouse", "Bordeaux", "Lille", "Nantes", "Rennes", "Nanterre", "Strasbourg", "Nice", "Montpellier", "Rouen", "Dijon", "Grenoble", "Tours", "Orléans"]:
        if norm(city) in raw:
            c.city = city
            break
    m = re.search(r"(?:rayon de|dans un rayon de|autour de)\s*(\d{1,3})\s*km", raw)
    if m:
        c.radius_km = min(max(int(m.group(1)), 0), 200)
    return c


def extract_with_ai(query: str, api_key: str, model: str = "gpt-4.1-mini") -> Criteria:
    """La clé ne sort pas de l'appel au fournisseur ; aucun stockage persistant."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    fields = list(asdict(Criteria()).keys())
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": (
                "Tu extrais les critères pour acheter une voiture d'occasion en France. "
                "Retourne UNIQUEMENT un objet JSON contenant ces clés: " + ", ".join(fields) + ". "
                "N'invente jamais de budget, marque, ville, année, kilométrage ou énergie non cités. "
                "Pour les contraintes non précisées, utilise null pour les entiers, '' pour les chaînes, false pour les booléens. "
                "'famille pour 4' signifie passengers=4, family=true. "
                "'moteur robuste' => reliability=true, mais n'invente aucun classement moteur. "
                "Si radius_km n'est pas mentionné, mets 50. Valeurs numériques en entiers."
            )},
            {"role": "user", "content": query[:6000]},
        ],
    )
    obj = json.loads(response.choices[0].message.content or "{}")
    allowed = set(fields)
    obj = {k: v for k, v in obj.items() if k in allowed}
    for k in ("budget_max", "km_max", "year_min", "radius_km", "passengers"):
        try:
            obj[k] = int(obj[k]) if obj.get(k) not in (None, "") else None
        except (ValueError, TypeError):
            obj[k] = None
    for k in ("family", "reliability", "low_maintenance", "trunk", "isofix", "highway"):
        obj[k] = obj.get(k) is True
    for k in ("brand", "model", "fuel", "gearbox", "city"):
        obj[k] = str(obj.get(k) or "")[:120]
    if obj.get("radius_km") is None:
        obj["radius_km"] = 50
    obj["radius_km"] = max(0, min(200, obj["radius_km"]))
    return Criteria(**obj)


def search_links(c: Criteria) -> list[tuple[str, str]]:
    # Les libellés sémantiques donnent plusieurs recherches sans imposer un modèle arbitraire.
    candidates = [("Recherche générale", "")]
    if c.family and not c.model:
        candidates = [("Break familial", "break"), ("Monospace familial", "monospace"), ("SUV familial", "SUV")]
    links = []
    for label, style in candidates:
        keywords = " ".join(x for x in [c.brand, c.model, style] if x)
        params = {"category": "2"}
        if keywords:
            params["text"] = keywords
        if c.budget_max:
            params["price"] = f"0-{c.budget_max}"
        if c.year_min:
            params["regdate"] = f"{c.year_min}-{max(c.year_min, date.today().year)}"
        if c.km_max:
            params["mileage"] = f"0-{c.km_max}"
        links.append((label, "https://www.leboncoin.fr/recherche?" + urlencode(params)))
    return links


def apify_input(c: Criteria, max_ads: int = 30) -> dict[str, Any]:
    p: dict[str, Any] = {"adLimit": max(10, min(100, max_ads)), "includeSeller": False, "includePhone": False,
                         "mode": "standard", "sortBy": "time", "excludeKeywords": "accidenté, pour pièces"}
    if c.budget_max: p["price_max_filter"] = c.budget_max
    if c.km_max: p["mileageMax"] = c.km_max
    if c.year_min: p["yearMin"] = c.year_min
    if c.city:
        p["location"] = c.city
        p["radius"] = c.radius_km
    if c.brand: p["brands"] = [c.brand]
    if c.model: p["models"] = [c.model]
    if c.fuel: p["fuel"] = [c.fuel]
    if c.gearbox: p["gearbox"] = [c.gearbox]
    # Aucun "break" imposé en filtre : il écarterait d'autres modèles familiaux adaptés.
    return p


def retrieve_apify(c: Criteria, token: str, max_ads: int = 30) -> list[dict[str, Any]]:
    """Acteur externe optionnel, susceptible d'être payant et de changer de schéma."""
    import requests
    endpoint = "https://api.apify.com/v2/actors/clearpath~leboncoin-voitures/run-sync-get-dataset-items"
    r = requests.post(endpoint, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                      params={"format": "json", "clean": "true", "limit": max_ads},
                      json=apify_input(c, max_ads), timeout=240)
    r.raise_for_status()
    items = r.json()
    if not isinstance(items, list):
        raise ValueError("Le fournisseur n'a pas renvoyé une liste d'annonces.")
    return items


def find_value(item: dict[str, Any], *keys: str) -> Any:
    sources = [item]
    for key in ("vehicle", "car", "details", "location"):
        if isinstance(item.get(key), dict):
            sources.append(item[key])
    attr = item.get("attributes")
    if isinstance(attr, list):
        attrdict = {}
        for a in attr:
            if isinstance(a, dict):
                k = a.get("key") or a.get("label")
                if k:
                    attrdict[norm(k)] = a.get("value")
        sources.append(attrdict)
    for source in sources:
        for key in keys:
            if key in source and source[key] not in (None, ""):
                value = source[key]
                if isinstance(value, dict):
                    value = value.get("value") or value.get("label") or value.get("amount")
                if isinstance(value, list):
                    value = ", ".join(str(x) for x in value)
                if value not in (None, ""):
                    return value
            # fallback pour les colonnes CSV en français
            for skey, value in source.items():
                if norm(skey) == norm(key) and value not in (None, ""):
                    return value
    return None


def normalize_ad(a: dict[str, Any]) -> dict[str, Any]:
    title = find_value(a, "subject", "title", "titre", "name") or "Voiture sans titre"
    raw_url = find_value(a, "url", "link", "adUrl", "ad_url", "list_url") or ""
    url = str(raw_url)
    if url.startswith("/ad/"):
        url = "https://www.leboncoin.fr" + url
    if url and (urlparse(url).scheme not in ("https", "http") or not (urlparse(url).hostname == "leboncoin.fr" or str(urlparse(url).hostname).endswith(".leboncoin.fr"))):
        url = ""  # N'afficher que des URLs Leboncoin vérifiables
    description = str(find_value(a, "description", "body", "texte", "content") or "")
    price = amount(str(find_value(a, "price", "prix", "price_eur") or ""))
    km = amount(str(find_value(a, "mileage", "km", "kilometrage", "kilométrage", "mileage_km") or ""))
    y = amount(str(find_value(a, "year", "regdate", "annee", "année", "model_year") or ""))
    if y and (y < 1950 or y > 2030): y = None
    seats = amount(str(find_value(a, "seats", "places", "nombre de places", "u_car_nb_seats") or ""))
    car_model = str(find_value(a, "model", "modele", "modèle") or "")
    engine = str(find_value(a, "engine", "motorisation", "engine_name", "version") or "")
    city = find_value(a, "city", "ville", "location_name", "location") or ""
    if isinstance(city, dict):
        city = city.get("city") or city.get("name") or ""
    return {"title": str(title), "description": description, "url": url, "price": price, "km": km,
            "year": y, "seats": seats, "model": car_model, "engine": engine,
            "city": str(city), "fuel": str(find_value(a, "fuel", "carburant", "energie", "énergie") or ""),
            "gearbox": str(find_value(a, "gearbox", "boite", "boîte") or "")}


def evaluate_ad(a: dict[str, Any], c: Criteria) -> dict[str, Any]:
    car = normalize_ad(a)
    score = 48
    reasons: list[str] = []
    caveats: list[str] = []
    if c.budget_max:
        if car["price"] is None: caveats.append("Prix non indiqué")
        elif car["price"] > c.budget_max: return {**car, "eligible": False, "score": 0, "reasons": [], "caveats": ["Hors budget"]}
        else:
            score += 12
            reasons.append("Dans le budget")
    if c.km_max:
        if car["km"] is None: caveats.append("Kilométrage à vérifier")
        elif car["km"] > c.km_max: return {**car, "eligible": False, "score": 0, "reasons": [], "caveats": ["Kilométrage trop élevé"]}
        else: score += 8; reasons.append("Kilométrage conforme")
    if c.year_min:
        if car["year"] is None: caveats.append("Année à vérifier")
        elif car["year"] < c.year_min: return {**car, "eligible": False, "score": 0, "reasons": [], "caveats": ["Année trop ancienne"]}
        else: score += 6; reasons.append("Année conforme")
    full = norm(" ".join(str(car[x]) for x in ("title", "description", "model", "engine")))
    if c.brand and norm(c.brand) not in full:
        caveats.append("Marque non confirmée dans le texte")
    if c.model and norm(c.model) not in full:
        caveats.append("Modèle exact non confirmé")
    if c.family:
        if car["seats"] is not None:
            if car["seats"] < (c.passengers or 4):
                return {**car, "eligible": False, "score": 0, "reasons": [], "caveats": ["Pas assez de places"]}
            score += 8; reasons.append("Nombre de places suffisant")
        else: caveats.append("Nombre de places à confirmer")
        if re.search(r"\b(break|sw|tourer|estate|monospace|familial|touran|scenic|jogger|octavia combi)\b", full):
            score += 7; reasons.append("Format potentiellement pratique pour une famille")
        if re.search(r"\b(citadine|mini citadine|microcitadine)\b", full):
            score -= 15; caveats.append("Habitabilité et coffre d’une citadine à contrôler pour la famille")
        if c.isofix:
            if "isofix" in full: score += 7; reasons.append("ISOFIX mentionné")
            else: caveats.append("ISOFIX non mentionné")
        if c.trunk:
            if "coffre" in full: score += 3; reasons.append("Coffre décrit")
            else: caveats.append("Volume du coffre non précisé")
    if re.search(r"(factures? d.entretien|carnet d.entretien|entretien suivi|entretien a jour|factures disponibles)", full):
        score += 9; reasons.append("Entretien évoqué (preuves à demander)")
    else:
        caveats.append("Factures et historique d'entretien à demander")
    if re.search(r"(pour pieces|accidente|moteur hs|boite hs|ne roule pas|panne moteur)", full):
        score -= 35; caveats.append("Mention de panne ou de dommage à examiner")
    if c.reliability:
        if car["engine"]: caveats.append("Vérifier les problèmes connus de cette motorisation et de son millésime")
        else: caveats.append("Motorisation exacte non identifiée : fiabilité impossible à certifier")
    if c.low_maintenance:
        caveats.append("Coût réel d'entretien à documenter selon moteur, boîte et historique")
    # Le score reste un indice de correspondance, jamais une certification moteur.
    if c.reliability and not car["engine"]:
        score = min(score, 85)
    return {**car, "eligible": True, "score": min(100, max(0, score)), "reasons": reasons, "caveats": caveats}


def rank_ads(ads: list[dict[str, Any]], c: Criteria) -> list[dict[str, Any]]:
    rows = [evaluate_ad(a, c) for a in ads if isinstance(a, dict)]
    seen = set()
    out = []
    for r in sorted(rows, key=lambda x: (x["eligible"], x["score"]), reverse=True):
        key = r["url"] or (r["title"], r["price"], r["km"])
        if key in seen: continue
        seen.add(key)
        if r["eligible"]: out.append(r)
    return out
