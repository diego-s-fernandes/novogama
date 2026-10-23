"""
Extração, tratamento e persistência dos dados oficiais do TSE (2024).

Fontes:
1. ``votacao_secao_2024_GO.zip`` — votação nominal por seção;
2. ``eleitorado_local_votacao_2024.zip`` — locais, seções e coordenadas;
3. ``consulta_cand_2024.zip`` — registro de candidaturas, partido e situação
   (eleito, suplente, não eleito).

O módulo filtra Novo Gama / Vereador / 1º turno, cruza as três bases e grava
uma camada processada pronta para o painel. Nenhum dado é inventado: quando a
base oficial não está disponível, o painel informa e orienta o download.
"""
from __future__ import annotations

import io
import json
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Tuple

import pandas as pd
import requests

from src.analytics import build_candidate_summary, get_totals
from src.config import (
    ANO_ELEICAO,
    CD_CARGO_VEREADOR,
    CD_MUNICIPIO_TSE,
    MUNICIPIO_ALVO,
    NR_TURNO_ALVO,
    PROCESSED_CANDIDATOS_FILE,
    PROCESSED_LOCAIS_FILE,
    PROCESSED_MERGED_FILE,
    PROCESSED_METADATA_FILE,
    PROCESSED_RESUMO_FILE,
    PROCESSED_VOTACAO_FILE,
    RAW_DIR,
    SG_UF_ALVO,
    TSE_CANDIDATOS_URL,
    TSE_LOCAIS_VOTACAO_URL,
    TSE_VOTACAO_GO_URL,
)
from src.geo_processor import (
    clean_and_enrich_locais,
    join_votacao_and_locais,
    normalize_text,
)

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[float, str], None]]


