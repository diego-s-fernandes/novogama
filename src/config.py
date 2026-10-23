"""
Configurações centrais do painel eleitoral de Novo Gama (GO) — Eleições 2024.

Os caminhos, códigos oficiais do TSE e parâmetros de validação geográfica ficam
concentrados aqui para evitar valores mágicos espalhados pelo código.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Diretórios do projeto
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

for _directory in (RAW_DIR, PROCESSED_DIR):
    _directory.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Eleição / filtros oficiais
# ---------------------------------------------------------------------------
ANO_ELEICAO = 2024
NR_TURNO_ALVO = 1
SG_UF_ALVO = "GO"
MUNICIPIO_ALVO = "NOVO GAMA"
# Código do município no TSE (o mesmo usado em SG_UE na consulta de candidatos).
CD_MUNICIPIO_TSE = 93327
CD_CARGO_VEREADOR = 13
DS_CARGO_VEREADOR = "VEREADOR"

# ---------------------------------------------------------------------------
# URLs oficiais do Repositório de Dados Abertos do TSE
# ---------------------------------------------------------------------------
TSE_VOTACAO_GO_URL = (
    "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_2024_GO.zip"
)
TSE_LOCAIS_VOTACAO_URL = (
    "https://cdn.tse.jus.br/estatistica/sead/odsele/eleitorado_locais_votacao/"
    "eleitorado_local_votacao_2024.zip"
)
TSE_CANDIDATOS_URL = (
    "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2024.zip"
)

# ---------------------------------------------------------------------------
# Arquivos processados (camada servida ao painel)
# ---------------------------------------------------------------------------
PROCESSED_VOTACAO_FILE = PROCESSED_DIR / "votacao_vereador_novogama_2024.csv"
PROCESSED_LOCAIS_FILE = PROCESSED_DIR / "locais_votacao_novogama_2024.csv"
PROCESSED_MERGED_FILE = PROCESSED_DIR / "votacao_georreferenciada_novogama_2024.csv"
PROCESSED_CANDIDATOS_FILE = PROCESSED_DIR / "candidatos_novogama_2024.csv"
PROCESSED_RESUMO_FILE = PROCESSED_DIR / "resumo_candidatos_novogama_2024.csv"
PROCESSED_METADATA_FILE = PROCESSED_DIR / "metadata_novogama_2024.json"
GEOCODE_CACHE_FILE = PROCESSED_DIR / "geocode_cache_novogama.json"

# ---------------------------------------------------------------------------
# Geografia
# ---------------------------------------------------------------------------
# Centro aproximado da mancha urbana de Novo Gama. O mapa, porém, usa os
# limites reais dos locais de votação para enquadrar a visualização.
NOVO_GAMA_CENTER = (-16.0695, -48.0500)
DEFAULT_ZOOM = 12

# Limites do Brasil (validação dura: fora disso a coordenada é descartada).
BRAZIL_BOUNDS = {
    "lat_min": -33.75,
    "lat_max": 5.27,
    "lon_min": -73.99,
    "lon_max": -34.79,
}

# Limites de plausibilidade para Novo Gama e entorno imediato. Coordenadas
# oficiais fora desta caixa não são descartadas automaticamente: são marcadas
# para auditoria e, se estiverem muito distantes, substituídas por fallback.
NOVO_GAMA_BOUNDS = {
    "lat_min": -16.30,
    "lat_max": -15.90,
    "lon_min": -48.25,
    "lon_max": -47.85,
}
MAX_DISTANCIA_MUNICIPIO_KM = 35.0

# Centróides de bairros usados somente como último recurso de fallback.
# Foram calibrados com os locais de votação oficiais de 2024; o pipeline
# recalcula os centróides a partir dos dados sempre que possível.
BAIRROS_CENTROIDES_NOVO_GAMA = {
    "PEDREGAL": (-16.0710, -48.0335),
    "JARDIM LAGO AZUL": (-16.0915, -48.0740),
    "BOA VISTA": (-16.0580, -48.0600),
    "LUNABEL": (-16.0810, -48.0635),
    "MONT SERRAT": (-16.0603, -48.0609),
    "VALE DO PEDREGAL": (-16.0970, -48.0339),
    "GRANDE VALE": (-16.0573, -48.0471),
    "RESIDENCIAL ALVORADA": (-16.0751, -48.0768),
    "JARDIM PAIVA": (-16.0749, -48.0578),
    "RESIDENCIAL AMERICA DO SUL": (-16.0592, -48.0852),
    "NUCLEO RESIDENCIAL BRASILIA": (-16.1120, -48.0910),
    "VALE DAS ANDORINHAS": (-16.1234, -48.0332),
    "CHACARAS MINAS GERAIS": (-16.0846, -48.0409),
    "JARDIM TROPICAL": (-16.1040, -48.0741),
    "NOVO GAMA": (-16.0545, -48.0340),
    "CENTRO": (-16.0545, -48.0340),
}

# ---------------------------------------------------------------------------
# Semântica visual (paleta acessível, sem depender de vermelho/verde)
# ---------------------------------------------------------------------------
STATUS_LABELS = {
    "Eleito": "Eleito",
    "Suplente": "Suplente",
    "Não eleito": "Não eleito",
    "Sem situação": "Sem situação",
}
STATUS_COLORS = {
    "Eleito": "#1d4ed8",       # azul
    "Suplente": "#b45309",     # âmbar
    "Não eleito": "#64748b",   # cinza-azulado
    "Sem situação": "#94a3b8", # cinza claro
}
STATUS_ICONS = {
    "Eleito": "●",
    "Suplente": "◐",
    "Não eleito": "○",
    "Sem situação": "·",
}

PRIMARY_COLOR = "#1d4ed8"
SECONDARY_COLOR = "#0f766e"
NEUTRAL_COLOR = "#64748b"
GRID_COLOR = "#e2e8f0"
TEXT_COLOR = "#0f172a"

# CARTO/Stamen passaram a exigir chave de API; usamos camadas abertas.
TILE_OPTIONS = {
    "Ruas (OpenStreetMap)": "OpenStreetMap",
    "Relevo (OpenTopoMap)": "OpenTopoMap",
    "Satélite (Esri World Imagery)": "Esri WorldImagery",
}

# Rótulos de precisão usados na camada geoespacial.
PRECISAO_OFICIAL = "Local exato (TSE)"
PRECISAO_GEOCODIFICADA = "Geocodificado (OSM/Nominatim)"
PRECISAO_BAIRRO = "Aproximado (centróide do bairro)"
PRECISAO_MUNICIPIO = "Aproximado (centróide municipal)"
