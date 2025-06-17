import json
import pandas as pd
import numpy as np
from scipy.spatial import ConvexHull
from scipy.cluster.hierarchy import linkage, fcluster
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from collections import defaultdict
import re
import pathlib

# --- CONSTANTES --- #
# CORRECTION : Le chemin est maintenant relatif au script de la fonction.
# Netlify place les `included_files` au même niveau que la fonction.
FUNC_DIR = pathlib.Path(__file__).parent
REF_PATH = FUNC_DIR / "data_ref.csv"
ECOLOGY_PATH = FUNC_DIR / "data_ecologie_espece.csv"
SYNTAXON_PATH = FUNC_DIR / "data_villaret.csv"

# --- HELPERS DE NORMALISATION (issus de app.py) --- #
def normalize_species_name(species_name):
    if pd.isna(species_name) or str(species_name).strip() == "": return None
    return " ".join(str(species_name).strip().split()[:2]).lower()

def format_ecology_for_hover(text, line_width_chars=65):
    if pd.isna(text) or str(text).strip() == "":
        return "Description écologique non disponible."
    import textwrap
    wrapped_lines = textwrap.wrap(str(text), width=line_width_chars)
    return "<br>".join(wrapped_lines)

# Custom JSON encoder pour gérer les types NumPy
class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        return super(NpEncoder, self).default(obj)

# --- FONCTIONS DE CHARGEMENT DE DONNÉES --- #
def load_reference_data():
    ref = pd.read_csv(REF_PATH, sep=';')
    if 'CC Rhoméo' in ref.columns:
        ref.rename(columns={'CC Rhoméo': 'Perturbation CC'}, inplace=True)
    ref.iloc[:, 1:] = ref.iloc[:, 1:].apply(pd.to_numeric, errors="coerce")
    return ref

def load_ecology_data():
    try:
        eco_data = pd.read_csv(ECOLOGY_PATH, sep=';', header=None, names=['Espece', 'Description_Ecologie'], encoding='utf-8-sig', keep_default_na=False, na_values=[''])
        eco_data.dropna(subset=['Espece'], inplace=True)
        eco_data['Espece_norm'] = eco_data['Espece'].astype(str).str.strip().str.split().str[:2].str.join(" ").str.lower()
        eco_data.drop_duplicates(subset=['Espece_norm'], keep='first', inplace=True)
        return eco_data.set_index('Espece_norm')
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame(columns=['Description_Ecologie']).set_index(pd.Index([], name='Espece_norm'))

def load_syntaxon_data():
    try:
        df = pd.read_csv(SYNTAXON_PATH, sep=';', header=None, encoding='utf-8-sig', keep_default_na=False, na_values=[''])
        processed_syntaxons = []
        for _, row in df.iterrows():
            if len(row) < 2: continue
            species_set = {normalize_species_name(s) for s in row.iloc[2:] if normalize_species_name(s)}
            processed_syntaxons.append({
                'id': str(row.iloc[0]).strip(),
                'name_latin': str(row.iloc[1]).strip(),
                'species_set': species_set
            })
        return processed_syntaxons
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return []

# --- FONCTION D'ANALYSE PRINCIPALE (issue de core.py) --- #
def analyse_pca(df_numeric, n_clusters=3):
    if df_numeric.empty or df_numeric.shape[1] == 0:
        return np.array([]), None, pd.DataFrame()
    
    X = StandardScaler().fit_transform(df_numeric)
    
    labels = np.array([])
    if X.shape[0] >= n_clusters:
       labels = fcluster(linkage(X, method="ward"), n_clusters, criterion="maxclust")

    n_components = min(2, X.shape[1])
    if n_components > 0:
        pca = PCA(n_components=n_components).fit(X)
        coords = pca.transform(X)
        coords_df = pd.DataFrame(coords, columns=[f"PC{i+1}" for i in range(n_components)], index=df_numeric.index)
        return labels, pca, coords_df
    else:
        return labels, None, pd.DataFrame(index=df_numeric.index)