@dataclass
class ElectionData:
    """Pacote de dados consumido pelo painel."""

    votacao: pd.DataFrame = field(default_factory=pd.DataFrame)
    locais: pd.DataFrame = field(default_factory=pd.DataFrame)
    candidatos: pd.DataFrame = field(default_factory=pd.DataFrame)
    resumo: pd.DataFrame = field(default_factory=pd.DataFrame)
    metadata: dict = field(default_factory=dict)
    status: str = "Sem dados"

    @property
    def empty(self) -> bool:
        return self.votacao.empty or self.locais.empty or self.resumo.empty


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
def download_file_with_progress(
    url: str,
    dest_path: Path,
    progress_callback: ProgressCallback = None,
    timeout: int = 180,
) -> Path:
    """Baixa um arquivo do TSE em streaming, com callback de progresso."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_suffix(dest_path.suffix + ".part")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Painel-TSE-GIS/2.0"
    }
    with requests.get(url, stream=True, headers=headers, timeout=timeout) as response:
        response.raise_for_status()
        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0
        chunk_size = 1024 * 512
        with open(temp_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                handle.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total_size:
                    pct = min(downloaded / total_size, 1.0)
                    progress_callback(
                        pct,
                        f"Baixando {dest_path.name}: "
                        f"{downloaded / 1024 / 1024:.1f} / "
                        f"{total_size / 1024 / 1024:.1f} MB",
                    )
    if dest_path.exists():
        dest_path.unlink()
    temp_path.replace(dest_path)
    return dest_path


# ---------------------------------------------------------------------------
# Filtros de streaming
# ---------------------------------------------------------------------------
def _filter_votacao_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
    """Mantém apenas Novo Gama / Vereador / 1º turno."""
    df = chunk.copy()
    df.columns = [str(column).strip().upper() for column in df.columns]

    if "NM_MUNICIPIO" in df.columns:
        mask_municipio = df["NM_MUNICIPIO"].astype(str).map(normalize_text).eq(
            normalize_text(MUNICIPIO_ALVO)
        )
        if "CD_MUNICIPIO" in df.columns:
            mask_municipio = mask_municipio | pd.to_numeric(
                df["CD_MUNICIPIO"], errors="coerce"
            ).eq(CD_MUNICIPIO_TSE)
        df = df[mask_municipio]
    elif "CD_MUNICIPIO" in df.columns:
        df = df[pd.to_numeric(df["CD_MUNICIPIO"], errors="coerce").eq(CD_MUNICIPIO_TSE)]
    if df.empty:
        return df

    if "NR_TURNO" in df.columns:
        df = df[pd.to_numeric(df["NR_TURNO"], errors="coerce").eq(NR_TURNO_ALVO)]
    if df.empty:
        return df

    mask_cargo = pd.Series(False, index=df.index)
    if "CD_CARGO" in df.columns:
        mask_cargo = mask_cargo | pd.to_numeric(df["CD_CARGO"], errors="coerce").eq(
            CD_CARGO_VEREADOR
        )
    if "DS_CARGO" in df.columns:
        mask_cargo = mask_cargo | df["DS_CARGO"].astype(str).map(normalize_text).eq(
            "VEREADOR"
        )
    df = df[mask_cargo]
    if df.empty:
        return df

    wanted = [
        "ANO_ELEICAO",
        "NR_TURNO",
        "SG_UF",
        "CD_MUNICIPIO",
        "NM_MUNICIPIO",
        "NR_ZONA",
        "NR_SECAO",
        "CD_CARGO",
        "DS_CARGO",
        "NR_VOTAVEL",
        "NM_VOTAVEL",
        "QT_VOTOS",
    ]
    return df[[column for column in wanted if column in df.columns]].copy()


def _filter_locais_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
    """Mantém Novo Gama, 1º turno e apenas as seções principais."""
    df = chunk.copy()
    df.columns = [str(column).strip().upper() for column in df.columns]

    if "SG_UF" in df.columns:
        df = df[df["SG_UF"].astype(str).str.strip().str.upper().eq(SG_UF_ALVO)]
    if df.empty:
        return df

    if "NM_MUNICIPIO" in df.columns:
        mask_municipio = df["NM_MUNICIPIO"].astype(str).map(normalize_text).eq(
            normalize_text(MUNICIPIO_ALVO)
        )
        if "CD_MUNICIPIO" in df.columns:
            mask_municipio = mask_municipio | pd.to_numeric(
                df["CD_MUNICIPIO"], errors="coerce"
            ).eq(CD_MUNICIPIO_TSE)
        df = df[mask_municipio]
    elif "CD_MUNICIPIO" in df.columns:
        df = df[pd.to_numeric(df["CD_MUNICIPIO"], errors="coerce").eq(CD_MUNICIPIO_TSE)]
    if df.empty:
        return df

    if "NR_TURNO" in df.columns:
        turno = df[pd.to_numeric(df["NR_TURNO"], errors="coerce").eq(NR_TURNO_ALVO)]
        if not turno.empty:
            df = turno
    if df.empty:
        return df

    # Seções agregadas aparecem como linhas extras no cadastro do TSE. Elas não
    # são urnas independentes e duplicariam a contagem; ficamos com a principal.
    if "CD_TIPO_SECAO_AGREGADA" in df.columns:
        principal = df[df["CD_TIPO_SECAO_AGREGADA"].astype(str) == "1"]
        if not principal.empty:
            df = principal

    rename = {
        "NM_LOCAL_VOTACAO": "NM_LOCVOT",
        "DS_LOCAL_VOTACAO_ENDERECO": "DS_ENDERECO",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    wanted = [
        "NR_ZONA",
        "NR_SECAO",
        "NR_LOCAL_VOTACAO",
        "NM_LOCVOT",
        "DS_ENDERECO",
        "NM_BAIRRO",
        "NR_CEP",
        "NR_LATITUDE",
        "NR_LONGITUDE",
        "DS_SITU_LOCAL_VOTACAO",
        "QT_ELEITOR_SECAO",
    ]
    return df[[column for column in wanted if column in df.columns]].copy()


# ---------------------------------------------------------------------------
# Candidatos
# ---------------------------------------------------------------------------
def _classify_status(value: object) -> str:
    status = normalize_text(value)
    if status.startswith("ELEITO"):
        return "Eleito"
    if status == "SUPLENTE":
        return "Suplente"
    if status.startswith("NAO ELEITO"):
        return "Não eleito"
    return "Sem situação"


def _elected_type(value: object) -> str:
    status = normalize_text(value)
    if "QP" in status:
        return "Quociente partidário"
    if "MEDIA" in status:
        return "Média"
    return "—"


def _prepare_candidates(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza o registro de candidaturas e classifica a situação eleitoral."""
    candidates = df.copy()
    candidates.columns = [str(column).strip().upper() for column in candidates.columns]

    for column in [
        "NR_CANDIDATO",
        "NM_CANDIDATO",
        "NM_URNA_CANDIDATO",
        "SG_PARTIDO",
        "NM_PARTIDO",
        "DS_SIT_TOT_TURNO",
        "NM_COLIGACAO",
        "SQ_CANDIDATO",
        "DS_GENERO",
        "DS_GRAU_INSTRUCAO",
        "DS_COR_RACA",
        "DS_OCUPACAO",
    ]:
        if column not in candidates.columns:
            candidates[column] = ""

    candidates["NR_VOTAVEL"] = candidates["NR_CANDIDATO"].astype(str).str.strip()
    candidates["NM_CANDIDATO"] = (
        candidates["NM_CANDIDATO"].fillna("").astype(str).str.strip()
    )
    candidates["NM_URNA_CANDIDATO"] = (
        candidates["NM_URNA_CANDIDATO"]
        .fillna(candidates["NM_CANDIDATO"])
        .astype(str)
        .str.strip()
    )
    candidates.loc[candidates["NM_URNA_CANDIDATO"].eq(""), "NM_URNA_CANDIDATO"] = (
        candidates["NM_CANDIDATO"]
    )
    candidates["SG_PARTIDO"] = (
        candidates["SG_PARTIDO"].fillna("").astype(str).str.strip()
    )
    candidates["NM_PARTIDO"] = (
        candidates["NM_PARTIDO"].fillna("").astype(str).str.strip()
    )
    candidates["SITUACAO_TSE"] = (
        candidates["DS_SIT_TOT_TURNO"]
        .fillna("Não informada")
        .astype(str)
        .str.strip()
        .replace({"#NULO": "Não informada", "#NE": "Não informada"})
    )
    candidates["SITUACAO"] = candidates["SITUACAO_TSE"].map(_classify_status)
    candidates["ELEITO"] = candidates["SITUACAO"].eq("Eleito")
    candidates["ELEITO_POR"] = candidates["SITUACAO_TSE"].map(_elected_type)
    candidates["COLIGACAO"] = (
        candidates["NM_COLIGACAO"].fillna("").astype(str).str.strip().replace("", "—")
    )
    candidates["CANDIDATO_LABEL"] = (
        candidates["NM_URNA_CANDIDATO"] + " (" + candidates["SG_PARTIDO"] + ")"
    )
    candidates["BUSCA"] = (
        candidates["NM_URNA_CANDIDATO"].astype(str)
        + " "
        + candidates["NM_CANDIDATO"].astype(str)
        + " "
        + candidates["NR_VOTAVEL"].astype(str)
        + " "
        + candidates["SG_PARTIDO"].astype(str)
    ).map(normalize_text)

    # Um candidato por número; em caso de duplicidade, mantém a situação mais
    # informativa (eleito > suplente > não eleito > sem situação).
    candidates["_ORDEM"] = candidates["SITUACAO"].map(
        {"Eleito": 1, "Suplente": 2, "Não eleito": 3, "Sem situação": 4}
    ).fillna(9)
    candidates = (
        candidates.sort_values(["NR_VOTAVEL", "_ORDEM"])
        .drop_duplicates(subset=["NR_VOTAVEL"], keep="first")
        .drop(columns=["_ORDEM"])
        .reset_index(drop=True)
    )

    wanted = [
        "NR_VOTAVEL",
        "NM_CANDIDATO",
        "NM_URNA_CANDIDATO",
        "SG_PARTIDO",
        "NM_PARTIDO",
        "SITUACAO",
        "SITUACAO_TSE",
        "ELEITO",
        "ELEITO_POR",
        "COLIGACAO",
        "CANDIDATO_LABEL",
        "BUSCA",
        "SQ_CANDIDATO",
        "DS_GENERO",
        "DS_GRAU_INSTRUCAO",
        "DS_COR_RACA",
        "DS_OCUPACAO",
    ]
    return candidates[[column for column in wanted if column in candidates.columns]].copy()


