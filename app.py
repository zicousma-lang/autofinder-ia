"""AutoFinder IA — Interface locale Streamlit."""
from __future__ import annotations
import json
import pandas as pd
import streamlit as st
from engine import Criteria, extract_fallback, extract_with_ai, search_links, retrieve_apify, rank_ads

st.set_page_config(page_title="AutoFinder IA — Leboncoin", page_icon="🚗", layout="wide")
st.title("🚗 AutoFinder IA")
st.caption("Décris ta voiture idéale en français. L'outil traduit les critères, lance des recherches et compare les annonces.")

if "criteria" not in st.session_state:
    st.session_state.criteria = Criteria()
if "ads" not in st.session_state:
    st.session_state.ads = []
if "source" not in st.session_state:
    st.session_state.source = ""

with st.sidebar:
    st.header("🔐 Connexions (facultatives)")
    openai_token = st.text_input("Clé API OpenAI", type="password", help="Active l'interprétation par un vrai modèle d'IA. Sans clé, des règles locales sont utilisées.")
    apify_token = st.text_input("Jeton API Apify", type="password", help="Pour récupérer automatiquement des annonces. Service tiers potentiellement payant.")
    st.caption("Les clés restent dans la session du navigateur, ne sont pas écrites dans les fichiers du projet et sont envoyées uniquement aux services concernés.")
    st.divider()
    st.info("Le score classe l'adéquation aux critères. Ce n'est ni un diagnostic mécanique, ni une garantie de fiabilité.")

example = ("Je cherche une voiture familiale pour 4 personnes avec un moteur robuste, un grand coffre "
           "et un entretien pas cher. Budget maximum 12 000 €, moins de 150 000 km, à partir de 2015, autour de Paris.")
query = st.text_area("Décris ta recherche", value=example, height=120)
if st.button("🧠 Comprendre mes critères", type="primary"):
    if not query.strip():
        st.warning("Décris d'abord le véhicule recherché.")
    else:
        try:
            c = extract_with_ai(query, openai_token) if openai_token else extract_fallback(query)
            st.session_state.criteria = c
            st.success("Critères analysés par IA." if openai_token else "Critères analysés localement (sans modèle d'IA).")
        except Exception as err:
            st.session_state.criteria = extract_fallback(query)
            st.warning(f"Analyse IA indisponible ({type(err).__name__}). Règles locales utilisées à la place.")

st.subheader("1. Critères détectés — modifiables")
c = st.session_state.criteria
with st.form("filters"):
    cols = st.columns(4)
    def number(col, label, value, maximum, step):
        with col:
            v = st.number_input(label, min_value=0, max_value=maximum, value=int(value or 0), step=step)
            return int(v) or None
    budget = number(cols[0], "Budget max (€)", c.budget_max, 500000, 500)
    km = number(cols[1], "Kilométrage max", c.km_max, 800000, 5000)
    year = number(cols[2], "Année minimum", c.year_min, 2030, 1)
    passengers = number(cols[3], "Nombre de personnes", c.passengers, 9, 1)
    cols2 = st.columns(4)
    brand = cols2[0].text_input("Marque", value=c.brand)
    model = cols2[1].text_input("Modèle", value=c.model)
    fuel = cols2[2].selectbox("Carburant", ["", "Essence", "Diesel", "Hybride", "Électrique"], index=["", "Essence", "Diesel", "Hybride", "Électrique"].index(c.fuel) if c.fuel in ["", "Essence", "Diesel", "Hybride", "Électrique"] else 0)
    gearbox = cols2[3].selectbox("Boîte", ["", "Manuelle", "Automatique"], index=["", "Manuelle", "Automatique"].index(c.gearbox) if c.gearbox in ["", "Manuelle", "Automatique"] else 0)
    c3, c4 = st.columns(2)
    city = c3.text_input("Ville (facultatif)", value=c.city)
    radius = c4.slider("Rayon (km)", 0, 200, c.radius_km, 10)
    flags = st.columns(3)
    family = flags[0].checkbox("Familiale", value=c.family)
    reliability = flags[1].checkbox("Fiabilité du moteur prioritaire", value=c.reliability)
    maintenance = flags[2].checkbox("Entretien économique", value=c.low_maintenance)
    trunk = flags[0].checkbox("Grand coffre", value=c.trunk)
    isofix = flags[1].checkbox("Fixations ISOFIX", value=c.isofix)
    highway = flags[2].checkbox("Confort longs trajets", value=c.highway)
    saved = st.form_submit_button("✅ Enregistrer les critères")
    if saved:
        st.session_state.criteria = Criteria(budget_max=budget, km_max=km, year_min=year, brand=brand, model=model, fuel=fuel,
            gearbox=gearbox, city=city, radius_km=radius, passengers=passengers, family=family, reliability=reliability,
            low_maintenance=maintenance, trunk=trunk, isofix=isofix, highway=highway)
        st.success("Critères mis à jour.")

