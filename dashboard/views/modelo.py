"""04 · Desempeño del modelo: formulación, validación, métricas y diagnóstico."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import charts, data, ui
from core.catalog import (EVAL_BAND_LABELS, EVAL_BAND_ORDER, EVAL_DIMENSIONS, feature_group,
                          feature_label, month_label, segment_name)
from core.theme import AMBER, GRAY, INK, INK_2, NAVY, NAVY_100, NAVY_300, NAVY_900

metrics = data.model_metrics()
test = {r["modelo"]: r for r in metrics["test_metrics"]}
valid = {r["modelo"]: r for r in metrics["validation_comparison"]}
bv = metrics["bias_variance_diagnosis"]
cuts = metrics["temporal_cuts"]
lift_test = test["lightgbm"]["MAP@7"] / test["popularidad"]["MAP@7"] - 1
lift_valid = valid["lightgbm"]["MAP@7"] / valid["popularidad"]["MAP@7"] - 1

ui.page_header(
    "04", "Modelo y decisión · Desempeño",
    f"LightGBM supera al baseline de popularidad en validación (+{lift_valid * 100:.0f} %) y en "
    f"prueba (+{lift_test * 100:.0f} %), sin señales de sobreajuste fuerte",
    "El problema se plantea como <b>clasificación multiclase con ranking por propensión</b>: para "
    "cada cliente y mes se estima la probabilidad de que el próximo producto contratado sea cada uno "
    "de los 24; se excluye lo que ya tiene y se recomiendan los 7 más probables. Se evalúa con "
    "MAP@7 sobre meses que el modelo nunca vio.",
)

ui.kpi_row([
    {"label": "MAP@7 · prueba", "value": ui.fmt_dec(test["lightgbm"]["MAP@7"]), "accent": True,
     "note": f"baseline {ui.fmt_dec(test['popularidad']['MAP@7'])}"},
    {"label": "MAP@7 · validación", "value": ui.fmt_dec(valid["lightgbm"]["MAP@7"]),
     "note": f"baseline {ui.fmt_dec(valid['popularidad']['MAP@7'])}"},
    {"label": "Acierto en el Top-7 · prueba", "value": ui.fmt_pct(test["lightgbm"]["hit_rate@7"], 2),
     "note": f"baseline {ui.fmt_pct(test['popularidad']['hit_rate@7'], 2)} de los clientes"},
    {"label": "Variables del modelo", "value": str(metrics["feature_count"]),
     "note": "perfil, tenencia, rezagos 1/3/6 meses"},
    {"label": "Filas de entrenamiento", "value": ui.fmt_compact(metrics["rows"]["train"]),
     "note": f"{ui.fmt_compact(metrics['clients']['train'])} clientes"},
])

# --- Formulación y validación temporal ----------------------------------------------------
c1, c2 = st.columns([1.05, 1], gap="large")
with c1:
    with ui.card():
        ui.chart_title(
            "La validación respeta el tiempo: el modelo nunca ve el mes con el que se evalúa",
            "Partición fuera de tiempo (out-of-time). Cada fila usa variables del mes t para predecir "
            "las altas de t+1, así que no hay fuga de información del futuro.",
        )
        from core.catalog import MONTHS, month_short as _ms
        idx = {m: i for i, m in enumerate(MONTHS)}
        phases = [
            ("Entrenamiento", 0, idx[cuts["train_max_feature_month"]] + 1, NAVY,
             f"{ui.fmt_compact(metrics['rows']['train'])} filas"),
            ("Validación", idx[cuts["validation_month"]], idx[cuts["validation_month"]] + 1, NAVY_300,
             "elige hiperparámetros"),
            ("Prueba", idx[cuts["test_month"]], idx[cuts["test_month"]] + 1, AMBER,
             "una sola vez"),
            ("Inferencia", idx[cuts["inference_month"]], idx[cuts["inference_month"]] + 1, GRAY,
             "recomienda junio"),
        ]
        fig = go.Figure()
        for name, start_i, end_i, color, desc in phases:
            fig.add_bar(y=[name], x=[end_i - start_i], base=[start_i], orientation="h",
                        marker=dict(color=color, cornerradius=3), width=0.55, showlegend=False,
                        hovertemplate=f"{name}<br>{desc}<extra></extra>")
            fig.add_annotation(x=end_i + 0.2, y=name, text=desc, showarrow=False, xanchor="left",
                               font=dict(size=11, color=INK_2))
        ticks = list(range(0, len(MONTHS), 2))
        fig.update_layout(
            yaxis=dict(autorange="reversed", showgrid=False, tickfont=dict(size=12, color=INK)),
            xaxis=dict(range=[0, len(MONTHS) + 5.5], tickvals=ticks,
                       ticktext=[_ms(MONTHS[i]) for i in ticks], showgrid=True, gridcolor="#EDF0F4",
                       tickangle=0, title="Mes de las variables (t); la etiqueta es el mes t+1"),
            margin=dict(l=8, r=8, t=8, b=8), barmode="overlay",
        )
        ui.plot(fig, key="mod_split", height=260)
        ui.method(
            f"<b>Unidad de observación:</b> cliente × mes. <b>Objetivo:</b> producto que el cliente "
            f"contrata el mes siguiente (no lo tenía y lo tiene). <b>Supuestos:</b> el pasado "
            f"reciente predice el próximo mes; solo se recomiendan productos que el cliente no "
            f"tiene. <b>Restricción:</b> los meses con lags de 6 meses empiezan a tener historia "
            f"completa desde julio de 2015."
        )

with c2:
    with ui.card():
        ui.chart_title(
            f"En los dos meses de evaluación el modelo gana: +{lift_valid * 100:.0f} % y "
            f"+{lift_test * 100:.0f} % de MAP@7",
            "MAP@7 del modelo frente al baseline (ofrecer a todos los 7 productos más contratados del "
            "mes, excluyendo los que ya tiene). Mayor es mejor.",
        )
        groups = [f"Validación<br>{month_label(cuts['validation_month'])}",
                  f"Prueba<br>{month_label(cuts['test_month'])}"]
        base_vals = [valid["popularidad"]["MAP@7"], test["popularidad"]["MAP@7"]]
        model_vals = [valid["lightgbm"]["MAP@7"], test["lightgbm"]["MAP@7"]]
        fig = go.Figure()
        fig.add_bar(x=groups, y=base_vals, name="Baseline de popularidad",
                    marker=dict(color=GRAY, cornerradius=3),
                    text=[ui.fmt_dec(v) for v in base_vals], textposition="outside",
                    textfont=dict(color=INK_2), hovertemplate="Baseline<br>MAP@7 %{y:.4f}<extra></extra>")
        fig.add_bar(x=groups, y=model_vals, name="LightGBM",
                    marker=dict(color=NAVY, cornerradius=3),
                    text=[ui.fmt_dec(v) for v in model_vals], textposition="outside",
                    textfont=dict(color=NAVY_900), hovertemplate="LightGBM<br>MAP@7 %{y:.4f}<extra></extra>")
        fig.update_layout(barmode="group", bargap=0.35, bargroupgap=0.08,
                          yaxis=dict(title="MAP@7", range=[0, max(model_vals) * 1.25],
                                     tickformat=".3f"))
        ui.plot(fig, key="mod_compare", height=330)
        ui.note("MAP@7 premia que los productos que el cliente realmente contrató aparezcan arriba "
                "del ranking. Los clientes que no contratan nada cuentan como 0 (criterio de Kaggle), "
                "por eso los valores absolutos son bajos: el ganador de la competencia obtuvo ≈ 0,031.")

# --- Diagnóstico sesgo-varianza + hiperparámetros ---------------------------------------------
c3, c4 = st.columns(2, gap="large")
with c3:
    with ui.card():
        gap = bv["train_validation_gap"]
        ui.chart_title(
            f"La brecha entre entrenamiento y validación es pequeña ({ui.fmt_dec(gap)}): "
            "no hay sobreajuste fuerte",
            "MAP@7 del modelo final en cada partición. Si entrenamiento fuera muy superior a "
            "validación y prueba, el modelo estaría memorizando (alta varianza).",
        )
        stages = ["Entrenamiento", "Validación", "Prueba"]
        vals = [bv["train_MAP_at_7"], bv["validation_MAP_at_7"], test["lightgbm"]["MAP@7"]]
        fig = charts.vbar(stages, vals, text=[ui.fmt_dec(v) for v in vals],
                          hover="%{x}<br>MAP@7 %{y:.4f}<extra></extra>", y_title="MAP@7")
        fig.update_traces(marker=dict(color=[NAVY_300, NAVY, NAVY]))
        fig.update_layout(yaxis=dict(tickformat=".3f"))
        ui.plot(fig, key="mod_bv", height=300)

with c4:
    with ui.card():
        hp = data.model_csv("hyperparameter_search.csv").sort_values("validation_MAP_at_7",
                                                                     ascending=False)
        spread = hp["validation_MAP_at_7"].max() - hp["validation_MAP_at_7"].min()
        ui.chart_title(
            f"Las 4 configuraciones probadas difieren en solo {ui.fmt_dec(spread, 5)} de MAP@7: "
            "el modelo es estable",
            "Búsqueda en rejilla sobre los 24 productos a la vez, evaluada en validación con parada "
            "temprana. La elegida (ámbar) se reentrena y se mide una sola vez en prueba.",
        )
        labels = [f"hojas {int(r.num_leaves)} · lr {r.learning_rate} · min {int(r.min_data_in_leaf)} "
                  f"· ff {r.feature_fraction}" for r in hp.itertuples()]
        fig = go.Figure(go.Scatter(
            x=hp["validation_MAP_at_7"], y=labels, mode="markers+text",
            marker=dict(size=13, color=[AMBER] + [NAVY] * (len(hp) - 1),
                        line=dict(color="white", width=2)),
            text=[ui.fmt_dec(v, 5) for v in hp["validation_MAP_at_7"]],
            textposition="middle right", textfont=dict(size=11, color=INK_2),
            customdata=hp["best_iteration"],
            hovertemplate="%{y}<br>MAP@7 %{x:.5f}<br>%{customdata} iteraciones<extra></extra>",
        ))
        lo, hi = hp["validation_MAP_at_7"].min(), hp["validation_MAP_at_7"].max()
        fig.update_layout(xaxis=dict(range=[lo - (hi - lo) * 0.6, hi + (hi - lo) * 1.4],
                                     tickformat=".5f", showgrid=True, gridcolor="#EDF0F4",
                                     title="MAP@7 en validación"),
                          yaxis=dict(autorange="reversed", showgrid=False))
        ui.plot(fig, key="mod_hp", height=300)

# --- Desempeño por segmento --------------------------------------------------------------------
with ui.card():
    seg = data.model_csv("test_metrics_by_segment.csv")
    dim = st.segmented_control("Analizar errores por", list(EVAL_DIMENSIONS),
                               default="segmento", format_func=EVAL_DIMENSIONS.get,
                               key="mod_dim") or "segmento"
    part = seg[(seg["segmento"] == dim) & seg["segmento_valor"].notna() & (seg["clientes"] >= 1000)].copy()
    if dim == "segmento":
        part["label"] = part["segmento_valor"].map(segment_name)
        part = part[part["label"] != "Sin dato"].sort_values("MAP_at_7", ascending=False)
    elif dim in EVAL_BAND_ORDER:
        order = EVAL_BAND_ORDER[dim]
        part = part[part["segmento_valor"].isin(order)]
        part["o"] = part["segmento_valor"].map(order.index)
        part = part.sort_values("o")
        part["label"] = part["segmento_valor"].map(EVAL_BAND_LABELS)
    else:
        part["label"] = part["segmento_valor"]
    best, worst = part.loc[part["MAP_at_7"].idxmax()], part.loc[part["MAP_at_7"].idxmin()]
    overall = test["lightgbm"]["MAP@7"]
    ui.chart_title(
        f"El modelo acierta {best['MAP_at_7'] / worst['MAP_at_7']:.1f} veces más en «{best['label']}» "
        f"que en «{worst['label']}»".replace(".", ","),
        "MAP@7 en el mes de prueba por grupo de clientes (solo grupos con ≥ 1.000 clientes). La línea "
        "gris es el MAP@7 total. Los grupos con baja actividad comercial (jóvenes, universitarios) "
        "contratan poco y son más difíciles de anticipar.",
    )
    idx_best = list(part.index).index(best.name)
    fig = charts.vbar(part["label"], part["MAP_at_7"], text=[ui.fmt_dec(v) for v in part["MAP_at_7"]],
                      highlight=[idx_best],
                      hover="%{x}<br>MAP@7 %{y:.4f}<extra></extra>", y_title="MAP@7 (prueba)")
    fig.add_hline(y=overall, line=dict(color="#9AA5B4", width=1),
                  annotation_text=f"total {ui.fmt_dec(overall)}", annotation_position="top right",
                  annotation_font=dict(size=11, color=INK_2))
    fig.update_layout(yaxis=dict(tickformat=".3f"))
    ui.plot(fig, key="mod_seg", height=320)
    ui.data_table(part[["label", "clientes", "MAP_at_7", "hit_rate_at_7"]].rename(columns={
        "label": "Grupo", "clientes": "Clientes", "MAP_at_7": "MAP@7", "hit_rate_at_7": "Acierto Top-7"}),
        column_config={"MAP@7": st.column_config.NumberColumn(format="%.4f"),
                       "Acierto Top-7": st.column_config.NumberColumn(format="percent")})

# --- Importancia de variables ------------------------------------------------------------------
fi = data.model_csv("feature_importance.csv")
fi["share"] = fi["importance"] / fi["importance"].sum()
fi["group"] = fi["feature"].map(feature_group)
fi["label"] = fi["feature"].map(feature_label)
groups = fi.groupby("group")["share"].sum().sort_values(ascending=False)

c5, c6 = st.columns([1.5, 1], gap="large")
with c5:
    with ui.card():
        top = fi.head(15)
        ui.chart_title(
            f"Lo que el cliente ya tiene domina la predicción: «{top.iloc[0]['label']}» es la "
            "variable más importante",
            "Las 15 variables con mayor ganancia acumulada en los árboles (importancia «gain»), como "
            "porcentaje del total. Mide cuánto usa el modelo cada variable, no causalidad.",
        )
        fig = charts.hbar(top["label"], top["share"], text=[ui.fmt_pct(v, 1) for v in top["share"]],
                          highlight=[0], customdata=top["group"],
                          hover="%{y}<br>%{x:.1%} de la importancia<br>%{customdata}<extra></extra>")
        ui.plot(fig, key="mod_fi", height=470)
with c6:
    with ui.card():
        ui.chart_title(
            f"«{groups.index[0]}» concentra el {groups.iloc[0] * 100:.0f} % de la importancia",
            "Importancia total por familia de variables (las 142 del modelo).",
        )
        fig = charts.hbar(groups.index, groups.values,
                          text=[ui.fmt_pct(v, 0) for v in groups.values], highlight=[0],
                          hover="%{y}<br>%{x:.1%} de la importancia<extra></extra>")
        ui.plot(fig, key="mod_groups", height=230)
        ui.method(
            "<b>Lectura:</b> los rezagos (tenencia hace 1, 3 y 6 meses) y los movimientos del mes "
            "permiten detectar cambios recientes; el perfil (edad, antigüedad, canal, renta) ajusta "
            "la propensión. Esto es coherente con lo observado en <b>Transiciones</b>."
        )

with st.expander("Notas de método y limitaciones"):
    st.markdown(
        "- **Modelos comparados:** el pipeline de entrenamiento compara LightGBM (ensamble de "
        "árboles por *gradient boosting*) contra el baseline de popularidad. XGBoost y CatBoost, "
        "mencionados en la propuesta, no se ejecutaron en esta versión.\n"
        "- **Métrica:** MAP@7 se eligió porque es la métrica oficial de la competencia y premia el "
        "orden: un acierto en la posición 1 vale más que en la 7. El desbalance (la mayoría de "
        "clientes no contrata nada en un mes) hace inadecuada la exactitud (*accuracy*).\n"
        "- **Probabilidades:** los puntajes del modelo son valores de ranking multiclase, no "
        "probabilidades calibradas de compra independiente.\n"
        "- **Estacionalidad:** se valida en mayo; meses con estacionalidad fuerte (junio, por pago "
        "de impuestos) pueden comportarse distinto."
    )