def _filter_candidates_frame(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(column).strip().upper() for column in df.columns]
    if "NM_UE" in df.columns:
        mask = df["NM_UE"].astype(str).map(normalize_text).eq(
            normalize_text(MUNICIPIO_ALVO)
        )
    else:
        mask = pd.Series(True, index=df.index)
    if "CD_CARGO" in df.columns:
        mask = mask & pd.to_numeric(df["CD_CARGO"], errors="coerce").eq(
            CD_CARGO_VEREADOR
        )
    if "NR_TURNO" in df.columns:
        mask = mask & pd.to_numeric(df["NR_TURNO"], errors="coerce").eq(NR_TURNO_ALVO)
    filtered = df[mask].copy()
    if filtered.empty:
        raise ValueError(
            "O arquivo de candidatos não contém registros de Vereador de Novo Gama no 1º turno."
        )
    return _prepare_candidates(filtered)


def _read_candidates_from_zip(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        names = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".csv") and "consulta_cand_2024_GO" in name
        ]
        if not names:
            names = [
                name
                for name in archive.namelist()
                if name.lower().endswith(".csv") and "GO" in name.upper()
            ]
        if not names:
            raise FileNotFoundError(f"Não foi encontrado o CSV de Goiás em {path.name}.")
        with archive.open(names[0]) as raw:
            df = pd.read_csv(
                raw,
                sep=";",
                encoding="latin1",
                dtype=str,
                low_memory=False,
            )
    return _filter_candidates_frame(df)