c = st.session_state.criteria
st.subheader("2. Rechercher sur Leboncoin")
st.write("Ces liens ouvrent des recherches sur Leboncoin. Vérifie les filtres et la localisation directement sur le site.")
for label, url in search_links(c):
    st.link_button("🔎 " + label, url)

st.markdown("**Récupération automatique (optionnelle)**")
max_ads = st.slider("Nombre maximum d'annonces à demander", 10, 100, 30, 10)
st.caption("La récupération passe par un prestataire tiers Apify, soumis à ses propres tarifs et conditions. "
           "Aucune annonce n'est récupérée automatiquement sans action de ta part.")
if st.button("📥 Récupérer et classer les annonces", disabled=not bool(apify_token)):
    try:
        with st.spinner("Récupération depuis le prestataire…"):
            data = retrieve_apify(c, apify_token, max_ads)
        st.session_state.ads = data
        st.session_state.source = f"Apify ({len(data)} annonces reçues)"
        st.success(f"{len(data)} annonces reçues. Le classement apparaît ci-dessous.")
    except Exception as err:
        st.error(f"Connexion non aboutie : {err}. Tu peux continuer avec les liens de recherche ou un fichier CSV/JSON.")

st.subheader("3. Comparer les annonces")
upload = st.file_uploader("Ou importe les annonces exportées en CSV / JSON", type=["csv", "json"])
if upload is not None and st.button("Analyser le fichier importé"):
    try:
        if upload.name.lower().endswith(".json"):
            data = json.loads(upload.getvalue().decode("utf-8-sig"))
            if isinstance(data, dict): data = data.get("items") or data.get("ads") or []
        else:
            data = pd.read_csv(upload, sep=None, engine="python").fillna("").to_dict("records")
        if not isinstance(data, list): raise ValueError("Le fichier doit contenir une liste de véhicules.")
        st.session_state.ads = data[:500]
        st.session_state.source = f"Fichier importé ({len(data[:500])} lignes)"
        st.success("Annonces chargées.")
    except Exception as err:
        st.error(f"Fichier non reconnu : {err}")

if st.session_state.ads:
    ranked = rank_ads(st.session_state.ads, c)
    st.caption(f"Source : {st.session_state.source} · {len(ranked)} annonce(s) correspondant aux contraintes vérifiables.")
    if not ranked:
        st.warning("Aucune annonce compatible dans ces données. Élargis les filtres ou vérifie les colonnes importées.")
    else:
        flat = []
        for car in ranked:
            flat.append({"Score /100": car["score"], "Annonce": car["title"], "Prix (€)": car["price"],
                        "Kilométrage": car["km"], "Année": car["year"], "Motorisation": car["engine"],
                        "Lien": car["url"], "Points positifs": "; ".join(car["reasons"]),
                        "À vérifier": "; ".join(car["caveats"])})
        frame = pd.DataFrame(flat)
        st.dataframe(frame, hide_index=True, use_container_width=True)
        st.download_button("⬇️ Télécharger le classement (CSV)", frame.to_csv(index=False).encode("utf-8-sig"),
                           file_name="autofinder_classement.csv", mime="text/csv")
        st.markdown("**Les meilleures annonces**")
        for i, car in enumerate(ranked[:8], 1):
            with st.expander(f"{i}. {car['title']} — {car['score']}/100", expanded=i <= 2):
                price = f"{car['price']:,} €".replace(",", " ") if car['price'] is not None else "Inconnu"
                km_txt = f"{car['km']:,} km".replace(",", " ") if car['km'] is not None else "Inconnu"
                st.write(f"**Prix :** {price} · **Kilométrage :** {km_txt} · **Année :** {car['year'] or 'Inconnue'}")
                st.write("**Points positifs :** " + (" · ".join(car["reasons"]) or "Pas assez d'informations pour conclure."))
                st.write("**Vérifications :** " + (" · ".join(car["caveats"]) or "Historique et essai toujours indispensables."))
                if car["url"]: st.link_button("Voir l'annonce sur Leboncoin", car["url"])
                if car["description"]: st.caption(car["description"][:1500])
else:
    st.info("Utilise la connexion Apify ou importe un fichier d'annonces pour obtenir un classement réel.")

st.divider()
st.caption("Important : vérifie toujours la motorisation exacte (code moteur, version, année), les factures, le contrôle technique, "
           "l'historique et le véhicule lors d'un essai. Le classement ne prétend pas prédire les pannes.")
