"""
Camada analítica do painel: agregações, benchmarks e formatação.

Todas as funções recebem DataFrames já tratados por ``src.data_loader`` e não
fazem I/O. Isso mantém o app.py focado em interface e facilita testes.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

import pandas as pd

from src.config import STATUS_COLORS, STATUS_LABELS
from src.geo_processor import normalize_text


# ---------------------------------------------------------------------------
# Formatação pt-BR
# ---------------------------------------------------------------------------
def format_int(value: object, fallback: str = "—") -> str:
    """Formata inteiro com separador de milhar brasileiro."""
    if value is None:
        return fallback
    try:
        if pd.isna(value):
            return fallback
    except (TypeError, ValueError):
        pass
    return f"{int(round(float(value))):,}".replace(",", ".")


def format_pct(value: object, decimals: int = 1, fallback: str = "—") -> str:
    """Formata percentual com vírgula decimal."""
    if value is None:
        return fallback
    try:
        if pd.isna(value):
            return fallback
    except (TypeError, ValueError):
        return fallback
    return f"{float(value):.{decimals}f}%".replace(".", ",")


def format_decimal(value: object, decimals: int = 1, fallback: str = "—") -> str:
    if value is None:
        return fallback
    try:
        if pd.isna(value):
            return fallback
    except (TypeError, ValueError):
        return fallback
    return f"{float(value):,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def status_color(status: str) -> str:
    return STATUS_COLORS.get(status, "#64748b")


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


# ---------------------------------------------------------------------------
# Totais gerais
# ---------------------------------------------------------------------------
def get_totals(votacao: pd.DataFrame) -> Dict[str, object]:
    """Totais da eleição para vereador em Novo Gama."""
    if votacao.empty:
        return {
            "total_votos": 0,
            "votos_validos": 0,
            "votos_nominais": 0,
            "votos_legenda": 0,
            "votos_branco": 0,
            "votos_nulos": 0,
            "n_secoes": 0,
            "n_locais": 0,
            "n_eleitores": 0,
            "n_candidatos": 0,
        }

    by_type = votacao.groupby("TP_VOTO", dropna=False)["QT_VOTOS"].sum()
    total = int(votacao["QT_VOTOS"].sum())
    nominal = int(by_type.get("Nominal", 0))
    legend = int(by_type.get("Legenda", 0))
    blank = int(by_type.get("Branco", 0))
    null = int(by_type.get("Nulo", 0))
    valid = nominal + legend

    sections = votacao[["NR_ZONA", "NR_SECAO"]].drop_duplicates()
    n_eleitores = int(
        votacao.drop_duplicates(subset=["NR_ZONA", "NR_SECAO"])["QT_ELEITOR_SECAO"].sum()
    )
    return {
        "total_votos": total,
        "votos_validos": valid,
        "votos_nominais": nominal,
        "votos_legenda": legend,
        "votos_branco": blank,
        "votos_nulos": null,
        "n_secoes": int(len(sections)),
        "n_locais": int(votacao["LOCAL_KEY"].nunique()),
        "n_eleitores": n_eleitores,
        "n_candidatos": int(votacao.loc[votacao["IS_CANDIDATO_NOMINAL"], "NR_VOTAVEL"].nunique()),
    }


# ---------------------------------------------------------------------------
# Resumo por candidato
# ---------------------------------------------------------------------------
def build_candidate_summary(
    votacao: pd.DataFrame, candidatos: pd.DataFrame
) -> pd.DataFrame:
    """
    Constrói o resumo de todos os candidatos do registro do TSE, inclusive os
    que não foram eleitos e os que tiveram zero voto.
    """
    totals = get_totals(votacao)
    valid_votes = max(int(totals["votos_validos"]), 0)
    nominal_votes = max(int(totals["votos_nominais"]), 0)
    total_votes = max(int(totals["total_votos"]), 0)

    candidate_votes = (
        votacao[votacao["TP_VOTO"].eq("Nominal")]
        .groupby("NR_VOTAVEL", as_index=False)["QT_VOTOS"]
        .sum()
        .rename(columns={"QT_VOTOS": "QT_VOTOS"})
    )

    summary = candidatos.copy()
    summary["NR_VOTAVEL"] = summary["NR_VOTAVEL"].astype(str)
    summary = summary.merge(candidate_votes, on="NR_VOTAVEL", how="left")
    summary["QT_VOTOS"] = summary["QT_VOTOS"].fillna(0).astype(int)

    # Ranking entre todos os candidatos nominais do registro.
    summary = summary.sort_values(
        ["QT_VOTOS", "NM_URNA_CANDIDATO", "NR_VOTAVEL"],
        ascending=[False, True, True],
    ).reset_index(drop=True)
    summary["RANKING"] = range(1, len(summary) + 1)

    summary["PCT_VALIDOS"] = (
        (summary["QT_VOTOS"] / valid_votes * 100.0) if valid_votes else 0.0
    ).round(2)
    summary["PCT_NOMINAIS"] = (
        (summary["QT_VOTOS"] / nominal_votes * 100.0) if nominal_votes else 0.0
    ).round(2)
    summary["PCT_TOTAL"] = (
        (summary["QT_VOTOS"] / total_votes * 100.0) if total_votes else 0.0
    ).round(2)

    votos_cand = votacao[votacao["TP_VOTO"].eq("Nominal") & votacao["QT_VOTOS"].gt(0)]
    if not votos_cand.empty:
        sec_count = (
            votos_cand.groupby("NR_VOTAVEL")[["NR_ZONA", "NR_SECAO"]]
            .apply(lambda group: len(group.drop_duplicates()))
            .rename("QTD_SECOES_COM_VOTO")
        )
        loc_count = (
            votos_cand.groupby("NR_VOTAVEL")["LOCAL_KEY"]
            .nunique()
            .rename("QTD_LOCAIS_COM_VOTO")
        )
        best_local = (
            votos_cand.groupby(["NR_VOTAVEL", "NM_LOCVOT"], as_index=False)["QT_VOTOS"]
            .sum()
            .sort_values(["NR_VOTAVEL", "QT_VOTOS"], ascending=[True, False])
            .drop_duplicates("NR_VOTAVEL")
            .set_index("NR_VOTAVEL")
        )
        summary = summary.merge(sec_count, on="NR_VOTAVEL", how="left")
        summary = summary.merge(loc_count, on="NR_VOTAVEL", how="left")
        summary = summary.merge(
            best_local[["QT_VOTOS", "NM_LOCVOT"]].rename(
                columns={
                    "QT_VOTOS": "MELHOR_LOCAL_VOTOS",
                    "NM_LOCVOT": "MELHOR_LOCAL",
                }
            ),
            on="NR_VOTAVEL",
            how="left",
        )
    for column in ["QTD_SECOES_COM_VOTO", "QTD_LOCAIS_COM_VOTO", "MELHOR_LOCAL_VOTOS"]:
        if column not in summary.columns:
            summary[column] = 0
        summary[column] = summary[column].fillna(0).astype(int)
    if "MELHOR_LOCAL" not in summary.columns:
        summary["MELHOR_LOCAL"] = ""
    summary["MELHOR_LOCAL"] = summary["MELHOR_LOCAL"].fillna("")

    summary["CANDIDATO_LABEL"] = summary.apply(
        lambda row: f"{row['NM_URNA_CANDIDATO']} ({row['SG_PARTIDO']})", axis=1
    )
    summary["BUSCA"] = (
        summary["NM_URNA_CANDIDATO"].astype(str)
        + " "
        + summary["NM_CANDIDATO"].astype(str)
        + " "
        + summary["NR_VOTAVEL"].astype(str)
        + " "
        + summary["SG_PARTIDO"].astype(str)
        + " "
        + summary["NM_PARTIDO"].astype(str)
    ).map(normalize_text)
    summary["SITUACAO"] = summary["SITUACAO"].fillna("Sem situação")
    summary["ORDEM_SITUACAO"] = summary["SITUACAO"].map(
        {"Eleito": 1, "Suplente": 2, "Não eleito": 3, "Sem situação": 4}
    ).fillna(9)
    return summary


def get_benchmarks(resumo: pd.DataFrame) -> Dict[str, object]:
    """Indicadores de contexto: vagas, corte dos eleitos e distorções do QP."""
    if resumo.empty:
        return {}

    eleitos = resumo[resumo["SITUACAO"].eq("Eleito")]
    nao_eleitos = resumo[resumo["SITUACAO"].eq("Não eleito")]
    suplentes = resumo[resumo["SITUACAO"].eq("Suplente")]

    min_eleito = int(eleitos["QT_VOTOS"].min()) if not eleitos.empty else 0
    max_nao_eleito = int(nao_eleitos["QT_VOTOS"].max()) if not nao_eleitos.empty else 0
    max_suplente = int(suplentes["QT_VOTOS"].max()) if not suplentes.empty else 0

    return {
        "vagas": int(len(eleitos)),
        "corte_eleitos": min_eleito,
        "media_eleitos": float(eleitos["QT_VOTOS"].mean()) if not eleitos.empty else 0.0,
        "mediana_eleitos": float(eleitos["QT_VOTOS"].median()) if not eleitos.empty else 0.0,
        "maior_nao_eleito": max_nao_eleito,
        "maior_suplente": max_suplente,
        "nao_eleitos_acima_do_corte": int(
            (nao_eleitos["QT_VOTOS"] >= min_eleito).sum()
        ) if min_eleito else 0,
        "eleitos_abaixo_do_maior_nao_eleito": int(
            (eleitos["QT_VOTOS"] < max_nao_eleito).sum()
        ) if max_nao_eleito else 0,
        "n_eleitos": int(len(eleitos)),
        "n_suplentes": int(len(suplentes)),
        "n_nao_eleitos": int(len(nao_eleitos)),
        "n_sem_situacao": int((resumo["SITUACAO"] == "Sem situação").sum()),
        "n_candidatos": int(len(resumo)),
    }


# ---------------------------------------------------------------------------
# Agregações geográficas
# ---------------------------------------------------------------------------
def aggregate_candidate_by_local(
    votacao: pd.DataFrame, nr_votavel: str
) -> pd.DataFrame:
    """Agrega os votos do candidato por local de votação."""
    if votacao.empty:
        return pd.DataFrame()

    nr_votavel = str(nr_votavel)
    valid = votacao[votacao["TP_VOTO"].isin(["Nominal", "Legenda"])]

    local_valid = (
        valid.groupby("LOCAL_KEY")["QT_VOTOS"].sum().rename("VOTOS_VALIDOS_LOCAL")
    )
    local_nominal = (
        valid[valid["TP_VOTO"].eq("Nominal")]
        .groupby("LOCAL_KEY")["QT_VOTOS"]
        .sum()
        .rename("VOTOS_NOMINAIS_LOCAL")
    )
    local_cand = (
        valid[valid["NR_VOTAVEL"].astype(str).eq(nr_votavel)]
        .groupby("LOCAL_KEY")["QT_VOTOS"]
        .sum()
        .rename("VOTOS_CANDIDATO")
    )
    local_sections = (
        votacao.drop_duplicates(subset=["NR_ZONA", "NR_SECAO"])
        .groupby("LOCAL_KEY")
        .agg(
            QTD_SECOES=("NR_SECAO", "nunique"),
            ELEITORADO=("QT_ELEITOR_SECAO", "sum"),
            NM_LOCVOT=("NM_LOCVOT", "first"),
            NM_BAIRRO=("NM_BAIRRO", "first"),
            DS_ENDERECO=("DS_ENDERECO", "first"),
            NR_ZONA=("NR_ZONA", "first"),
            NR_LATITUDE=("NR_LATITUDE", "first"),
            NR_LONGITUDE=("NR_LONGITUDE", "first"),
            PRECISAO=("PRECISAO", "first"),
            COORD_APROXIMADA=("COORD_APROXIMADA", "first"),
            USAR_NO_MAPA=("USAR_NO_MAPA", "first"),
            DIST_KM_CENTRO=("DIST_KM_CENTRO", "first"),
        )
    )
    sections_with_votes = (
        valid[valid["NR_VOTAVEL"].astype(str).eq(nr_votavel) & valid["QT_VOTOS"].gt(0)]
        .drop_duplicates(subset=["NR_ZONA", "NR_SECAO"])
        .groupby("LOCAL_KEY")["NR_SECAO"]
        .nunique()
        .rename("SECOES_COM_VOTO")
    )
    sections_list = (
        votacao.drop_duplicates(subset=["LOCAL_KEY", "NR_SECAO"])
        .sort_values(["LOCAL_KEY", "NR_SECAO"])
        .groupby("LOCAL_KEY")["NR_SECAO"]
        .apply(lambda values: ", ".join(str(int(v)) for v in values))
        .rename("LISTA_SECOES")
    )

    result = local_sections.join(local_valid).join(local_nominal).join(local_cand)
    result = result.join(sections_with_votes).join(sections_list)
    for column in [
        "VOTOS_VALIDOS_LOCAL",
        "VOTOS_NOMINAIS_LOCAL",
        "VOTOS_CANDIDATO",
        "SECOES_COM_VOTO",
    ]:
        if column not in result.columns:
            result[column] = 0
        result[column] = result[column].fillna(0).astype(int)

    total_candidate = int(result["VOTOS_CANDIDATO"].sum())
    result["PCT_CANDIDATO_NO_LOCAL"] = (
        result["VOTOS_CANDIDATO"]
        / result["VOTOS_VALIDOS_LOCAL"].replace(0, pd.NA)
        * 100.0
    ).fillna(0.0).round(2)
    result["PCT_DO_TOTAL_CANDIDATO"] = (
        result["VOTOS_CANDIDATO"] / total_candidate * 100.0
        if total_candidate
        else 0.0
    )
    result["PCT_DO_TOTAL_CANDIDATO"] = result["PCT_DO_TOTAL_CANDIDATO"].round(2)
    result["PCT_ELEITORADO"] = (
        result["VOTOS_CANDIDATO"] / result["ELEITORADO"].replace(0, pd.NA) * 100.0
    ).fillna(0.0).round(2)
    result["PARTICIPACAO_LOCAL"] = (
        result["VOTOS_VALIDOS_LOCAL"] / result["ELEITORADO"].replace(0, pd.NA) * 100.0
    ).fillna(0.0).round(2)
    result["MEDIA_VOTOS_SECAO"] = (
        result["VOTOS_CANDIDATO"] / result["QTD_SECOES"].replace(0, pd.NA)
    ).fillna(0.0).round(1)
    result["RANKING_LOCAL"] = (
        result["VOTOS_CANDIDATO"].rank(method="min", ascending=False).astype(int)
    )
    result = result.reset_index().sort_values(
        ["VOTOS_CANDIDATO", "NM_LOCVOT"], ascending=[False, True]
    ).reset_index(drop=True)
    return result


def aggregate_candidate_by_section(
    votacao: pd.DataFrame, nr_votavel: str
) -> pd.DataFrame:
    """Agrega os votos do candidato por seção eleitoral (urna)."""
    if votacao.empty:
        return pd.DataFrame()

    nr_votavel = str(nr_votavel)
    valid = votacao[votacao["TP_VOTO"].isin(["Nominal", "Legenda"])]
    base = votacao.drop_duplicates(subset=["NR_ZONA", "NR_SECAO"])[
        [
            "NR_ZONA",
            "NR_SECAO",
            "LOCAL_KEY",
            "NM_LOCVOT",
            "DS_ENDERECO",
            "NM_BAIRRO",
            "NR_LATITUDE",
            "NR_LONGITUDE",
            "PRECISAO",
            "COORD_APROXIMADA",
            "QT_ELEITOR_SECAO",
        ]
    ].copy()

    section_valid = (
        valid.groupby(["NR_ZONA", "NR_SECAO"])["QT_VOTOS"]
        .sum()
        .rename("VOTOS_VALIDOS_SECAO")
    )
    section_cand = (
        valid[valid["NR_VOTAVEL"].astype(str).eq(nr_votavel)]
        .groupby(["NR_ZONA", "NR_SECAO"])["QT_VOTOS"]
        .sum()
        .rename("VOTOS_CANDIDATO")
    )
    result = base.set_index(["NR_ZONA", "NR_SECAO"]).join(section_valid).join(section_cand)
    result["VOTOS_VALIDOS_SECAO"] = result["VOTOS_VALIDOS_SECAO"].fillna(0).astype(int)
    result["VOTOS_CANDIDATO"] = result["VOTOS_CANDIDATO"].fillna(0).astype(int)
    total_candidate = int(result["VOTOS_CANDIDATO"].sum())
    result["PCT_CANDIDATO_NO_SECAO"] = (
        result["VOTOS_CANDIDATO"]
        / result["VOTOS_VALIDOS_SECAO"].replace(0, pd.NA)
        * 100.0
    ).fillna(0.0).round(2)
    result["PCT_DO_TOTAL_CANDIDATO"] = (
        (result["VOTOS_CANDIDATO"] / total_candidate * 100.0)
        if total_candidate
        else 0.0
    )
    result["PCT_DO_TOTAL_CANDIDATO"] = result["PCT_DO_TOTAL_CANDIDATO"].round(2)
    result["PCT_ELEITORADO"] = (
        result["VOTOS_CANDIDATO"] / result["QT_ELEITOR_SECAO"].replace(0, pd.NA) * 100.0
    ).fillna(0.0).round(2)
    result = result.reset_index().sort_values(
        ["VOTOS_CANDIDATO", "NR_SECAO"], ascending=[False, True]
    )
    return result.reset_index(drop=True)


def aggregate_candidate_by_bairro(
    votacao: pd.DataFrame, nr_votavel: str
) -> pd.DataFrame:
    """Agrega os votos do candidato por bairro."""
    local = aggregate_candidate_by_local(votacao, nr_votavel)
    if local.empty:
        return local
    grouped = (
        local.groupby("NM_BAIRRO", as_index=False)
        .agg(
            VOTOS_CANDIDATO=("VOTOS_CANDIDATO", "sum"),
            VOTOS_VALIDOS=("VOTOS_VALIDOS_LOCAL", "sum"),
            ELEITORADO=("ELEITORADO", "sum"),
            LOCAIS=("LOCAL_KEY", "nunique"),
            SECOES=("QTD_SECOES", "sum"),
        )
        .sort_values("VOTOS_CANDIDATO", ascending=False)
        .reset_index(drop=True)
    )
    grouped["PCT_LOCAL"] = (
        grouped["VOTOS_CANDIDATO"] / grouped["VOTOS_VALIDOS"].replace(0, pd.NA) * 100.0
    ).fillna(0.0).round(2)
    return grouped


# ---------------------------------------------------------------------------
# Partidos e qualidade
# ---------------------------------------------------------------------------
def build_party_summary(resumo: pd.DataFrame) -> pd.DataFrame:
    """Resumo por partido, incluindo eleitos e não eleitos."""
    if resumo.empty:
        return pd.DataFrame()
    grouped = (
        resumo.groupby(["SG_PARTIDO", "NM_PARTIDO"], as_index=False)
        .agg(
            CANDIDATOS=("NR_VOTAVEL", "nunique"),
            ELEITOS=("ELEITO", "sum"),
            VOTOS=("QT_VOTOS", "sum"),
        )
        .sort_values(["ELEITOS", "VOTOS"], ascending=[False, False])
        .reset_index(drop=True)
    )
    grouped["SUPLENTES"] = grouped["SG_PARTIDO"].map(
        resumo[resumo["SITUACAO"].eq("Suplente")]
        .groupby("SG_PARTIDO")["NR_VOTAVEL"]
        .nunique()
    ).fillna(0).astype(int)
    grouped["NAO_ELEITOS"] = grouped["SG_PARTIDO"].map(
        resumo[resumo["SITUACAO"].eq("Não eleito")]
        .groupby("SG_PARTIDO")["NR_VOTAVEL"]
        .nunique()
    ).fillna(0).astype(int)
    grouped["ELEITOS"] = grouped["ELEITOS"].astype(int)
    return grouped


def build_quality_report(
    votacao: pd.DataFrame,
    locais: pd.DataFrame,
    resumo: pd.DataFrame,
) -> pd.DataFrame:
    """Checklist de qualidade dos dados e da geolocalização."""
    checks: List[Dict[str, object]] = []
    locais_unicos = (
        locais.drop_duplicates(subset=["LOCAL_KEY"]).copy()
        if "LOCAL_KEY" in locais.columns
        else locais.drop_duplicates(subset=["NM_LOCVOT"]).copy()
        if "NM_LOCVOT" in locais.columns
        else locais.copy()
    )
    n_locais = len(locais_unicos)
    n_oficiais = int((~locais_unicos["COORD_APROXIMADA"]).sum()) if "COORD_APROXIMADA" in locais_unicos else 0
    n_aproximadas = int(locais_unicos["COORD_APROXIMADA"].sum()) if "COORD_APROXIMADA" in locais_unicos else 0
    n_sem_mapa = int((~locais_unicos["USAR_NO_MAPA"]).sum()) if "USAR_NO_MAPA" in locais_unicos else 0

    duplicate_coords = 0
    if {"NR_LATITUDE", "NR_LONGITUDE"}.issubset(locais_unicos.columns):
        duplicate_coords = int(
            locais_unicos.duplicated(subset=["NR_LATITUDE", "NR_LONGITUDE"]).sum()
        )

    checks.append(
        {
            "VERIFICACAO": "Locais de votação distintos",
            "STATUS": "OK" if n_locais else "ERRO",
            "VALOR": format_int(n_locais),
            "DETALHE": "Um ponto por local; seções do mesmo local compartilham a coordenada.",
        }
    )
    checks.append(
        {
            "VERIFICACAO": "Coordenadas oficiais do TSE",
            "STATUS": "OK" if n_aproximadas == 0 else "ATENÇÃO",
            "VALOR": f"{format_int(n_oficiais)} de {format_int(n_locais)}",
            "DETALHE": "Fonte primária: NR_LATITUDE / NR_LONGITUDE do cadastro de locais do TSE.",
        }
    )
    checks.append(
        {
            "VERIFICACAO": "Coordenadas aproximadas",
            "STATUS": "OK" if n_aproximadas == 0 else "ATENÇÃO",
            "VALOR": format_int(n_aproximadas),
            "DETALHE": "Usam geocodificação ou centróide de bairro e aparecem com contorno tracejado.",
        }
    )
    checks.append(
        {
            "VERIFICACAO": "Coordenadas duplicadas entre locais",
            "STATUS": "OK" if duplicate_coords == 0 else "ATENÇÃO",
            "VALOR": format_int(duplicate_coords),
            "DETALHE": "Sobreposição exata de pontos distintos dificultaria a leitura do mapa.",
        }
    )
    checks.append(
        {
            "VERIFICACAO": "Locais fora da área de plotagem",
            "STATUS": "OK" if n_sem_mapa == 0 else "ATENÇÃO",
            "VALOR": format_int(n_sem_mapa),
            "DETALHE": "Coordenadas muito distantes do município são excluídas do mapa e listadas abaixo.",
        }
    )

    secoes_votacao = set(
        map(tuple, votacao[["NR_ZONA", "NR_SECAO"]].drop_duplicates().to_numpy())
    )
    secoes_locais = set(
        map(tuple, locais[["NR_ZONA", "NR_SECAO"]].drop_duplicates().to_numpy())
    ) if {"NR_ZONA", "NR_SECAO"}.issubset(locais.columns) else set()
    orfas = len(secoes_votacao - secoes_locais)
    checks.append(
        {
            "VERIFICACAO": "Seções da votação sem local correspondente",
            "STATUS": "OK" if orfas == 0 else "ATENÇÃO",
            "VALOR": format_int(orfas),
            "DETALHE": "O join é feito por NR_ZONA + NR_SECAO; seções órfãs recebem fallback.",
        }
    )

    if not resumo.empty:
        sem_votos = int((resumo["QT_VOTOS"] == 0).sum())
        checks.append(
            {
                "VERIFICACAO": "Candidatos no registro com zero voto",
                "STATUS": "OK",
                "VALOR": format_int(sem_votos),
                "DETALHE": "Permanecem no painel para retratar a disputa completa, inclusive não eleitos.",
            }
        )

        nominais = set(
            votacao.loc[votacao["TP_VOTO"].eq("Nominal"), "NR_VOTAVEL"].astype(str)
        )
        registrados = set(resumo["NR_VOTAVEL"].astype(str))
        sem_registro = len(nominais - registrados)
        checks.append(
            {
                "VERIFICACAO": "Votos nominais sem registro de candidato",
                "STATUS": "OK" if sem_registro == 0 else "ATENÇÃO",
                "VALOR": format_int(sem_registro),
                "DETALHE": "Números votados que não aparecem na consulta de candidatos do TSE.",
            }
        )

        status_counts = resumo["SITUACAO"].value_counts().to_dict()
        checks.append(
            {
                "VERIFICACAO": "Cobertura de situação eleitoral",
                "STATUS": "OK"
                if status_counts.get("Sem situação", 0) == 0
                else "ATENÇÃO",
                "VALOR": (
                    f"{format_int(status_counts.get('Eleito', 0))} eleitos · "
                    f"{format_int(status_counts.get('Suplente', 0))} suplentes · "
                    f"{format_int(status_counts.get('Não eleito', 0))} não eleitos"
                ),
                "DETALHE": "Situação oficial extraída de DS_SIT_TOT_TURNO (consulta_cand_2024).",
            }
        )

    return pd.DataFrame(checks)


def coordinate_provenance(locais: pd.DataFrame) -> pd.DataFrame:
    """Contagem de locais e seções por tipo de precisão da coordenada."""
    if locais.empty or "PRECISAO" not in locais.columns:
        return pd.DataFrame()
    unique = locais.drop_duplicates(subset=["LOCAL_KEY"]).copy()
    sections_per_local = locais.groupby("LOCAL_KEY")["NR_SECAO"].nunique()
    unique["SECOES"] = unique["LOCAL_KEY"].map(sections_per_local).fillna(0).astype(int)
    grouped = (
        unique.groupby("PRECISAO", as_index=False)
        .agg(LOCAIS=("LOCAL_KEY", "nunique"), SECOES=("SECOES", "sum"))
        .sort_values("LOCAIS", ascending=False)
    )
    return grouped


def approximate_locations(locais: pd.DataFrame) -> pd.DataFrame:
    """Lista os locais com coordenada aproximada para auditoria."""
    if locais.empty or "COORD_APROXIMADA" not in locais.columns:
        return pd.DataFrame()
    unique = locais.drop_duplicates(subset=["LOCAL_KEY"]).copy()
    return unique[unique["COORD_APROXIMADA"]][
        [
            "NM_LOCVOT",
            "DS_ENDERECO",
            "NM_BAIRRO",
            "PRECISAO",
            "COORD_OBS",
            "NR_LATITUDE",
            "NR_LONGITUDE",
            "DIST_KM_CENTRO",
        ]
    ].sort_values("NM_LOCVOT")


def filter_candidates(
    resumo: pd.DataFrame,
    statuses: Optional[Iterable[str]] = None,
    partidos: Optional[Iterable[str]] = None,
    search: str = "",
) -> pd.DataFrame:
    """Aplica os filtros da barra lateral sem esconder os não eleitos por padrão."""
    filtered = resumo.copy()
    if statuses:
        filtered = filtered[filtered["SITUACAO"].isin(list(statuses))]
    if partidos:
        filtered = filtered[filtered["SG_PARTIDO"].isin(list(partidos))]
    if search and search.strip():
        needle = normalize_text(search)
        filtered = filtered[filtered["BUSCA"].str.contains(needle, regex=False)]
    return filtered


def csv_bytes(df: pd.DataFrame) -> bytes:
    """CSV compatível com Excel brasileiro (UTF-8 com BOM e ponto e vírgula)."""
    return df.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")