def _read_candidates_from_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", encoding="latin1", dtype=str, low_memory=False)
    return _filter_candidates_frame(df)


# ---------------------------------------------------------------------------
# Leitura genérica de ZIP/CSV
# ---------------------------------------------------------------------------
def read_tse_source(
    source_path: Path,
    chunk_filter: Callable[[pd.DataFrame], pd.DataFrame],
    csv_name_hint: Optional[str] = None,
    chunksize: int = 120_000,
) -> pd.DataFrame:
    """Lê um CSV/ZIP do TSE em chunks, aplicando o filtro em cada bloco."""
    chunks = []
    if source_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(source_path) as archive:
            csv_files = [
                name
                for name in archive.namelist()
                if name.lower().endswith((".csv", ".txt"))
            ]
            if csv_name_hint:
                preferred = [
                    name for name in csv_files if csv_name_hint.lower() in name.lower()
                ]
                if preferred:
                    csv_files = preferred
            if not csv_files:
                raise FileNotFoundError(f"Nenhum CSV encontrado em {source_path.name}.")
            with archive.open(csv_files[0]) as raw:
                stream = io.TextIOWrapper(raw, encoding="latin1", errors="replace")
                reader = pd.read_csv(
                    stream,
                    sep=";",
                    quotechar='"',
                    chunksize=chunksize,
                    low_memory=False,
                    dtype=str,
                )
                for chunk in reader:
                    filtered = chunk_filter(chunk)
                    if not filtered.empty:
                        chunks.append(filtered)
    else:
        reader = pd.read_csv(
            source_path,
            sep=";",
            quotechar='"',
            encoding="latin1",
            chunksize=chunksize,
            low_memory=False,
            dtype=str,
        )
        for chunk in reader:
            filtered = chunk_filter(chunk)
            if not filtered.empty:
                chunks.append(filtered)

    if not chunks:
        return pd.DataFrame()
    return pd.concat(chunks, ignore_index=True)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def _classify_vote_type(nr_votavel: object) -> str:
    number = str(nr_votavel).strip()
    if number == "95":
        return "Branco"
    if number in {"96", "97"}:
        return "Nulo"
    if len(number) <= 2 and number.isdigit():
        return "Legenda"
    if len(number) == 5 and number.isdigit():
        return "Nominal"
    return "Outro"


