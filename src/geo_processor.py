"""
Tratamento geoespacial dos locais de votação de Novo Gama (GO).

Princípios:
- a coordenada oficial do TSE é a fonte primária e é agregada por local de
  votação (``NR_LOCAL_VOTACAO``), não por seção;
- coordenadas inválidas, zeradas, ausentes ou claramente fora do município
  recebem fallback explícito e passam a ser marcadas como aproximadas;
- cada ponto no mapa carrega a procedência da coordenada, para que o painel
  possa distinguir local exato de estimativa.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import unicodedata
from typing import Dict, Optional, Tuple

import pandas as pd

from src.config import (
    BAIRROS_CENTROIDES_NOVO_GAMA,
    BRAZIL_BOUNDS,
    GEOCODE_CACHE_FILE,
    MAX_DISTANCIA_MUNICIPIO_KM,
    NOVO_GAMA_BOUNDS,
    NOVO_GAMA_CENTER,
    PRECISAO_BAIRRO,
    PRECISAO_GEOCODIFICADA,
    PRECISAO_MUNICIPIO,
    PRECISAO_OFICIAL,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalização e geometria
# ---------------------------------------------------------------------------
def normalize_text(value: object) -> str:
    """Remove acentos, padroniza caixa e espaços para uso em chaves/join."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip().upper()
    text = "".join(
        char
        for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"\s+", " ", text).strip()


def parse_coordinate(value: object) -> Optional[float]:
    """Converte coordenada textual do TSE (vírgula decimal) em float válido."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip().replace(",", ".")
    if text in {"", "-", "-1", "-1.0", "0", "0.0", "NAN", "NONE", "NULL"}:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    if number == 0.0 or number == -1.0:
        return None
    return number


def is_valid_brazil_coord(lat: Optional[float], lon: Optional[float]) -> bool:
    """Validação dura: a coordenada precisa estar dentro do Brasil."""
    if lat is None or lon is None:
        return False
    try:
        if math.isnan(lat) or math.isnan(lon):
            return False
    except TypeError:
        return False
    return (
        BRAZIL_BOUNDS["lat_min"] <= float(lat) <= BRAZIL_BOUNDS["lat_max"]
        and BRAZIL_BOUNDS["lon_min"] <= float(lon) <= BRAZIL_BOUNDS["lon_max"]
    )


def is_plausible_novogama_coord(lat: Optional[float], lon: Optional[float]) -> bool:
    """Validação fina: coordenada dentro da caixa de Novo Gama/entorno."""
    if not is_valid_brazil_coord(lat, lon):
        return False
    return (
        NOVO_GAMA_BOUNDS["lat_min"] <= float(lat) <= NOVO_GAMA_BOUNDS["lat_max"]
        and NOVO_GAMA_BOUNDS["lon_min"] <= float(lon) <= NOVO_GAMA_BOUNDS["lon_max"]
    )


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em km entre dois pares de coordenadas."""
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def _deterministic_jitter(seed_text: str, max_offset: float = 0.0018) -> Tuple[float, float]:
    """Deslocamento pequeno e reprodutível para separar fallbacks sobrepostos."""
    digest = hashlib.md5(seed_text.encode("utf-8")).hexdigest()
    u1 = (int(digest[:8], 16) / 0xFFFFFFFF) * 2 - 1
    u2 = (int(digest[8:16], 16) / 0xFFFFFFFF) * 2 - 1
    return u1 * max_offset, u2 * max_offset