# --- NETLIFY FUNCTION HANDLER --- #
def handler(event, context):
    try:
        # 1. Charger les données de référence une seule fois
        ref_original = load_reference_data()
        ref = ref_original.copy()
        ecology_df = load_ecology_data()
        syntaxon_data_list = load_syntaxon_data()
        
        ref_binom_series = pd.Series(ref["Espece"].astype(str).str.split().str[:2].str.join(" ").str.lower())

        # 2. Recevoir les données de l'utilisateur depuis le frontend
        body = json.loads(event.get("body", "{}"))
        releves_data = body.get("releves_data", [])
        selected_indices = body.get("selected_indices", [])

        if not releves_data or not selected_indices:
            return {"statusCode": 400, "body": json.dumps({"error": "Données de relevé ou indices manquants"})}

        df_releves = pd.DataFrame(releves_data)
        habitat_names = df_releves.iloc[0].tolist()

        # 3. Traitement principal (inspiré de app.py)
        all_species_data = []
        for habitat_idx in selected_indices:
            habitat_name = habitat_names[habitat_idx] or f"Relevé {habitat_idx + 1}"
            species_in_col = df_releves.iloc[1:, habitat_idx].dropna().astype(str).str.strip().tolist()
            
            for raw_species in species_in_col:
                if not raw_species: continue
                binom_species = normalize_species_name(raw_species)
                match = ref_binom_series[ref_binom_series == binom_species]
                if not match.empty:
                    ref_idx = match.index[0]
                    trait_data = ref.loc[ref_idx].to_dict()
                    trait_data['Source_Habitat'] = habitat_name
                    trait_data['Espece_User_Input_Raw'] = raw_species
                    eco_desc = ecology_df.loc[binom_species, 'Description_Ecologie'] if binom_species in ecology_df.index else None
                    trait_data['Ecologie'] = format_ecology_for_hover(eco_desc)
                    all_species_data.append(trait_data)

        if not all_species_data:
            return {"statusCode": 200, "body": json.dumps({"message": "Aucune espèce correspondante trouvée dans les relevés sélectionnés."})}

        sub_df = pd.DataFrame(all_species_data)
        
        # 4. Analyse PCA
        numeric_traits = ref.select_dtypes(include=np.number).columns.tolist()
        sub_numeric = sub_df[numeric_traits].dropna(axis=1, how='all').fillna(0)
        
        labels, pca_obj, coords_df = analyse_pca(sub_numeric)

        # 5. Calcul des communalités
        communalities_data = []
        if pca_obj and hasattr(pca_obj, 'components_'):
            loadings = pca_obj.components_.T * np.sqrt(pca_obj.explained_variance_)
            communal = (loadings**2).sum(axis=1)
            communal_percent = np.clip((communal * 100).round(0).astype(int), 0, 100)
            communalities_data = [{"Variable": name, "Communalité (%)": val} for name, val in zip(sub_numeric.columns, communal_percent)]
            communalities_data = sorted(communalities_data, key=lambda x: x["Communalité (%)"], reverse=True)

        # 6. Identification des syntaxons
        releve_species_norm = {normalize_species_name(sp) for sp in sub_df['Espece'].unique()}
        syntaxon_matches = []
        for syntaxon in syntaxon_data_list:
            common = releve_species_norm.intersection(syntaxon['species_set'])
            if common:
                syntaxon_matches.append({
                    'id': syntaxon['id'],
                    'name_latin': syntaxon['name_latin'],
                    'score': len(common),
                    'common_species': list(common),
                    'absent_species': list(syntaxon['species_set'] - common)
                })
        top_syntaxons = sorted(syntaxon_matches, key=lambda x: x['score'], reverse=True)[:5]
        
        # 7. Regrouper les résultats
        results = {
            "species_data": sub_df.to_dict(orient='records'),
            "pca_coords": coords_df.to_dict(orient='records'),
            "communalities": communalities_data,
            "top_syntaxons": top_syntaxons,
        }

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(results, cls=NpEncoder)
        }

    except Exception as e:
        import traceback
        error_message = f"Une erreur est survenue dans la fonction serverless: {str(e)}"
        error_trace = traceback.format_exc()
        # Log l'erreur pour le débogage côté serveur dans les logs Netlify
        print(error_message)
        print(error_trace)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": error_message, "trace": error_trace})
        }