def build_pipeline_from_files(
    votacao_path: Path,
    locais_path: Optional[Path] = None,
    candidatos_path: Optional[Path] = None,
    allow_network_geocode: bool = False,
    progress_callback: ProgressCallback = None,
    persist: bool = True,
) -> ElectionData:
    """
    Executa o pipeline completo:
    1. filtra votação, locais e candidaturas;
    2. limpa/valida coordenadas e resolve fallbacks;
    3. cruza votos × locais × candidatos;
    4. classifica situação eleitoral e tipo de voto;
    5. grava a camada processada e o resumo de candidatos.
    """
    if progress_callback:
        progress_callback(0.05, "Lendo votação por seção de Novo Gama...")
    votos = read_tse_source(
        votacao_path,
        _filter_votacao_chunk,
        csv_name_hint="votacao_secao_2024_GO",
    )
    if votos.empty:
        raise ValueError(
            "Nenhum registro de Vereador de Novo Gama foi encontrado no arquivo de votação."
        )

    if progress_callback:
        progress_callback(0.30, "Lendo locais de votação e coordenadas oficiais...")
    if locais_path and Path(locais_path).exists():
        locais_raw = read_tse_source(
            locais_path,
            _filter_locais_chunk,
            csv_name_hint="eleitorado_local_votacao_2024",
        )
        if locais_raw.empty:
            locais_raw = read_tse_source(locais_path, _filter_locais_chunk)
    else:
        raise ValueError(
            "O arquivo de locais de votação é obrigatório para georreferenciar as urnas."
        )
    if locais_raw.empty:
        raise ValueError("Nenhum local de votação de Novo Gama foi encontrado.")

    if progress_callback:
        progress_callback(0.45, "Limpando coordenadas e validando a geolocalização...")
    locais = clean_and_enrich_locais(
        locais_raw, allow_network_geocode=allow_network_geocode
    )

    if candidatos_path and Path(candidatos_path).exists():
        if progress_callback:
            progress_callback(0.55, "Lendo o registro de candidaturas do TSE...")
        candidatos = (
            _read_candidates_from_zip(Path(candidatos_path))
            if Path(candidatos_path).suffix.lower() == ".zip"
            else _read_candidates_from_csv(Path(candidatos_path))
        )
    else:
        # Sem o registro de candidaturas ainda é possível analisar votos, mas a
        # situação eleitoral fica indisponível — o painel sinaliza isso.
        logger.warning(
            "Arquivo de candidatos não informado; a situação eleitoral não será preenchida."
        )
        unique = (
            votos[votos["NR_VOTAVEL"].astype(str).str.len().eq(5)]
            .drop_duplicates("NR_VOTAVEL")[["NR_VOTAVEL", "NM_VOTAVEL"]]
            .copy()
        )
        unique["NR_VOTAVEL"] = unique["NR_VOTAVEL"].astype(str)
        unique["NM_CANDIDATO"] = unique["NM_VOTAVEL"]
        unique["NM_URNA_CANDIDATO"] = unique["NM_VOTAVEL"]
        unique["SG_PARTIDO"] = "—"
        unique["NM_PARTIDO"] = "—"
        unique["SITUACAO"] = "Sem situação"
        unique["SITUACAO_TSE"] = "Não informada"
        unique["ELEITO"] = False
        unique["ELEITO_POR"] = "—"
        unique["COLIGACAO"] = "—"
        unique["CANDIDATO_LABEL"] = unique["NM_VOTAVEL"]
        unique["BUSCA"] = unique["NM_VOTAVEL"].map(normalize_text)
        unique["SQ_CANDIDATO"] = ""
        for column in ["DS_GENERO", "DS_GRAU_INSTRUCAO", "DS_COR_RACA", "DS_OCUPACAO"]:
            unique[column] = ""
        candidatos = unique[
            [
                "NR_VOTAVEL",
                "NM_CANDIDATO",
                "NM_URNA_CANDIDATO",
                "SG_PARTIDO",
                "NM_PARTIDO",
                "SITUACAO",
                "SITUACAO_TSE",
                "ELEITO",
                "ELEITO_POR",
                "COLIGACAO",
                "CANDIDATO_LABEL",
                "BUSCA",
                "SQ_CANDIDATO",
                "DS_GENERO",
                "DS_GRAU_INSTRUCAO",
                "DS_COR_RACA",
                "DS_OCUPACAO",
            ]
        ].copy()

    if progress_callback:
        progress_callback(0.68, "Cruzando votos, locais e candidatos...")
    votos["NR_VOTAVEL"] = votos["NR_VOTAVEL"].astype(str).str.strip()
    votos["TP_VOTO"] = votos["NR_VOTAVEL"].map(_classify_vote_type)
    votos["IS_CANDIDATO_NOMINAL"] = votos["TP_VOTO"].eq("Nominal")
    votos["VOTO_VALIDO"] = votos["TP_VOTO"].isin(["Nominal", "Legenda"])
    votos["QT_VOTOS"] = (
        pd.to_numeric(votos["QT_VOTOS"], errors="coerce").fillna(0).astype(int)
    )

    merged = join_votacao_and_locais(votos, locais)
    merged = merged.merge(candidatos, on="NR_VOTAVEL", how="left", suffixes=("", "_CAND"))

    merged["NM_VOTAVEL"] = merged["NM_VOTAVEL"].fillna("").astype(str).str.strip()
    merged["NM_URNA_CANDIDATO"] = merged["NM_URNA_CANDIDATO"].fillna("")
    merged["SG_PARTIDO"] = merged["SG_PARTIDO"].fillna("")
    merged["SITUACAO"] = merged["SITUACAO"].fillna("Voto não nominal")
    merged["ELEITO"] = merged["ELEITO"].fillna(False).astype(bool)
    merged["CANDIDATO_LABEL"] = merged["CANDIDATO_LABEL"].fillna("")
    merged.loc[merged["CANDIDATO_LABEL"].eq(""), "CANDIDATO_LABEL"] = merged.loc[
        merged["CANDIDATO_LABEL"].eq(""), "NM_VOTAVEL"
    ]
    merged["CANDIDATO_LABEL"] = merged.apply(
        lambda row: (
            f"{row['NM_URNA_CANDIDATO']} ({row['SG_PARTIDO']})"
            if str(row.get("NM_URNA_CANDIDATO", "")).strip()
            and str(row.get("SG_PARTIDO", "")).strip()
            else row["CANDIDATO_LABEL"]
        ),
        axis=1,
    )

    if progress_callback:
        progress_callback(0.82, "Calculando o resumo dos candidatos...")
    resumo = build_candidate_summary(merged, candidatos)

    metadata = {
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "ano": ANO_ELEICAO,
        "turno": NR_TURNO_ALVO,
        "municipio": MUNICIPIO_ALVO,
        "uf": SG_UF_ALVO,
        "cargo": "Vereador",
        "cd_municipio": CD_MUNICIPIO_TSE,
        "fontes": {
            "votacao": str(votacao_path),
            "locais": str(locais_path) if locais_path else None,
            "candidatos": str(candidatos_path) if candidatos_path else None,
            "urls": {
                "votacao": TSE_VOTACAO_GO_URL,
                "locais": TSE_LOCAIS_VOTACAO_URL,
                "candidatos": TSE_CANDIDATOS_URL,
            },
        },
        "registros": {
            "votacao": int(len(merged)),
            "locais": int(len(locais)),
            "candidatos": int(len(candidatos)),
            "resumo": int(len(resumo)),
        },
        "totais": get_totals(merged),
        "geolocalizacao": {
            "locais_distintos": int(locais["LOCAL_KEY"].nunique()),
            "coordenadas_oficiais": int(
                locais.drop_duplicates("LOCAL_KEY")["PRECISAO"]
                .eq("Local exato (TSE)")
                .sum()
            ),
            "coordenadas_aproximadas": int(
                locais.drop_duplicates("LOCAL_KEY")["COORD_APROXIMADA"].sum()
            ),
        },
    }

    data = ElectionData(
        votacao=merged,
        locais=locais,
        candidatos=candidatos,
        resumo=resumo,
        metadata=metadata,
        status="Dados oficiais do TSE 2024 (processados agora)",
    )

    if persist:
        if progress_callback:
            progress_callback(0.92, "Gravando a camada processada...")
        _persist(data)
    if progress_callback:
        progress_callback(1.0, "Dados prontos.")
    return data