# ---------------------------------------------------------------------------
# Cache de geocodificação
# ---------------------------------------------------------------------------
def _load_geocode_cache() -> dict:
    if GEOCODE_CACHE_FILE.exists():
        try:
            return json.loads(GEOCODE_CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _save_geocode_cache(cache: dict) -> None:
    try:
        GEOCODE_CACHE_FILE.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        logger.warning("Não foi possível salvar o cache de geocodificação: %s", exc)


def geocode_fallback_nominatim(
    nm_locvot: str,
    ds_endereco: str,
    nm_bairro: str = "",
    allow_network: bool = True,
) -> Optional[Tuple[float, float]]:
    """Geocodifica um local via Nominatim/OSM, com cache em disco."""
    cache_key = "|".join(
        normalize_text(part) for part in (nm_locvot, ds_endereco, nm_bairro)
    )
    cache = _load_geocode_cache()
    if cache_key in cache:
        cached = cache[cache_key]
        if cached and len(cached) == 2:
            return float(cached[0]), float(cached[1])
        return None

    if not allow_network:
        return None

    try:
        from geopy.geocoders import Nominatim

        geolocator = Nominatim(user_agent="painel_novogama_2024_gis", timeout=5)
        queries = [
            f"{nm_locvot}, {nm_bairro}, Novo Gama, Goiás, Brasil",
            f"{ds_endereco}, Novo Gama, Goiás, Brasil",
            f"{nm_bairro}, Novo Gama, Goiás, Brasil",
        ]
        for query in queries:
            if not normalize_text(query):
                continue
            location = geolocator.geocode(query, country_codes="br")
            if location and is_plausible_novogama_coord(
                location.latitude, location.longitude
            ):
                coords = (float(location.latitude), float(location.longitude))
                cache[cache_key] = list(coords)
                _save_geocode_cache(cache)
                return coords
    except Exception as exc:  # geopy/rede: fallback silencioso com log
        logger.debug("Geocodificação indisponível para '%s': %s", nm_locvot, exc)

    cache[cache_key] = None
    _save_geocode_cache(cache)
    return None


# ---------------------------------------------------------------------------
# Fallback geográfico
# ---------------------------------------------------------------------------
def _build_bairro_centroids(
    df: pd.DataFrame, bairro_centroids: Optional[Dict[str, Tuple[float, float]]]
) -> Dict[str, Tuple[float, float]]:
    """Combina centróides informados com a mediana observada nos dados oficiais."""
    centroids: Dict[str, Tuple[float, float]] = {
        normalize_text(key): tuple(value)  # type: ignore[arg-type]
        for key, value in BAIRROS_CENTROIDES_NOVO_GAMA.items()
    }
    if bairro_centroids:
        for key, value in bairro_centroids.items():
            centroids[normalize_text(key)] = (float(value[0]), float(value[1]))

    official = df[df["_COORD_VALIDA"]].copy()
    if not official.empty:
        official["_BAIRRO_NORM"] = official["NM_BAIRRO"].map(normalize_text)
        medians = official.groupby("_BAIRRO_NORM")[["_LAT", "_LON"]].median()
        for bairro, row in medians.iterrows():
            if bairro and bairro not in {"", "NAO INFORMADO"}:
                centroids[bairro] = (float(row["_LAT"]), float(row["_LON"]))
    return centroids


def _infer_centroid(
    nm_locvot: str,
    ds_endereco: str,
    nm_bairro: str,
    centroids: Dict[str, Tuple[float, float]],
) -> Tuple[float, float, str]:
    """Último recurso: centróide do bairro ou do município, com jitter."""
    bairro_norm = normalize_text(nm_bairro)
    combined = normalize_text(f"{nm_locvot} {ds_endereco} {bairro_norm}")

    for key, (lat, lon) in centroids.items():
        if key and (key == bairro_norm or key in combined):
            dlat, dlon = _deterministic_jitter(
                normalize_text(nm_locvot or ds_endereco), max_offset=0.0012
            )
            return (
                round(lat + dlat, 6),
                round(lon + dlon, 6),
                PRECISAO_BAIRRO,
            )

    dlat, dlon = _deterministic_jitter(
        normalize_text(nm_locvot or ds_endereco), max_offset=0.0022
    )
    return (
        round(NOVO_GAMA_CENTER[0] + dlat, 6),
        round(NOVO_GAMA_CENTER[1] + dlon, 6),
        PRECISAO_MUNICIPIO,
    )


# ---------------------------------------------------------------------------
# Limpeza geoespacial
# ---------------------------------------------------------------------------
def clean_and_enrich_locais(
    df_locais: pd.DataFrame,
    allow_network_geocode: bool = False,
    bairro_centroids: Optional[Dict[str, Tuple[float, float]]] = None,
) -> pd.DataFrame:
    """
    Limpa e enriquece a tabela de locais de votação.

    A saída tem uma linha por seção, com coordenada do local e colunas de
    procedência (``ORIGEM_COORD``, ``PRECISAO``, ``COORD_APROXIMADA``,
    ``USAR_NO_MAPA``, ``DIST_KM_CENTRO``).
    """
    df = df_locais.copy()

    for column, default in [
        ("NM_LOCVOT", "LOCAL NÃO INFORMADO"),
        ("DS_ENDERECO", "ENDEREÇO NÃO INFORMADO"),
        ("NM_BAIRRO", ""),
        ("NR_LATITUDE", None),
        ("NR_LONGITUDE", None),
        ("NR_LOCAL_VOTACAO", None),
        ("QT_ELEITOR_SECAO", 0),
    ]:
        if column not in df.columns:
            df[column] = default

    df["NR_ZONA"] = pd.to_numeric(df["NR_ZONA"], errors="coerce").astype("Int64")
    df["NR_SECAO"] = pd.to_numeric(df["NR_SECAO"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["NR_ZONA", "NR_SECAO"]).copy()
    df["NR_ZONA"] = df["NR_ZONA"].astype(int)
    df["NR_SECAO"] = df["NR_SECAO"].astype(int)

    df["NM_LOCVOT"] = df["NM_LOCVOT"].fillna("LOCAL NÃO INFORMADO").astype(str).str.strip()
    df["DS_ENDERECO"] = df["DS_ENDERECO"].fillna("ENDEREÇO NÃO INFORMADO").astype(str).str.strip()
    df["NM_BAIRRO"] = df["NM_BAIRRO"].fillna("").astype(str).str.strip()
    df["QT_ELEITOR_SECAO"] = (
        pd.to_numeric(df["QT_ELEITOR_SECAO"], errors="coerce").fillna(0).astype(int)
    )

    # Chave estável do local: código TSE quando disponível; nome normalizado
    # como alternativa para bases antigas.
    local_code = df["NR_LOCAL_VOTACAO"].astype(str).str.strip()
    fallback_key = df["NM_LOCVOT"].map(normalize_text)
    df["LOCAL_KEY"] = local_code.where(
        local_code.ne("") & local_code.ne("NAN") & local_code.ne("NONE"),
        fallback_key,
    )

    df["_LAT"] = df["NR_LATITUDE"].map(parse_coordinate)
    df["_LON"] = df["NR_LONGITUDE"].map(parse_coordinate)
    df["_COORD_VALIDA"] = [
        is_valid_brazil_coord(lat, lon) for lat, lon in zip(df["_LAT"], df["_LON"])
    ]
    # Coordenada dentro do Brasil mas fora da caixa do município é suspeita.
    df["_COORD_PLAUSIVEL"] = [
        is_plausible_novogama_coord(lat, lon) for lat, lon in zip(df["_LAT"], df["_LON"])
    ]

    centroids = _build_bairro_centroids(df, bairro_centroids)

    # Agrega a coordenada por local de votação (a menor unidade geográfica
    # disponível no TSE; seções do mesmo local compartilham o endereço).
    local_rows = (
        df.groupby("LOCAL_KEY", sort=False)
        .agg(
            lat=("_LAT", "median"),
            lon=("_LON", "median"),
            plausivel=("_COORD_PLAUSIVEL", "max"),
            nm_locvot=("NM_LOCVOT", "first"),
            ds_endereco=("DS_ENDERECO", "first"),
            nm_bairro=("NM_BAIRRO", "first"),
        )
        .reset_index()
    )

    resolved: Dict[str, Tuple[float, float, str, str]] = {}
    for row in local_rows.itertuples(index=False):
        lat, lon = row.lat, row.lon
        if pd.notna(lat) and pd.notna(lon) and bool(row.plausivel):
            resolved[row.LOCAL_KEY] = (
                float(lat),
                float(lon),
                PRECISAO_OFICIAL,
                "Coordenada oficial do TSE",
            )
            continue

        # Coordenada oficial fora da caixa do município: registra o motivo e
        # tenta um fallback confiável antes de plotar um ponto errado.
        geocoded = geocode_fallback_nominatim(
            str(row.nm_locvot),
            str(row.ds_endereco),
            str(row.nm_bairro),
            allow_network=allow_network_geocode,
        )
        if geocoded is not None:
            resolved[row.LOCAL_KEY] = (
                float(geocoded[0]),
                float(geocoded[1]),
                PRECISAO_GEOCODIFICADA,
                "Coordenada oficial ausente/inválida; geocodificada via OSM",
            )
            continue

        fallback_lat, fallback_lon, precision = _infer_centroid(
            str(row.nm_locvot), str(row.ds_endereco), str(row.nm_bairro), centroids
        )
        reason = (
            "Coordenada oficial ausente"
            if pd.isna(lat) or pd.isna(lon)
            else "Coordenada oficial fora da área de Novo Gama"
        )
        resolved[row.LOCAL_KEY] = (
            fallback_lat,
            fallback_lon,
            precision,
            reason,
        )

    df["NR_LATITUDE"] = df["LOCAL_KEY"].map(lambda key: resolved[key][0])
    df["NR_LONGITUDE"] = df["LOCAL_KEY"].map(lambda key: resolved[key][1])
    df["PRECISAO"] = df["LOCAL_KEY"].map(lambda key: resolved[key][2])
    df["ORIGEM_COORD"] = df["PRECISAO"]
    df["COORD_OBS"] = df["LOCAL_KEY"].map(lambda key: resolved[key][3])
    df["COORD_APROXIMADA"] = df["PRECISAO"].ne(PRECISAO_OFICIAL)
    df["DIST_KM_CENTRO"] = [
        round(haversine_km(lat, lon, *NOVO_GAMA_CENTER), 2)
        for lat, lon in zip(df["NR_LATITUDE"], df["NR_LONGITUDE"])
    ]
    df["USAR_NO_MAPA"] = (
        df["DIST_KM_CENTRO"].le(MAX_DISTANCIA_MUNICIPIO_KM)
        & df["NR_LATITUDE"].notna()
        & df["NR_LONGITUDE"].notna()
    )

    df = (
        df.sort_values(["NR_ZONA", "NR_SECAO"])
        .drop_duplicates(subset=["NR_ZONA", "NR_SECAO"], keep="first")
        .reset_index(drop=True)
    )

    # Preenche bairro vazio com uma descrição legível.
    df.loc[df["NM_BAIRRO"].eq(""), "NM_BAIRRO"] = "Não informado"

    cols = [
        "NR_ZONA",
        "NR_SECAO",
        "NR_LOCAL_VOTACAO",
        "LOCAL_KEY",
        "NM_LOCVOT",
        "DS_ENDERECO",
        "NM_BAIRRO",
        "NR_CEP",
        "NR_LATITUDE",
        "NR_LONGITUDE",
        "PRECISAO",
        "ORIGEM_COORD",
        "COORD_OBS",
        "COORD_APROXIMADA",
        "USAR_NO_MAPA",
        "DIST_KM_CENTRO",
        "QT_ELEITOR_SECAO",
    ]
    return df[[column for column in cols if column in df.columns]].reset_index(drop=True)


def join_votacao_and_locais(
    df_votacao: pd.DataFrame, df_locais_clean: pd.DataFrame
) -> pd.DataFrame:
    """Faz o join por zona/seção e garante coordenadas para todas as linhas."""
    votes = df_votacao.copy()
    votes["NR_ZONA"] = pd.to_numeric(votes["NR_ZONA"], errors="coerce").astype(int)
    votes["NR_SECAO"] = pd.to_numeric(votes["NR_SECAO"], errors="coerce").astype(int)
    votes["QT_VOTOS"] = (
        pd.to_numeric(votes["QT_VOTOS"], errors="coerce").fillna(0).astype(int)
    )

    merged = votes.merge(
        df_locais_clean,
        on=["NR_ZONA", "NR_SECAO"],
        how="left",
        validate="many_to_one",
    )

    missing = merged["NR_LATITUDE"].isna() | merged["NR_LONGITUDE"].isna()
    if missing.any():
        for idx in merged[missing].index:
            row = merged.loc[idx]
            nm_loc = str(row.get("NM_LOCVOT") or f"SEÇÃO {row['NR_SECAO']} - NOVO GAMA")
            endereco = str(row.get("DS_ENDERECO") or "NOVO GAMA - GO")
            lat, lon, precision = _infer_centroid(nm_loc, endereco, "", {})
            merged.at[idx, "NM_LOCVOT"] = nm_loc
            merged.at[idx, "DS_ENDERECO"] = endereco
            merged.at[idx, "NM_BAIRRO"] = "Não informado"
            merged.at[idx, "NR_LATITUDE"] = lat
            merged.at[idx, "NR_LONGITUDE"] = lon
            merged.at[idx, "PRECISAO"] = precision
            merged.at[idx, "ORIGEM_COORD"] = precision
            merged.at[idx, "COORD_OBS"] = "Seção sem local de votação correspondente"
            merged.at[idx, "COORD_APROXIMADA"] = True
            merged.at[idx, "USAR_NO_MAPA"] = True
            merged.at[idx, "DIST_KM_CENTRO"] = round(
                haversine_km(lat, lon, *NOVO_GAMA_CENTER), 2
            )
            merged.at[idx, "QT_ELEITOR_SECAO"] = 0

    merged["NR_LATITUDE"] = merged["NR_LATITUDE"].astype(float)
    merged["NR_LONGITUDE"] = merged["NR_LONGITUDE"].astype(float)
    merged["QT_ELEITOR_SECAO"] = (
        pd.to_numeric(merged["QT_ELEITOR_SECAO"], errors="coerce").fillna(0).astype(int)
    )
    return merged