def _persist(data: ElectionData) -> None:
    """Grava a camada processada em CSV/JSON."""
    PROCESSED_VOTACAO_FILE.parent.mkdir(parents=True, exist_ok=True)
    data.votacao.to_csv(PROCESSED_MERGED_FILE, index=False, encoding="utf-8-sig")
    data.locais.to_csv(PROCESSED_LOCAIS_FILE, index=False, encoding="utf-8-sig")
    data.candidatos.to_csv(PROCESSED_CANDIDATOS_FILE, index=False, encoding="utf-8-sig")
    data.resumo.to_csv(PROCESSED_RESUMO_FILE, index=False, encoding="utf-8-sig")
    # Mantém também a votação sem enriquecimento geográfico, útil para auditoria.
    colunas_votacao = [
        "ANO_ELEICAO",
        "NR_TURNO",
        "SG_UF",
        "CD_MUNICIPIO",
        "NM_MUNICIPIO",
        "NR_ZONA",
        "NR_SECAO",
        "CD_CARGO",
        "DS_CARGO",
        "NR_VOTAVEL",
        "NM_VOTAVEL",
        "QT_VOTOS",
        "TP_VOTO",
        "IS_CANDIDATO_NOMINAL",
        "VOTO_VALIDO",
    ]
    data.votacao[
        [column for column in colunas_votacao if column in data.votacao.columns]
    ].to_csv(PROCESSED_VOTACAO_FILE, index=False, encoding="utf-8-sig")
    PROCESSED_METADATA_FILE.write_text(
        json.dumps(data.metadata, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Download + processamento
# ---------------------------------------------------------------------------
def download_and_process_tse_data(
    progress_callback: ProgressCallback = None,
    allow_network_geocode: bool = False,
) -> ElectionData:
    """Baixa os três pacotes oficiais e executa o pipeline completo."""
    votacao_zip = RAW_DIR / "votacao_secao_2024_GO.zip"
    locais_zip = RAW_DIR / "eleitorado_local_votacao_2024.zip"
    candidatos_zip = RAW_DIR / "consulta_cand_2024.zip"

    def _stage(base: float, span: float):
        def _callback(pct: float, message: str) -> None:
            if progress_callback:
                progress_callback(
                    base + span * min(max(pct, 0.0), 1.0), message
                )

        return _callback

    if not votacao_zip.exists():
        download_file_with_progress(
            TSE_VOTACAO_GO_URL, votacao_zip, progress_callback=_stage(0.0, 0.18)
        )
    if not locais_zip.exists():
        download_file_with_progress(
            TSE_LOCAIS_VOTACAO_URL, locais_zip, progress_callback=_stage(0.18, 0.12)
        )
    if not candidatos_zip.exists():
        download_file_with_progress(
            TSE_CANDIDATOS_URL, candidatos_zip, progress_callback=_stage(0.30, 0.15)
        )

    if progress_callback:
        progress_callback(0.46, "Processando os arquivos oficiais do TSE...")
    return build_pipeline_from_files(
        votacao_zip,
        locais_zip,
        candidatos_zip,
        allow_network_geocode=allow_network_geocode,
        progress_callback=progress_callback,
    )


# ---------------------------------------------------------------------------
# Carregamento da camada processada
# ---------------------------------------------------------------------------
def _load_processed() -> ElectionData:
    votacao = pd.read_csv(
        PROCESSED_MERGED_FILE,
        dtype={"NR_VOTAVEL": str, "NR_ZONA": int, "NR_SECAO": int},
        encoding="utf-8-sig",
    )
    locais = pd.read_csv(
        PROCESSED_LOCAIS_FILE,
        dtype={"NR_ZONA": int, "NR_SECAO": int},
        encoding="utf-8-sig",
    )
    candidatos = pd.read_csv(
        PROCESSED_CANDIDATOS_FILE,
        dtype={"NR_VOTAVEL": str},
        encoding="utf-8-sig",
    )
    resumo = pd.read_csv(
        PROCESSED_RESUMO_FILE,
        dtype={"NR_VOTAVEL": str},
        encoding="utf-8-sig",
    )
    metadata: dict = {}
    if PROCESSED_METADATA_FILE.exists():
        try:
            metadata = json.loads(PROCESSED_METADATA_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadata = {}
    return ElectionData(
        votacao=votacao,
        locais=locais,
        candidatos=candidatos,
        resumo=resumo,
        metadata=metadata,
        status="Dados oficiais do TSE 2024 (cache processado)",
    )


def _find_raw_file(patterns: Tuple[str, ...]) -> Optional[Path]:
    for pattern in patterns:
        matches = sorted(RAW_DIR.glob(pattern))
        if matches:
            return matches[0]
    return None


def load_or_init_dataset() -> ElectionData:
    """Carrega o cache processado ou processa os arquivos brutos disponíveis."""
    required = [
        PROCESSED_MERGED_FILE,
        PROCESSED_LOCAIS_FILE,
        PROCESSED_CANDIDATOS_FILE,
        PROCESSED_RESUMO_FILE,
    ]
    if all(path.exists() for path in required):
        return _load_processed()

    votacao = _find_raw_file(
        ("votacao_secao_2024_GO.zip", "votacao_secao_2024_GO.csv")
    )
    locais = _find_raw_file(
        (
            "eleitorado_local_votacao_2024.zip",
            "eleitorado_local_votacao_2024.csv",
        )
    )
    candidatos = _find_raw_file(("consulta_cand_2024.zip", "consulta_cand_2024.csv"))

    if votacao and locais:
        data = build_pipeline_from_files(
            votacao,
            locais,
            candidatos,
            allow_network_geocode=False,
        )
        data.status = "Dados oficiais do TSE 2024 (processados a partir dos brutos)"
        return data

    return ElectionData(
        status=(
            "Sem dados processados. Use o botão de download do TSE na barra "
            "lateral ou coloque os arquivos oficiais em data/raw/."
        )
    )


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    parser = argparse.ArgumentParser(
        description="Processa os dados oficiais do TSE 2024 para Novo Gama (GO)."
    )
    parser.add_argument(
        "--download-tse",
        action="store_true",
        help="Baixa os pacotes oficiais e gera a base processada.",
    )
    parser.add_argument(
        "--reprocess",
        action="store_true",
        help="Reprocessa a partir dos arquivos já existentes em data/raw.",
    )
    args = parser.parse_args()

    if args.download_tse:
        def _cli_progress(pct: float, message: str) -> None:
            print(f"\r[{pct * 100:5.1f}%] {message}", end="", flush=True)

        result = download_and_process_tse_data(progress_callback=_cli_progress)
        print(f"\nBase gerada: {len(result.votacao)} registros em {PROCESSED_MERGED_FILE}")
    elif args.reprocess:
        votacao_zip = RAW_DIR / "votacao_secao_2024_GO.zip"
        locais_zip = RAW_DIR / "eleitorado_local_votacao_2024.zip"
        candidatos_zip = RAW_DIR / "consulta_cand_2024.zip"
        if not votacao_zip.exists() or not locais_zip.exists():
            raise SystemExit(
                "Arquivos oficiais ausentes em data/raw/. Rode --download-tse primeiro."
            )
        result = build_pipeline_from_files(
            votacao_zip,
            locais_zip,
            candidatos_zip if candidatos_zip.exists() else None,
        )
        print(f"Base reprocessada: {len(result.votacao)} registros")
        print(f"Locais: {len(result.locais)} · Candidatos: {len(result.resumo)}")
